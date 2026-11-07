from glob import glob
from setuptools import find_packages, setup

setup(
    name='pi4_camera_vision', version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/pi4_camera_vision']),
        ('share/pi4_camera_vision', ['package.xml', 'README.md']),
        ('share/pi4_camera_vision/config', glob('config/*.yaml')),
        ('share/pi4_camera_vision/launch', glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'], tests_require=['pytest'], zip_safe=True,
    maintainer='Pi4 project', maintainer_email='maintainer@example.invalid',
    description='USB camera capture and pluggable object recognition.',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'camera_capture = pi4_camera_vision.capture_node:main',
        'object_recognition = pi4_camera_vision.recognition_node:main',
        'camera_http_bridge = pi4_camera_vision.http_node:main',
    ]},
)
