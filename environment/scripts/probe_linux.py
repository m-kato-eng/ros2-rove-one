#!/usr/bin/env python3
"""Read selected Linux configuration; emit JSON without writing remote files."""
import base64
import glob
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone


SENSITIVE = re.compile(
    r'(?i)(?:password|passwd|passphrase|psk|secret|token|credential)\s*[=:]|'
    r'-----BEGIN .*PRIVATE KEY-----|https?://[^\s/:]+:[^\s/@]+@')


def safe_content(text):
    for line in text.splitlines():
        if line.lstrip().startswith(('#', ';')):
            continue
        if SENSITIVE.search(line):
            return False
    return True


def command(argv, timeout=20):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                env={**os.environ, 'LC_ALL': 'C', 'SYSTEMD_COLORS': '0'})
        package_table = argv[0] == 'dpkg-query' and any(arg.startswith('-f=') for arg in argv)
        if package_table:
            # Validate structured public metadata separately from free text.
            valid = True
            for line in result.stdout.splitlines():
                fields = line.split('\t')
                valid = valid and len(fields) == 4
                if len(fields) == 4:
                    valid = valid and bool(re.fullmatch(r'[a-z0-9][a-z0-9+.:\-]*', fields[0]))
                    valid = valid and bool(re.fullmatch(r'[A-Za-z0-9.+:~_\-]*', fields[1]))
                    valid = valid and bool(re.fullmatch(r'[a-z0-9\-]*', fields[2]))
                    valid = valid and bool(re.fullmatch(r'[a-z\-]+', fields[3]))
            if not valid:
                return {'argv': argv, 'returncode': result.returncode, 'withheld': True,
                        'reason': 'unexpected_package_table_format'}
        if (not package_table and not safe_content(result.stdout)) or not safe_content(result.stderr):
            return {'argv': argv, 'returncode': result.returncode, 'withheld': True}
        return {'argv': argv, 'returncode': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'argv': argv, 'returncode': None, 'error': str(exc)}


def main():
    if platform.system() != 'Linux':
        raise RuntimeError('Run the probe on Linux')
    report = {'collected_at_utc': datetime.now(timezone.utc).isoformat(),
              'kernel': platform.release(), 'architecture': platform.machine(),
              'files': [], 'commands': {}, 'systemd_links': []}
    home = Path.home()
    paths = [
        '/etc/os-release', '/boot/firmware/config.txt', '/boot/firmware/usercfg.txt',
        '/boot/firmware/syscfg.txt', '/boot/firmware/cmdline.txt',
        '/etc/X11/default-display-manager', '/etc/gdm3/custom.conf',
        '/etc/gdm3/daemon.conf', '/etc/lightdm/lightdm.conf',
        '/etc/sysctl.conf', '/etc/fstab', '/etc/dphys-swapfile',
        '/etc/modules', '/etc/default/keyboard', '/etc/default/locale',
        '/etc/environment', '/etc/default/grub',
        str(home / '.xsession'), str(home / '.xsessionrc'),
        str(home / '.xinitrc'), str(home / '.dmrc'),
    ]
    patterns = [
        '/etc/sysctl.d/*.conf', '/etc/modules-load.d/*.conf', '/etc/modprobe.d/*.conf',
        '/etc/lightdm/lightdm.conf.d/*.conf', '/etc/gdm3/greeter.dconf-defaults',
        '/etc/systemd/system/*.service', '/etc/systemd/system/*.service.d/*.conf',
        '/etc/udev/rules.d/*.rules', '/etc/xdg/autostart/*.desktop',
        '/usr/share/xsessions/*.desktop',
        str(home / '.config/autostart/*.desktop'),
        str(home / '.config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml'),
        str(home / '.config/xfce4/xfconf/xfce-perchannel-xml/displays.xml'),
        str(home / '.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-session.xml'),
        str(home / '.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml'),
    ]
    for pattern in patterns:
        paths.extend(glob.glob(pattern))
    for link in sorted(Path('/etc/systemd/system').rglob('*')):
        if link.is_symlink():
            report['systemd_links'].append({'path': str(link), 'target': os.readlink(link)})
    seen = set()
    # Follow boot include directives only within /boot, bounded to 32 files.
    boot_includes = 0
    index = 0
    while index < len(paths):
        raw = paths[index]
        index += 1
        if raw in seen:
            continue
        seen.add(raw)
        path = Path(raw)
        entry = {'path': raw}
        try:
            metadata = path.stat()
            if not stat.S_ISREG(metadata.st_mode):
                entry['status'] = 'not_regular'
            elif metadata.st_size > 262144:
                entry['status'] = 'too_large'
            else:
                data = path.read_bytes()
                text = data.decode('utf-8')
                if not safe_content(text):
                    entry['status'] = 'withheld_sensitive_pattern'
                else:
                    entry.update(status='captured', content_b64=base64.b64encode(data).decode(),
                                 mode=oct(stat.S_IMODE(metadata.st_mode)), uid=metadata.st_uid,
                                 gid=metadata.st_gid, symlink_target=os.readlink(path) if path.is_symlink() else None)
                    if raw.startswith('/boot/'):
                        for include in re.findall(r'^\s*include\s+([^\s#]+)', text, re.M):
                            candidate = (path.parent / include).resolve()
                            if candidate.is_relative_to(Path('/boot')) and boot_includes < 32:
                                paths.append(str(candidate))
                                boot_includes += 1
        except FileNotFoundError:
            entry['status'] = 'missing'
        except PermissionError:
            entry['status'] = 'permission_denied'
        except (OSError, UnicodeError) as exc:
            entry.update(status='unreadable', error=str(exc))
        report['files'].append(entry)
    commands = {
        'packages': ['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n'],
        'manual_packages': ['apt-mark', 'showmanual'],
        'python_version': ['python3', '--version'],
        'python_packages': ['python3', '-m', 'pip', '--disable-pip-version-check', 'list', '--format=json'],
        'snap_packages': ['snap', 'list'],
        'service_units': ['systemctl', 'list-unit-files', '--type=service', '--no-pager', '--no-legend'],
        'default_target': ['systemctl', 'get-default'],
        'display_manager': ['readlink', '-f', '/etc/systemd/system/display-manager.service'],
        'boot_time': ['systemd-analyze', 'time'],
        'boot_blame': ['systemd-analyze', 'blame', '--no-pager'],
        'boot_chain': ['systemd-analyze', 'critical-chain', '--no-pager'],
        'loaded_modules': ['lsmod'],
        'swap': ['swapon', '--show', '--bytes'],
        'swappiness': ['sysctl', '-n', 'vm.swappiness'],
        'gpio_device': ['stat', '-c', '%U %G %a', '/dev/gpiomem'],
        'groups': ['id', '-nG'],
        'xfce_version': ['dpkg-query', '-W', 'xfce4-session', 'xfce4'],
        'xorg_version': ['dpkg-query', '-W', 'xserver-xorg-core'],
    }
    for name, argv in commands.items():
        report['commands'][name] = command(argv)
    units = report['commands']['service_units']
    if units.get('returncode') == 0 and 'stdout' in units:
        enabled = [line for line in units['stdout'].splitlines()
                   if len(line.split()) >= 2 and line.split()[1] in ('enabled', 'enabled-runtime')]
        report['commands']['enabled_units'] = {
            'returncode': 0, 'derived_from': 'service_units',
            'stdout': '\n'.join(enabled) + '\n', 'stderr': ''}
    # Read only known ROS source lines, never dump the complete shell environment.
    bashrc = home / '.bashrc'
    if bashrc.is_file():
        text = bashrc.read_text(encoding='utf-8')
        report['ros_shell_lines'] = [line for line in text.splitlines()
                                     if line.strip() == 'source /opt/ros/humble/setup.bash']
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
