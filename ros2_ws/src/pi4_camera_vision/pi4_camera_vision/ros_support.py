import json
import math

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.clock import Clock, ClockType
from rclpy.executors import ExternalShutdownException
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


def image_qos():
    return QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)


def parameter(node, name, default, minimum=None, maximum=None):
    value = node.declare_parameter(
        name, default, ParameterDescriptor(read_only=True)).value
    if minimum is not None:
        if not math.isfinite(value) or value < minimum:
            raise ValueError(f'{name} must be finite and >= {minimum}')
    if maximum is not None and value > maximum:
        raise ValueError(f'{name} must be <= {maximum}')
    return value


def timer(node, period, callback):
    return node.create_timer(period, callback, clock=Clock(clock_type=ClockType.STEADY_TIME))


def publish_json(publisher, data):
    publisher.publish(String(data=json.dumps(data, ensure_ascii=False, allow_nan=False)))


def run(node_class, args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = node_class()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
