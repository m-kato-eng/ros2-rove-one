"""One camera owner. Forward native MJPEG without pixel decoding/re-encoding."""
import os
import selectors
import subprocess
import threading
import time

from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from .core import JpegFramer, jpeg_dimensions
from .ros_support import image_qos, parameter, publish_json, run, timer


class CameraCapture(Node):
    def __init__(self, **kwargs):
        super().__init__('camera_capture', **kwargs)
        self.device = parameter(self, 'device', '/dev/v4l/by-id/usb-046d_081b_F6390640-video-index0')
        self.width = parameter(self, 'width', 320, 16, 4096)
        self.height = parameter(self, 'height', 240, 16, 4096)
        self.fps = parameter(self, 'fps', 10, 1, 60)
        self.frame_id = parameter(self, 'frame_id', 'camera_optical_frame')
        self.timeout = parameter(self, 'frame_timeout_sec', 3.0, 0.5, 60.0)
        self.retry = parameter(self, 'reconnect_sec', 2.0, 0.1, 60.0)
        self.local_preview = parameter(self, 'local_preview', False)
        self.image_pub = self.create_publisher(CompressedImage, 'camera/image/compressed', image_qos())
        self.status_pub = self.create_publisher(String, 'camera/status', 1)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        self.counter = 0
        self.sent = 0
        self.state = 'starting'
        self.error = ''
        self.restarts = 0
        self.last_received = None
        self.process = None
        self.worker = threading.Thread(target=self._capture, daemon=True)
        timer(self, 1.0, self._publish_status)
        self.worker.start()

    def _command(self):
        cmd = ['gst-launch-1.0', '-q', 'v4l2src', f'device={self.device}', '!',
               f'image/jpeg,width={self.width},height={self.height},framerate={self.fps}/1', '!']
        if self.local_preview:
            cmd += ['tee', 'name=t', 't.', '!', 'queue', 'leaky=downstream',
                    'max-size-buffers=2', '!', 'jpegdec', '!', 'videoconvert', '!',
                    'autovideosink', 'sync=false', 't.', '!', 'queue',
                    'leaky=downstream', 'max-size-buffers=2', '!']
        return cmd + ['fdsink', 'fd=1', 'sync=false']

    @staticmethod
    def _terminate(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if process.stdout:
            process.stdout.close()

    def _capture(self):
        while not self.stop.is_set():
            process = None
            try:
                with self.lock:
                    self.state, self.error, self.latest = 'connecting', '', None
                process = subprocess.Popen(self._command(), stdout=subprocess.PIPE, bufsize=0)
                self.process = process
                framer = JpegFramer()
                last_frame = time.monotonic()
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while not self.stop.is_set():
                        if time.monotonic() - last_frame > self.timeout:
                            raise TimeoutError('no camera frames before timeout')
                        if not selector.select(timeout=0.2):
                            continue
                        chunk = os.read(process.stdout.fileno(), 65536)
                        if not chunk:
                            raise RuntimeError(f'camera stream ended (exit={process.poll()})')
                        for jpeg in framer.feed(chunk):
                            if jpeg_dimensions(jpeg) != (self.width, self.height):
                                raise ValueError('camera returned unexpected dimensions')
                            last_frame = time.monotonic()
                            stamp = self.get_clock().now().to_msg()
                            with self.lock:
                                self.counter += 1
                                self.latest = (self.counter, jpeg, stamp, last_frame)
                                self.last_received = last_frame
                                self.state, self.error = 'streaming', ''
                            # Publish at frame arrival; a second fps timer adds needless latency.
                            self._publish_image()
            except Exception as exc:
                with self.lock:
                    self.state, self.error, self.latest = 'reconnecting', str(exc), None
                    self.restarts += 1
                if not self.stop.is_set():
                    self.get_logger().warning(f'Camera: {exc}; retrying in {self.retry}s')
            finally:
                if process is not None:
                    self._terminate(process)
                self.process = None
            self.stop.wait(self.retry)

    def _publish_image(self):
        with self.lock:
            frame = self.latest
        if frame is None or frame[0] == self.sent or time.monotonic() - frame[3] > self.timeout:
            return
        msg = CompressedImage()
        msg.header.stamp = frame[2]
        msg.header.frame_id = self.frame_id
        msg.format = 'jpeg'
        msg.data = frame[1]
        self.image_pub.publish(msg)
        self.sent = frame[0]

    def _publish_status(self):
        with self.lock:
            age = None if self.last_received is None else time.monotonic() - self.last_received
            data = {'schema_version': 1, 'state': self.state, 'error': self.error,
                    'device': self.device, 'width': self.width, 'height': self.height,
                    'requested_fps': self.fps, 'frames_received': self.counter,
                    'last_frame_age_sec': age, 'restarts': self.restarts}
        publish_json(self.status_pub, data)

    def destroy_node(self):
        self.stop.set()
        self.worker.join(timeout=5)
        if self.worker.is_alive():
            self.get_logger().error('Capture worker did not stop within 5 seconds')
        return super().destroy_node()


def main(args=None):
    run(CameraCapture, args)
