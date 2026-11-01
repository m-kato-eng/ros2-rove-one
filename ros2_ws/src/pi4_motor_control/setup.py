from glob import glob
from setuptools import find_packages, setup

setup(
    name='pi4_motor_control', version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/pi4_motor_control']),
        ('share/pi4_motor_control', ['package.xml', 'README.md']),
        ('share/pi4_motor_control/config', glob('config/*.yaml')),
        ('share/pi4_motor_control/launch', glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'], tests_require=['pytest'], zip_safe=True,
    maintainer='Pi4 project', maintainer_email='maintainer@example.invalid',
    description='Four motor L298N controller with a GPIO-free default mode.',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'motor_controller = pi4_motor_control.node:main',
    ]},
)
