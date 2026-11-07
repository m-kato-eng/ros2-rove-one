"""Stop this user's camera launch/nodes and their GStreamer child, never motors."""
import os
from pathlib import Path
import signal
import time


def read_process(path):
    try:
        if path.stat().st_uid != os.getuid():
            return None
        args = (path / 'cmdline').read_bytes().split(b'\0')
        status = (path / 'status').read_text()
        ppid = int(next(line.split()[1] for line in status.splitlines() if line.startswith('PPid:')))
        return args, ppid
    except (FileNotFoundError, PermissionError, ProcessLookupError, StopIteration):
        return None


processes = {int(path.name): info for path in Path('/proc').iterdir()
             if path.name.isdigit() and (info := read_process(path)) is not None}
nodes = {}
for pid, (args, _) in processes.items():
    executable = args[1] if len(args) > 1 else b''
    if any(executable.endswith(b'/lib/pi4_camera_vision/' + name)
           for name in (b'camera_capture', b'object_recognition', b'camera_http_bridge')):
        nodes[pid] = args
    elif len(args) > 4 and args[1].endswith(b'/ros2') and args[2:4] == [b'launch', b'pi4_camera_vision']:
        nodes[pid] = args
children = {pid: args for pid, (args, parent) in processes.items()
            if parent in nodes and args[0].endswith(b'gst-launch-1.0')}
for pid in nodes:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
deadline = time.monotonic() + 7
while time.monotonic() < deadline:
    if not any((current := read_process(Path('/proc') / str(pid))) and current[0] == args
               for pid, args in nodes.items()):
        break
    time.sleep(0.1)
for pid, args in children.items():
    current = read_process(Path('/proc') / str(pid))
    if current and current[0] == args:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
remaining = [pid for pid, args in nodes.items()
             if (current := read_process(Path('/proc') / str(pid))) and current[0] == args]
if remaining:
    raise RuntimeError(f'Camera processes did not stop: {remaining}')
print('Camera processes stopped; motor processes were not targeted.')
