"""Real rclpy/message tests. No physical camera or chosen recognition target."""
import json
import sys
import time
import types
from urllib.error import HTTPError
from urllib.request import urlopen
from http.server import ThreadingHTTPServer
import threading

import pytest

rclpy = pytest.importorskip('rclpy')
from rclpy.parameter import Parameter
from sensor_msgs.msg import CompressedImage

from pi4_camera_vision.core import Detection, result
from pi4_camera_vision.capture_node import CameraCapture
from pi4_camera_vision.http_node import PreviewState, make_handler
from pi4_camera_vision.recognition_node import ObjectRecognition
from test_core import jpeg


@pytest.fixture
def ros():
    rclpy.init()
    yield
    rclpy.shutdown()


def message(node, age=0):
    msg = CompressedImage()
    msg.header.stamp = (node.get_clock().now() - rclpy.duration.Duration(seconds=age)).to_msg()
    msg.header.frame_id = 'camera_optical_frame'
    msg.format = 'jpeg'
    msg.data = jpeg()
    return msg


def test_disabled_is_not_successful_recognition_and_stale_clears_frame(ros):
    node = ObjectRecognition()
    try:
        node._recognize()
        assert node.last_result['state'] == 'waiting_for_image'
        node._receive(message(node))
        node._recognize()
        assert node.last_result['state'] == 'recognition_disabled'
        assert node.last_result['detections'] == []
        assert node.last_result['frame']['width'] == 320
        node._receive(message(node, age=5))
        node._recognize()
        assert node.last_result['state'] == 'stale'
        assert node.last_result['frame'] is None
    finally:
        node.destroy_node()


@pytest.mark.parametrize('mode', ['valid', 'error', 'slow', 'invalid_box', 'too_many'])
def test_plugin_result_failure_and_late_result_rejection(ros, monkeypatch, mode):
    class FixtureDetector:
        def detect(self, data, width, height):
            if mode == 'error':
                raise RuntimeError('fixture failure')
            if mode == 'slow':
                time.sleep(0.15)
            if mode == 'invalid_box':
                return [Detection('fixture', 0.9, -1, 0, 10, 10)]
            if mode == 'too_many':
                return [Detection('fixture', 0.9, 0, 0, 10, 10)] * 3
            return [Detection('fixture', 0.9, 10, 20, 100, 40),
                    Detection('below_threshold', 0.1, 0, 0, 10, 10)]

    module = types.ModuleType('contract_fixture')
    module.Detector = FixtureDetector
    monkeypatch.setitem(sys.modules, 'contract_fixture', module)
    node = ObjectRecognition(parameter_overrides=[
        Parameter('detector', value='contract_fixture:Detector'),
        Parameter('max_frame_age_sec', value=0.1),
        Parameter('max_detections', value=2),
    ])
    try:
        node._receive(message(node))
        node._recognize()
        data = node.last_result
        if mode == 'valid':
            assert data['state'] == 'ok'
            assert len(data['detections']) == 1
            assert data['detections'][0]['center_px'] == {'x': 60, 'y': 40}
        elif mode == 'slow':
            assert data['state'] == 'stale'
            assert data['detections'] == []
        else:
            assert data['state'] == 'error'
            assert data['detections'] == []
            assert data['error']
    finally:
        node.destroy_node()


def test_plugin_load_error_is_reported(ros):
    node = ObjectRecognition(parameter_overrides=[Parameter('detector', value='missing_xyz:Detector')])
    try:
        node._receive(message(node))
        node._recognize()
        assert node.last_result['state'] == 'error'
        assert node.last_result['error']
    finally:
        node.destroy_node()


def test_camera_watchdog_retries_and_stops_child_process(ros):
    class SilentCamera(CameraCapture):
        def _command(self):
            return [sys.executable, '-c', 'import time; time.sleep(30)']

    node = SilentCamera(parameter_overrides=[
        Parameter('frame_timeout_sec', value=0.5),
        Parameter('reconnect_sec', value=0.1),
    ])
    try:
        deadline = time.monotonic() + 4
        while node.restarts < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert node.restarts >= 2
        assert node.latest is None
        assert node.counter == 0
        assert 'timeout' in node.error
        process = node.process
    finally:
        node.destroy_node()
    assert not node.worker.is_alive()
    assert process is None or process.poll() is not None


def test_bright_target_requires_unique_frames_and_expiration_clears_it(ros):
    from test_bright_ground import frame
    node = ObjectRecognition(parameter_overrides=[
        Parameter('detector', value='pi4_camera_vision.bright_ground:BrightGroundDetector')])
    try:
        msg = message(node)
        msg.data = frame([(230, 190, 225)])
        node._receive(msg)
        node._recognize()
        assert not node.last_ground_target['target_valid']
        node._receive(msg)  # Repeated delivery of the same exposure must not confirm a target.
        node._recognize()
        assert not node.last_ground_target['target_valid']
        msg2 = message(node)
        msg2.data = msg.data
        node._receive(msg2)
        node._recognize()
        assert node.last_ground_target['target_valid']
        assert node.last_ground_target['target']['target_normalized']['x'] > 0.5
        node._receive(message(node, age=5))
        node._recognize()
        assert node.last_ground_target['state'] == 'stale'
        assert node.last_ground_target['target'] is None
    finally:
        node.destroy_node()


def test_http_snapshot_stream_and_expired_coordinates():
    state = PreviewState(max_age=1.0)
    state.jpeg, state.image_at, state.sequence = jpeg(), time.monotonic(), 1
    state.result_at = time.monotonic()
    state.detections = result('ok', 'fixture', detections=[{'label': 'fixture'}])
    state.target = {'schema_version': 1, 'state': 'tracking', 'target_valid': True, 'target': {'x': 1}}
    state.target_at = time.monotonic()
    state.debug = PreviewState(max_age=1.0)
    state.debug.jpeg, state.debug.image_at, state.debug.sequence = jpeg(), time.monotonic(), 1
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(state))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base + '/frame.jpg', timeout=2) as response:
            assert response.read() == jpeg()
        with urlopen(base + '/debug/frame.jpg', timeout=2) as response:
            assert response.read() == jpeg()
        with urlopen(base + '/target', timeout=2) as response:
            assert json.load(response)['target_valid']
        state.target_at -= 5
        with urlopen(base + '/target', timeout=2) as response:
            assert not json.load(response)['target_valid']
        with urlopen(base + '/stream', timeout=2) as response:
            assert response.readline() == b'--frame\r\n'
            assert response.readline() == b'Content-Type: image/jpeg\r\n'
            assert response.readline().startswith(b'Content-Length:')
            assert response.readline() == b'\r\n'
            assert response.read(len(jpeg())) == jpeg()
        state.image_at -= 5
        with urlopen(base + '/results', timeout=2) as response:
            data = json.load(response)
        assert data['state'] == 'stale'
        assert data['detections'] == []
        with pytest.raises(HTTPError) as exc:
            urlopen(base + '/frame.jpg', timeout=2)
        assert exc.value.code == 503
    finally:
        state.stop.set()
        with state.condition:
            state.condition.notify_all()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
