"""Latest-frame recognition, independent of the camera/preview process."""
import time

from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from .core import jpeg_dimensions, load_detector, result
from .ros_support import image_qos, parameter, publish_json, run, timer


class ObjectRecognition(Node):
    def __init__(self, **kwargs):
        super().__init__('object_recognition', **kwargs)
        self.spec = parameter(self, 'detector', 'none')
        self.rate = parameter(self, 'recognition_fps', 2.0, 0.1, 30.0)
        self.max_age = parameter(self, 'max_frame_age_sec', 1.5, 0.1, 60.0)
        self.threshold = parameter(self, 'confidence_threshold', 0.5, 0.0, 1.0)
        self.limit = parameter(self, 'max_detections', 100, 1, 1000)
        self.detector = None
        self.load_error = ''
        try:
            self.detector = load_detector(self.spec)
        except Exception as exc:
            self.load_error = str(exc)
            self.get_logger().error(f'Detector load failed: {exc}')
        if self.detector is not None and hasattr(self.detector, 'configure'):
            mode = parameter(self, 'bright_mode', getattr(self.detector, 'mode', 'light_spot'))
            if mode not in ('light_spot', 'bright_region', 'red_laser_spot'):
                raise ValueError('invalid bright_mode')
            self.detector.configure(
                mode=mode,
                brightness=parameter(self, 'brightness_min', 190, 0, 255),
                contrast=parameter(self, 'contrast_min', 15, 0, 255),
                min_area=parameter(self, 'min_area_px', 12, 1, 1000000),
                max_area_ratio=parameter(self, 'max_area_ratio', 0.25, 0.001, 1.0),
                confirm_frames=parameter(self, 'confirm_frames', 2, 1, 30),
                max_jump=parameter(self, 'max_jump_normalized', 0.20, 0.001, 1.0),
                ambiguity_margin=parameter(self, 'ambiguity_margin', 0.08, 0.0, 1.0),
                confidence_threshold=self.threshold)
            if mode == 'red_laser_spot':
                self.detector.configure(
                    red_min=parameter(self, 'laser_red_min', 100, 0, 255),
                    red_excess=parameter(self, 'laser_red_excess', 25, 1, 255),
                    red_contrast=parameter(self, 'laser_red_contrast', 20, 1, 255),
                    max_laser_area_ratio=parameter(self, 'laser_max_area_ratio', 0.001, 0.00001, 0.1))
        self.result_pub = self.create_publisher(String, 'vision/detections', 1)
        self.target_pub = self.create_publisher(String, 'vision/ground_target', 1)
        self.debug_pub = self.create_publisher(CompressedImage, 'vision/debug/image/compressed', image_qos())
        self.status_pub = self.create_publisher(String, 'vision/status', 1)
        self.latest = None
        self.seen = None
        self.seen_stamp = None
        self.last_run = 0.0
        self.last_result = result('waiting_for_image', self.spec)
        self.create_subscription(CompressedImage, 'camera/image/compressed', self._receive, image_qos())
        timer(self, 1 / (4 * self.rate), self._tick)
        timer(self, 1.0, self._status)

    def _receive(self, msg):
        self.latest = (msg, time.monotonic())
        self._tick()

    def _tick(self):
        now = time.monotonic()
        if now - self.last_run < 1 / self.rate:
            return
        if self.latest is self.seen and self.latest is not None and self._age(self.latest) <= self.max_age:
            return
        self.last_run = now
        self._recognize()

    def _age(self, entry):
        msg, received = entry
        stamp_ns = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        ros_age = (self.get_clock().now().nanoseconds - stamp_ns) / 1e9
        return max(time.monotonic() - received, ros_age)

    def _emit(self, data):
        self.last_result = data
        publish_json(self.result_pub, data)
        target = {'schema_version': 1, 'state': data['state'], 'reason': data['error'],
                  'target_valid': False, 'target': None, 'candidate_count': 0,
                  'ground_basis': 'lower_half_assumption', 'calibration_id': None}
        if data['state'] == 'ok' and getattr(self.detector, 'last_target', None) is not None:
            target.update(self.detector.last_target)
        elif data['state'] == 'recognition_disabled':
            target['state'] = 'unconfigured'
        elif hasattr(self.detector, 'reset'):
            self.detector.reset()
        target['source_frame'] = None if data['frame'] is None else dict(data['frame'], coordinate_space='raw_image')
        now = self.get_clock().now().to_msg()
        target['result_stamp'] = {'sec': now.sec, 'nanosec': now.nanosec}
        target['processing_ms'] = data['processing_ms']
        self.last_ground_target = target
        publish_json(self.target_pub, target)
        if data['state'] == 'ok' and getattr(self.detector, 'last_debug', None):
            frame = data['frame']
            debug = CompressedImage()
            debug.header.frame_id = frame['frame_id']
            debug.header.stamp.sec = frame['stamp']['sec']
            debug.header.stamp.nanosec = frame['stamp']['nanosec']
            debug.format = 'jpeg'
            debug.data = self.detector.last_debug
            self.debug_pub.publish(debug)

    def _recognize(self):
        entry = self.latest
        if entry is None:
            self._emit(result('waiting_for_image', self.spec))
            return
        if self._age(entry) > self.max_age:
            self._emit(result('stale', self.spec))  # Never retain old coordinates.
            return
        if entry is self.seen:
            return
        self.seen = entry
        msg, _ = entry
        stamp = (msg.header.stamp.sec, msg.header.stamp.nanosec, msg.header.frame_id)
        if stamp == self.seen_stamp:
            return
        self.seen_stamp = stamp
        started = time.monotonic()
        frame = None
        try:
            jpeg = bytes(msg.data)
            width, height = jpeg_dimensions(jpeg)
            frame = {'stamp': {'sec': msg.header.stamp.sec, 'nanosec': msg.header.stamp.nanosec},
                     'frame_id': msg.header.frame_id, 'width': width, 'height': height}
            if self.detector is None:
                raise RuntimeError(self.load_error)
            configured = getattr(self.detector, 'configured', True)
            detections = []
            if configured:
                for index, detection in enumerate(self.detector.detect(jpeg, width, height)):
                    if index >= self.limit:
                        raise ValueError('detector exceeded max_detections')
                    item = detection.as_dict(width, height)
                    if item['confidence'] >= self.threshold:
                        detections.append(item)
            elapsed = (time.monotonic() - started) * 1000
            if self._age(entry) > self.max_age:
                self._emit(result('stale', self.spec, processing_ms=elapsed))
            else:
                state = 'ok' if configured else 'recognition_disabled'
                self._emit(result(state, self.spec, frame, detections, elapsed))
        except Exception as exc:
            self._emit(result('error', self.spec, frame, error=str(exc)))

    def _status(self):
        publish_json(self.status_pub, {
            'schema_version': 1, 'state': self.last_result['state'], 'detector': self.spec,
            'recognition_configured': self.detector is not None and getattr(self.detector, 'configured', True),
            'last_frame_age_sec': None if self.latest is None else self._age(self.latest),
            'processing_ms': self.last_result['processing_ms'], 'error': self.last_result['error'],
        })


def main(args=None):
    run(ObjectRecognition, args)
