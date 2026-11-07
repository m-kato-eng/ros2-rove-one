#!/usr/bin/env bash
set -e
workspace=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
source /opt/ros/humble/setup.bash
source "$workspace/install/setup.bash"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-88}"
exec ros2 launch pi4_camera_vision camera_vision.launch.py "$@"
