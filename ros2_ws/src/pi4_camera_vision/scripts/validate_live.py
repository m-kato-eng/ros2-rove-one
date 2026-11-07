"""Read-only integration probe. Run while camera_vision.launch.py is active."""
import json
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from pi4_camera_vision.core import jpeg_dimensions
from pi4_camera_vision.ros_support import image_qos


def main():
    rclpy.init()
    node = Node('camera_live_validation')
    images, results, statuses, times = [], [], [], []

    def image(msg):
        assert msg.format == 'jpeg'
        dimensions = jpeg_dimensions(bytes(msg.data))
        assert dimensions == (320, 240), dimensions
        assert msg.header.frame_id == 'camera_optical_frame'
        images.append((msg.header.stamp.sec, msg.header.stamp.nanosec))
        times.append(time.monotonic())

    node.create_subscription(CompressedImage, '/camera/image/compressed', image, image_qos())
    node.create_subscription(String, '/vision/detections', lambda msg: results.append(json.loads(msg.data)), 1)
    node.create_subscription(String, '/camera/status', lambda msg: statuses.append(json.loads(msg.data)), 1)
    try:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and (len(images) < 40 or len(results) < 4 or not statuses):
            rclpy.spin_once(node, timeout_sec=0.2)
        assert len(images) >= 40, f'Only {len(images)} images'
        assert len(set(images)) == len(images), 'Duplicate image stamps'
        assert all(a < b for a, b in zip(images, images[1:])), 'Non-monotonic stamps'
        assert len(results) >= 4
        assert all(item['state'] == 'ok' for item in results)
        assert all(item['frame']['width'] == 320 and item['frame']['height'] == 240 for item in results)
        assert statuses[-1]['state'] == 'streaming', statuses[-1]
        print(json.dumps({'images': len(images), 'results': len(results),
                          'observed_fps': round((len(times) - 1) / (times[-1] - times[0]), 2),
                          'camera': statuses[-1], 'recognition_state': results[-1]['state']}, indent=2))
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
