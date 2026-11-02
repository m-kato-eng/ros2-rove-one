"""Subscribe to Twist; default to disarmed, GPIO-free simulation."""
import json
import math
import signal

import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import QoSProfile
from rcl_interfaces.msg import ParameterDescriptor
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from std_srvs.srv import SetBool

from .backends import DryRunBackend, GpioBackend, MOTORS
from .control import Controller, Limits


class MotorNode(Node):
    def __init__(self):
        super().__init__('motor_controller')
        self.backend = None
        self.control = None
        self._closed = False
        try:
            self._configure()
        except BaseException:
            if self.backend is not None:
                self.backend.close()
            self.destroy_node()
            raise

    def param(self, name, default):
        return self.declare_parameter(
            name, default, ParameterDescriptor(read_only=True)).value

    def _configure(self):
        self.dry_run = self.param('dry_run', True)
        confirmed = self.param('hardware_confirmed', False)
        limits = Limits(**{name: self.param(name, default)
                           for name, default in vars(Limits()).items()})
        rate = self.param('control_rate', 50.0)
        if not math.isfinite(rate) or not 10 <= rate <= 100:
            raise ValueError('control_rate must be in 10..100 Hz')
        frequency = self.param('pwm_frequency', 100.0)
        pins = {name: self.param(f'{name}.pins', [-1, -1, -1]) for name in MOTORS}
        self.invert = [self.param(f'{name}.invert', False) for name in MOTORS]
        self.control = Controller(limits)
        self.backend = (DryRunBackend() if self.dry_run else
                        GpioBackend(pins, frequency, confirmed))
        self.publisher = self.create_publisher(String, '~/status', 1)
        self.subscription = self.create_subscription(
            Twist, 'cmd_vel', self.on_command, QoSProfile(depth=1))
        self.wheel_subscription = self.create_subscription(
            String, 'wheel_command', self.on_wheel_command, QoSProfile(depth=1))
        self.enable_service = self.create_service(SetBool, '~/enable', self.on_enable)
        self.estop_service = self.create_service(
            SetBool, '~/emergency_stop', self.on_estop)
        # ROS /clock pausing must never suspend the command watchdog.
        self.steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self.timer = self.create_timer(1 / rate, self.on_tick, clock=self.steady_clock)
        self.status_timer = self.create_timer(0.1, self.publish_status, clock=self.steady_clock)
        self.get_logger().info(
            f'Started dry_run={self.dry_run}; DISABLED; explicit enable required')

    def on_command(self, msg):
        values = [msg.linear.x, msg.linear.y, msg.linear.z,
                  msg.angular.x, msg.angular.y, msg.angular.z]
        if (not all(math.isfinite(v) for v in values) or
                any(v != 0 for v in values[1:5])):
            self.control.stop('invalid_command')
        else:
            self.control.command(msg.linear.x, msg.angular.z)
        self.on_tick()

    def on_enable(self, request, response):
        response.success = self.control.enable(request.data)
        response.message = self.control.reason
        self.on_tick()
        return response

    def on_wheel_command(self, msg):
        try:
            command = json.loads(msg.data)
            if command.get('mode') == 'steer':
                speed, turn = command['speed'], command['turn']
                if any(type(v) not in (int, float) for v in (speed, turn)):
                    raise ValueError('invalid steering command')
                self.control.steer_command(speed, turn)
                self.on_tick()
                return
            motor, speed = command['motor'], command['speed']
            if type(motor) is not str or type(speed) not in (int, float):
                raise ValueError('invalid wheel command')
            self.control.wheel_command(motor, speed)
        except (ValueError, KeyError, TypeError):
            self.control.stop('invalid_command')
        self.on_tick()

    def on_estop(self, request, response):
        self.control.emergency_stop(request.data)
        self.on_tick()
        response.success = True
        response.message = self.control.reason
        return response

    def on_tick(self):
        duties = self.control.outputs()
        self.backend.write([-v if inv else v for v, inv in zip(duties, self.invert)])

    def publish_status(self):
        self.publisher.publish(String(data=json.dumps({
            'dry_run': self.dry_run, 'enabled': self.control.enabled,
            'emergency_stop': self.control.estop, 'reason': self.control.reason,
            'duties': dict(zip(MOTORS, self.backend.duties)),
        }, allow_nan=False)))

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.control is not None:
            self.control.stop('shutdown')
        if self.backend is not None:
            self.backend.close()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = MotorNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        # ros2 launch/process groups can deliver SIGINT more than once.
        # Do not allow a second KeyboardInterrupt to abort motor cleanup.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            if node is not None:
                try:
                    node.close()
                finally:
                    node.destroy_node()
        finally:
            if rclpy.ok():
                rclpy.shutdown()
