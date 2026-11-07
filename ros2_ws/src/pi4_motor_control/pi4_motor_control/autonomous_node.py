"""Periodic target conversion; PC bridge selects the active command source."""
import json
import time
import rclpy
from rclpy.node import Node
from rclpy.clock import Clock, ClockType
from std_msgs.msg import String
from .autonomy import plan


class AutonomousDriving(Node):
    def __init__(self):
        super().__init__('autonomous_driving')
        self.horizon = self.declare_parameter('horizon_y', 0.5).value
        if not 0 <= self.horizon < 0.75:
            raise ValueError('horizon_y must be in [0, 0.75)')
        self.latest = None
        self.received = 0.0
        self.frame_stamp = None
        self.publisher = self.create_publisher(String, 'autonomous/command', 1)
        self.create_subscription(String, '/vision/ground_target', self.receive, 1)
        self.steady = Clock(clock_type=ClockType.STEADY_TIME)
        self.create_timer(0.1, self.tick, clock=self.steady)

    def receive(self, msg):
        try:
            data = json.loads(msg.data)
            if data.get('target_valid') is not True:
                self.latest = None
                return
            stamp = data['source_frame']['stamp']
            seconds = stamp['sec'] + stamp['nanosec']/1e9
            age = self.get_clock().now().nanoseconds/1e9-seconds
            if not 0 <= age <= 1.5:
                raise ValueError('stale frame')
            if stamp == self.frame_stamp:
                return
            self.frame_stamp = stamp
            self.latest = data
            self.received = time.monotonic()-age
        except (ValueError, TypeError, KeyError, AttributeError):
            self.latest = None

    def tick(self):
        data = self.latest if time.monotonic()-self.received <= 1.5 else None
        self.publisher.publish(String(data=json.dumps(plan(data, self.horizon), allow_nan=False)))


def main(args=None):
    rclpy.init(args=args)
    node = AutonomousDriving()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
