import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    config = os.path.join(get_package_share_directory('pi4_camera_vision'), 'config', 'camera.yaml')
    parameters = [LaunchConfiguration('config')]
    return LaunchDescription([
        DeclareLaunchArgument('config', default_value=config),
        DeclareLaunchArgument('http_preview', default_value='false'),
        DeclareLaunchArgument('local_preview', default_value='false'),
        Node(package='pi4_camera_vision', executable='camera_capture', name='camera_capture',
             output='screen', parameters=parameters + [{
                 'local_preview': ParameterValue(LaunchConfiguration('local_preview'), value_type=bool)}]),
        Node(package='pi4_camera_vision', executable='object_recognition', name='object_recognition',
             output='screen', parameters=parameters),
        Node(package='pi4_camera_vision', executable='camera_http_bridge', name='camera_http_bridge',
             output='screen', parameters=parameters,
             condition=IfCondition(LaunchConfiguration('http_preview'))),
    ])
