#!/usr/bin/env python3
"""Run the read-only probe through SSH and save outside the managed repository."""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    managed = Path(__file__).resolve().parents[2]
    config_path = (args.config or managed / 'pc_controller/connection.json').resolve()
    config = json.loads(config_path.read_text(encoding='utf-8'))
    if config['host'].startswith('-'):
        raise ValueError('Invalid host')
    key = (config_path.parent / config['key']).resolve()
    known_hosts = (config_path.parent / config['known_hosts']).resolve()
    command = ['ssh', '-T', '-i', str(key), '-o', 'UserKnownHostsFile=' + str(known_hosts),
               '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes',
               '-o', 'ConnectTimeout=10', config['host'], 'python3 -']
    probe = Path(__file__).with_name('probe_linux.py').read_text(encoding='utf-8')
    result = subprocess.run(command, input=probe, text=True, encoding='utf-8',
                            capture_output=True, timeout=240)
    if result.returncode:
        raise RuntimeError('SSH collection failed: ' + result.stderr.strip())
    report = json.loads(result.stdout)
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d_%H%M%S_JST')
    destination = managed.parent / 'work_data/environment' / stamp
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'snapshot.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    if result.stderr:
        (destination / 'ssh-stderr.txt').write_text(result.stderr, encoding='utf-8')
    captured = 0
    for entry in report['files']:
        if entry['status'] != 'captured':
            continue
        relative = Path(entry['path'].lstrip('/'))
        if '..' in relative.parts or relative.is_absolute():
            raise ValueError('Unsafe path in probe output')
        target = destination / 'files' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(entry['content_b64'], validate=True))
        captured += 1
    for name, entry in report['commands'].items():
        if entry.get('returncode') == 0 and 'stdout' in entry:
            (destination / (name + '.txt')).write_text(entry['stdout'], encoding='utf-8')
    print(str(destination))
    print('Captured configuration files:', captured)
    print('Command collection results:', len(report['commands']))


if __name__ == '__main__':
    main()
