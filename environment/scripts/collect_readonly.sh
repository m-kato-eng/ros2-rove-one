#!/usr/bin/env bash
# Read public system metadata and print it; no configuration changes or sudo.
set -euo pipefail

if [[ "$(uname -s)" != Linux ]]; then
    printf '%s\n' 'Run this script on the Raspberry Pi Linux system.' >&2
    exit 2
fi

section() { printf '\n=== %s ===\n' "$1"; }

section 'Collection time'
date -Is
section 'OS'
cat /etc/os-release
section 'Kernel and architecture'
uname -r
uname -m
section 'APT package versions and package status'
dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n'
section 'Manually selected APT packages'
apt-mark showmanual
section 'Python'
python3 --version
if python3 -m pip --version >/dev/null 2>&1; then
    python3 -m pip --disable-pip-version-check list --format=json
fi
section 'Enabled service unit files'
systemctl list-unit-files --state=enabled --no-pager --no-legend
section 'Loaded kernel modules (not a persistent loading configuration)'
lsmod
section 'Selected boot configuration keys only'
if [[ -r /boot/firmware/config.txt ]]; then
    grep -E '^[[:space:]]*(arm_boost|dtoverlay|disable_fw_kms_setup|hdmi_force_hotplug|hdmi_group|hdmi_mode|gpu_mem|dtparam|arm_64bit)=' /boot/firmware/config.txt || true
fi
section 'GPIO device ownership and permissions'
if [[ -e /dev/gpiomem ]]; then
    stat -c '%U %G %a' /dev/gpiomem
fi
section 'ROS shell initialization line only'
if [[ -r "$HOME/.bashrc" ]]; then
    grep -F 'source /opt/ros/humble/setup.bash' "$HOME/.bashrc" || true
fi
section 'Swap configuration value'
cat /proc/sys/vm/swappiness
section 'End of collection'
