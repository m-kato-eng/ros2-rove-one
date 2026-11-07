"""Optional localhost HTTP adapter for existing SSH tunnels and future PC GUI."""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from .core import result
from .ros_support import image_qos, parameter, run


PAGE = b'''<!doctype html><meta charset="utf-8"><title>Pi Camera</title>
<body style="background:#181818;color:#eee;font-family:sans-serif;text-align:center">
<h2>Pi Camera - SSH</h2><img id="camera" src="/stream" width="640" style="max-width:100%">
<p id="status">Connecting...</p><script>
let wasFresh=true; const camera=document.getElementById('camera');
setInterval(async()=>{try{let s=await(await fetch('/health',{cache:'no-store'})).json();
document.getElementById('status').textContent=s.image_fresh?'Live / recognition: '+s.recognition_state:'Camera unavailable / stale';
camera.style.opacity=s.image_fresh?'1':'0.15';
if(s.image_fresh&&!wasFresh)camera.src='/stream?t='+Date.now(); wasFresh=s.image_fresh;
}catch(e){document.getElementById('status').textContent='Disconnected';camera.style.opacity='0.15';wasFresh=false;}},1000);
</script></body>'''


class PreviewState:
    def __init__(self, max_age):
        self.condition = threading.Condition()
        self.stop = threading.Event()
        self.max_age = max_age
        self.sequence = 0
        self.jpeg = b''
        self.image_at = None
        self.result_at = None
        self.detections = result('waiting_for_image', 'unknown')
        self.clients = threading.BoundedSemaphore(4)
        self.debug = None
        self.target = {'schema_version': 1, 'state': 'unconfigured', 'target_valid': False, 'target': None}
        self.target_at = None
        self.target_max_age = 0.3

    def fresh(self):
        return self.image_at is not None and time.monotonic() - self.image_at <= self.max_age

    def current_result(self):
        if not self.fresh() or self.result_at is None or time.monotonic() - self.result_at > self.max_age:
            return result('stale', self.detections.get('detector', 'unknown'))
        return self.detections

    def current_target(self):
        if self.target_at is None or time.monotonic() - self.target_at > self.target_max_age:
            return {'schema_version': 1, 'state': 'stale', 'target_valid': False, 'target': None}
        return self.target


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def _reply(self, code, content_type, body):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            active = state
            if path.startswith('/debug/'):
                active = state.debug
                path = path[6:]
                if active is None:
                    self.send_error(503, 'Debug image not available')
                    return
            try:
                if path == '/':
                    self._reply(200, 'text/html; charset=utf-8', PAGE)
                elif path in ('/health', '/results', '/frame.jpg', '/target'):
                    with active.condition:
                        fresh = active.fresh()
                        if path == '/frame.jpg':
                            body = active.jpeg if fresh else b'Camera image is stale'
                        else:
                            data = active.current_target() if path == '/target' else active.current_result()
                            if path == '/health':
                                data = {'schema_version': 1, 'frames': state.sequence,
                                        'image_fresh': fresh,
                                        'last_frame_age_sec': None if state.image_at is None else time.monotonic() - state.image_at,
                                        'recognition_state': data['state']}
                            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
                    if path == '/frame.jpg':
                        self._reply(200 if fresh else 503, 'image/jpeg' if fresh else 'text/plain', body)
                    else:
                        self._reply(200, 'application/json; charset=utf-8', body)
                elif path == '/stream':
                    self._stream(active)
                else:
                    self.send_error(404)
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                pass

        def _stream(self, state=state):
            if not state.clients.acquire(blocking=False):
                self.send_error(503, 'Maximum of four preview streams')
                return
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                seen = -1
                while not state.stop.is_set():
                    with state.condition:
                        ready = state.condition.wait_for(
                            lambda: state.stop.is_set() or (state.sequence != seen and state.fresh()),
                            timeout=state.max_age)
                        if not ready or state.stop.is_set():
                            return
                        jpeg, seen = state.jpeg, state.sequence
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '
                                     + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')
                    self.wfile.flush()
            finally:
                state.clients.release()

    return Handler


class CameraHttpBridge(Node):
    def __init__(self):
        super().__init__('camera_http_bridge')
        port = parameter(self, 'port', 8765, 1024, 65535)
        age = parameter(self, 'max_frame_age_sec', 2.0, 0.1, 60.0)
        self.state = PreviewState(age)
        self.state.target_max_age = parameter(self, 'target_max_age_sec', 0.3, 0.1, 60.0)
        self.state.debug = PreviewState(age)
        self.create_subscription(CompressedImage, 'camera/image/compressed', self._image, image_qos())
        self.create_subscription(String, 'vision/detections', self._result, 1)
        self.create_subscription(String, 'vision/ground_target', self._target, 1)
        self.create_subscription(CompressedImage, 'vision/debug/image/compressed', self._debug, image_qos())
        self.server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(self.state))
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.get_logger().info(f'SSH preview: http://127.0.0.1:{port}/')

    def _image(self, msg):
        self._save_image(self.state, msg)

    def _debug(self, msg):
        self._save_image(self.state.debug, msg)

    def _save_image(self, state, msg):
        stamp_ns = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        age = max(0.0, (self.get_clock().now().nanoseconds - stamp_ns) / 1e9)
        if age > state.max_age:
            return
        with state.condition:
            state.jpeg = bytes(msg.data)
            state.image_at = time.monotonic() - age
            state.sequence += 1
            state.condition.notify_all()

    def _target(self, msg):
        try:
            data = json.loads(msg.data)
            if not isinstance(data, dict) or data.get('schema_version') != 1:
                return
            frame = data.get('source_frame')
            age = 0.0
            if frame:
                stamp = frame['stamp']
                age = max(0.0, (self.get_clock().now().nanoseconds - stamp['sec'] * 1e9 - stamp['nanosec']) / 1e9)
            with self.state.condition:
                self.state.target = data
                self.state.target_at = time.monotonic() - age
        except (ValueError, TypeError, KeyError):
            return

    def _result(self, msg):
        try:
            data = json.loads(msg.data)
            if not isinstance(data, dict) or data.get('schema_version') != 1:
                return
        except (ValueError, TypeError):
            return
        with self.state.condition:
            self.state.detections = data
            self.state.result_at = time.monotonic()

    def destroy_node(self):
        self.state.stop.set()
        self.state.debug.stop.set()
        with self.state.debug.condition:
            self.state.debug.condition.notify_all()
        with self.state.condition:
            self.state.condition.notify_all()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        return super().destroy_node()


def main(args=None):
    run(CameraHttpBridge, args)
