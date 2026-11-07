"""Standard-library-only SSH JSON transport. No ROS installation on Windows."""
import json
import math
from pathlib import Path
import queue
import shlex
import subprocess
import threading
import time


class Connection:
    def __init__(self, config_path=None, log_name='pc-events.jsonl', dry_run=None):
        self.base = Path(__file__).resolve().parent
        config_path = Path(config_path) if config_path else self.base / 'connection.json'
        self.config = json.loads(config_path.read_text(encoding='utf-8'))
        self.dry_run = self.config.get('dry_run', True) if dry_run is None else dry_run
        if type(self.dry_run) is not bool:
            raise ValueError('dry_run must be boolean')
        for field in ('key', 'known_hosts'):
            self.config[field] = str((config_path.resolve().parent / self.config[field]).resolve())
            if not Path(self.config[field]).is_file():
                raise ValueError(field + ' file does not exist')
        domain = self.config['ros_domain_id']
        if type(domain) is not int or not 0 <= domain <= 101:
            raise ValueError('ros_domain_id must be an integer in 0..101')
        if self.config['host'].startswith('-'):
            raise ValueError('invalid SSH host')
        self.process = None
        self.events = queue.Queue()
        self.ready = False
        self.status = None
        self.status_at = 0.0
        self.sequence = 0
        self.lock = threading.Lock()
        self.log_lock = threading.Lock()
        log_directory = self.config.get('log_directory', 'logs')
        self.log_path = (config_path.resolve().parent / log_directory).resolve() / log_name
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, message):
        with self.log_lock:
            with self.log_path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'time': time.time(), **message}, ensure_ascii=False) + '\n')

    def connect(self):
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError('already connected')
        self.ready, self.status, self.status_at = False, None, 0.0
        workspace = self.config['remote_workspace']
        command = ' && '.join([
            'source /opt/ros/humble/setup.bash',
            'source ' + shlex.quote(workspace + '/install/setup.bash'),
            'export ROS_DOMAIN_ID=' + str(self.config['ros_domain_id']),
            'exec python3 -u ' + shlex.quote(workspace + '/src/pi4_motor_control/scripts/pc_bridge.py') +
            ('' if self.dry_run else ' --hardware'),
        ])
        args = ['ssh', '-T', '-i', self.config['key'],
                '-o', 'UserKnownHostsFile=' + self.config['known_hosts'],
                '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes',
                '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=2',
                '-o', 'ServerAliveCountMax=2', self.config['host'],
                'bash -c ' + shlex.quote(command)]
        self.process = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        process = self.process
        self.record({'type': 'connect', 'host': self.config['host'], 'dry_run': self.dry_run})
        threading.Thread(target=self._read, args=(process,), daemon=True).start()
        threading.Thread(target=self._errors, args=(process,), daemon=True).start()

    def _read(self, process):
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError('expected JSON object')
                except ValueError:
                    self.events.put({'type': 'error', 'message': 'Invalid bridge output: ' + line[:200]})
                    continue
                if message.get('type') == 'ready':
                    if message.get('dry_run') is not self.dry_run:
                        self.events.put({'type': 'error', 'message': 'Bridge mode mismatch'})
                        process.terminate()
                        break
                    self.ready = True
                elif message.get('type') == 'status':
                    if message['status'].get('dry_run') is not self.dry_run:
                        self.ready = False
                        process.terminate()
                        break
                    self.status = message['status']
                    self.status_at = time.monotonic()
                self.record(message)
                self.events.put(message)
        finally:
            if self.process is process:
                self.ready = False
            self.events.put({'type': 'disconnected', 'message': 'SSH session ended'})

    def _errors(self, process):
        for line in process.stderr:
            message = {'type': 'error', 'message': line.rstrip()[:1000]}
            self.record(message)
            self.events.put(message)

    def send(self, message):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                raise ConnectionError('SSH is not connected')
            try:
                self.process.stdin.write(json.dumps(message, allow_nan=False) + '\n')
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self.ready = False
                raise ConnectionError('SSH connection lost') from exc

    def drive(self, linear=0.0, angular=0.0):
        if not all(math.isfinite(v) for v in (linear, angular)):
            raise ValueError('drive values must be finite')
        self.send({'op': 'drive', 'linear': float(linear), 'angular': float(angular)})

    def wheel(self, motor, speed):
        if motor not in ('left_front', 'left_rear', 'right_front', 'right_rear') or not math.isfinite(speed) or abs(speed) > 0.3:
            raise ValueError('invalid wheel command')
        self.send({'op': 'wheel', 'motor': motor, 'speed': float(speed)})

    def steer(self, speed=0.0, turn=0.0):
        if any(not math.isfinite(v) or abs(v) > 0.3 for v in (speed, turn)):
            raise ValueError('invalid steering command')
        self.send({'op': 'steer', 'speed': float(speed), 'turn': float(turn)})

    def request(self, op, value):
        if not ((op in ('enable', 'estop') and type(value) is bool) or
                (op == 'source' and value in ('manual', 'auto'))):
            raise ValueError('invalid request')
        self.sequence += 1
        self.send({'op': op, 'value': value, 'id': self.sequence})
        self.record({'type': 'request', 'op': op, 'value': value, 'id': self.sequence})
        return self.sequence

    def close(self):
        process = self.process
        self.ready = False
        if process is None:
            return
        if process.poll() is None:
            try:
                self.drive()
                self.request('enable', False)
                self.send({'op': 'shutdown'})
                process.stdin.close()
            except (ConnectionError, ValueError, OSError):
                pass
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        self.record({'type': 'closed', 'returncode': process.returncode})
        self.process = None
