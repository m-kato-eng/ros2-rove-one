"""Periodic target conversion; PC bridge selects the active command source."""
import json
import time
import rclpy
from rclpy.node import Node
from rclpy.clock import Clock, ClockType
from std_msgs.msg import String
from .autonomy import plan
from .prediction import TargetPredictor


class AutonomousDriving(Node):
    def __init__(self):
        super().__init__('autonomous_driving')
        self.horizon = self.declare_parameter('horizon_y', 0.5).value
        if not 0 <= self.horizon < 0.75:
            raise ValueError('horizon_y must be in [0, 0.75)')
        self.target_timeout = self.declare_parameter('target_timeout_sec', 0.3).value
        if not 0 < self.target_timeout <= 1.5:
            raise ValueError('target_timeout_sec must be in (0, 1.5]')
        grace = self.declare_parameter('prediction_timeout_sec', 1.0).value
        if not 0 <= grace <= 1.0:
            raise ValueError('prediction_timeout_sec must be in [0, 1]')
        self.predictor = TargetPredictor(self.horizon, self.target_timeout, grace)
        self.latest = None
        self.received = 0.0
        self.frame_stamp = None
        self.publisher = self.create_publisher(String, 'autonomous/command', 1)
        self.create_subscription(String, '/vision/ground_target', self.receive, 1)
        self.steady = Clock(clock_type=ClockType.STEADY_TIME)
        self.create_timer(0.05, self.tick, clock=self.steady)

    def receive(self, msg):
        try:
            data = json.loads(msg.data)
            if data.get('target_valid') is not True and not (
                    data.get('state') in ('lost', 'searching') and
                    data.get('reason') in ('no_candidate', 'confirming_candidate', '')):
                self.predictor.clear()
                self.latest = None
                return
            stamp = data['source_frame']['stamp']
            seconds = stamp['sec'] + stamp['nanosec']/1e9
            age = self.get_clock().now().nanoseconds/1e9-seconds
            if not 0 <= age <= self.target_timeout:
                raise ValueError('stale frame')
            stamp_key = (stamp['sec'], stamp['nanosec'])
            if self.frame_stamp is not None and stamp_key <= self.frame_stamp:
                return
            self.frame_stamp = stamp_key
            self.received = time.monotonic()-age
            if data.get('target_valid') is True and data.get('state') == 'tracking':
                self.predictor.observe(data, self.received)
                self.latest = data
            elif (data.get('state') in ('lost', 'searching') and
                  data.get('reason') in ('no_candidate', 'confirming_candidate', '')):
                self.predictor.miss(self.received)
                self.latest = None
            else:
                self.predictor.clear()
                self.latest = None
        except (ValueError, TypeError, KeyError, AttributeError):
            self.predictor.clear()
            self.latest = None

    def tick(self):
        command = self.predictor.command(time.monotonic())
        self.publisher.publish(String(data=json.dumps(command, allow_nan=False)))


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
