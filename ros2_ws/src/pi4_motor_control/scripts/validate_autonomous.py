#!/usr/bin/env python3
"""Real ROS light recognition -> autonomous node -> bridge -> dry-run motors.

Run after colcon build and sourcing install/setup.bash. No physical camera,
GPIO, hardware switch, or external motor topics are used.
"""
from io import BytesIO
from collections import deque
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

from PIL import Image, ImageDraw
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter
from sensor_msgs.msg import CompressedImage

from pi4_camera_vision.recognition_node import ObjectRecognition


def main():
    rclpy.init()
    namespace = '/autonomy_validation_' + str(os.getpid())
    node = rclpy.create_node('validation', namespace=namespace)
    recognition = ObjectRecognition(namespace=namespace, parameter_overrides=[
        Parameter('detector', value='pi4_camera_vision.bright_ground:BrightGroundDetector'),
        Parameter('recognition_fps', value=20.0),
        Parameter('max_frame_age_sec', value=0.3),
        Parameter('bright_mode', value='light_spot'),
    ])
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    executor.add_node(recognition)
    publisher = node.create_publisher(CompressedImage, 'camera/image/compressed', 1)
    events = queue.Queue()
    process = None
    status = None
    heartbeat = True
    frames = True
    point = None
    last_send = 0.0
    sequence = 0
    manual = None
    send_lock = threading.Lock()
    finished = threading.Event()
    heartbeat_thread = None
    history = deque(maxlen=30)
    last_state = None

    def send(message):
        with send_lock:
            process.stdin.write(json.dumps(message) + '\n')
            process.stdin.flush()

    def pc_heartbeat():
        # PC heartbeat is independent of image processing on the Pi.
        while not finished.is_set():
            if heartbeat:
                try:
                    send(manual or {'op': 'drive', 'linear': 0.0, 'angular': 0.0})
                except (BrokenPipeError, ValueError):
                    return
            finished.wait(0.1)

    def receive():
        for line in process.stdout:
            try:
                events.put(json.loads(line))
            except ValueError:
                events.put({'type': 'error', 'message': line})

    def step():
        nonlocal last_send, status, last_state
        if process.poll() is not None:
            raise RuntimeError('Bridge exited: ' + str(process.returncode))
        now = time.monotonic()
        if now - last_send >= 0.05:
            if frames:
                image = Image.new('RGB', (320, 240), (60, 60, 60))
                if point is not None:
                    x, y = point[0]*320, point[1]*240
                    ImageDraw.Draw(image).ellipse((x-6, y-6, x+6, y+6), fill=(225, 225, 225))
                buffer = BytesIO()
                image.save(buffer, format='JPEG', quality=95)
                msg = CompressedImage()
                msg.header.stamp = node.get_clock().now().to_msg()
                msg.header.frame_id = 'synthetic_light'
                msg.format = 'jpeg'
                msg.data = buffer.getvalue()
                publisher.publish(msg)
            last_send = now
        executor.spin_once(timeout_sec=0.01)
        result = []
        while True:
            try:
                event = events.get_nowait()
            except queue.Empty:
                break
            if event.get('type') == 'status':
                status = event['status']
                if status.get('dry_run') is not True:
                    raise RuntimeError('Refusing non-dry-run status')
                state = (status['enabled'], status['emergency_stop'], status['reason'],
                         status['command_source'])
                if state != last_state:
                    history.append(state)
                    last_state = state
            else:
                history.append(event)
            if event.get('type') == 'error':
                raise RuntimeError(event.get('message'))
            result.append(event)
        return result

    def wait_status(predicate, label, timeout=12):
        nonlocal status
        status = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            step()
            if status is not None and predicate(status):
                print('PASS ' + label, flush=True)
                return status
        raise AssertionError(label + ': ' + repr(status) + '\nhistory: ' + repr(list(history)))

    def request(op, value):
        nonlocal sequence
        sequence += 1
        send({'op': op, 'value': value, 'id': sequence})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            for event in step():
                if event.get('type') == 'response' and event.get('id') == sequence:
                    if not event['ok']:
                        raise AssertionError(event)
                    return
        raise AssertionError('No response: ' + op)

    def zero(s):
        return all(v == 0 for v in s['duties'].values())

    def auto(s):
        return s.get('autonomous') or {}

    def moving(s):
        return s['enabled'] and any(v != 0 for v in s['duties'].values())

    try:
        with tempfile.TemporaryFile(mode='w+') as errors:
            process = subprocess.Popen([
                sys.executable, '-u', str(Path(__file__).with_name('pc_bridge.py')),
                '--target-topic', namespace + '/vision/ground_target'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                text=True, bufsize=1)
            threading.Thread(target=receive, daemon=True).start()
            heartbeat_thread = threading.Thread(target=pc_heartbeat, daemon=True)
            heartbeat_thread.start()
            wait_status(lambda s: not s['enabled'] and zero(s), 'startup disarmed', 25)
            request('source', 'auto')
            wait_status(lambda s: s['command_source'] == 'auto' and not s['enabled'],
                        'source switch disarms')
            point = (0.2, 0.55)
            wait_status(lambda s: auto(s).get('turn', 0) > 0, 'light detected on left')
            request('enable', True)
            wait_status(lambda s: moving(s) and s['duties']['left_front'] < s['duties']['right_front'],
                        'left light steers left')
            wait_status(lambda s: moving(s) and abs(s['duties']['left_front']/s['duties']['left_rear']-0.4) < 0.02
                        and abs(s['duties']['right_front']/s['duties']['right_rear']-1.6) < 0.02,
                        'automatic front correction is doubled')
            point = (0.8, 0.55)
            far = wait_status(lambda s: moving(s) and auto(s).get('turn', 0) < 0
                              and s['duties']['left_front'] > s['duties']['right_front'],
                              'right light steers right')
            point = (0.8, 0.70)
            wait_status(lambda s: moving(s) and 0 < auto(s).get('speed', 0) < auto(far)['speed']-0.03,
                        'near light slows vehicle')
            point = None
            wait_status(lambda s: moving(s) and auto(s).get('reason') == 'predicting',
                        'missed target uses bounded prediction')
            wait_status(lambda s: zero(s) and auto(s).get('reason') == 'prediction_expired',
                        'prediction stops after one second')
            point = (0.5, 0.55)
            wait_status(moving, 'new target resumes after Unknown')
            frames = False
            wait_status(lambda s: zero(s) and auto(s).get('speed') == 0,
                        'lost image stream stops')
            frames = True
            wait_status(moving, 'fresh images resume')
            request('enable', False)
            wait_status(lambda s: not s['enabled'] and zero(s), 'PC stop overrides auto')
            request('source', 'manual')
            request('enable', True)
            manual = {'op': 'steer', 'speed': 0.1, 'turn': 0.0}
            wait_status(lambda s: s['command_source'] == 'manual' and moving(s), 'manual source drives')
            manual = None
            request('source', 'auto')
            wait_status(lambda s: not s['enabled'] and zero(s), 'switch back requires reenable')
            request('enable', True)
            wait_status(moving, 'auto reenabled')
            heartbeat = False
            wait_status(lambda s: not s['enabled'] and zero(s), 'PC heartbeat loss disarms auto')
            heartbeat = True
            wait_status(lambda s: auto(s).get('speed', 0) > 0, 'heartbeat restored')
            request('enable', True)
            wait_status(moving, 'explicit reenable after heartbeat loss')
            point = (0.5, 0.80)
            wait_status(lambda s: s['enabled'] and not s['emergency_stop'] and zero(s)
                        and auto(s).get('reason') == 'target_near_stop',
                        'bottom quarter stops without latching')
            point = (0.2, 0.80)
            wait_status(lambda s: s['enabled'] and s['duties']['left_front'] < 0 < s['duties']['right_front']
                        and s['duties']['left_rear'] == s['duties']['right_rear'] == 0,
                        'near left target rotates in place')
            point = None
            wait_status(lambda s: zero(s), 'near target loss stops rotation')
            point = (0.8, 0.80)
            wait_status(lambda s: s['enabled'] and s['duties']['right_front'] < 0 < s['duties']['left_front']
                        and s['duties']['left_rear'] == s['duties']['right_rear'] == 0,
                        'near right target rotates in place')
            point = (0.5, 0.80)
            wait_status(lambda s: zero(s) and auto(s).get('reason') == 'target_near_stop',
                        'centered near target stops rotation')
            point = (0.5, 0.55)
            wait_status(moving, 'target back in range automatically resumes')
            request('estop', True)
            wait_status(lambda s: s['emergency_stop'] and not s['enabled'] and zero(s),
                        'PC emergency stop latches')
            # Fresh target and heartbeat cannot clear the latch themselves.
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                step()
                assert status['emergency_stop'] and not status['enabled'] and zero(status)
            request('enable', True)
            wait_status(lambda s: not s['emergency_stop'] and moving(s),
                        'single enable clears emergency and resumes')
            request('estop', True)
            wait_status(lambda s: s['emergency_stop'] and zero(s), 'repeat emergency stops again')
            request('estop', False)
            wait_status(lambda s: not s['emergency_stop'] and not s['enabled'] and zero(s),
                        'clear-only action remains disarmed')
            print('ALL AUTONOMOUS ROS DRY-RUN CHECKS PASSED', flush=True)
    finally:
        finished.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=2)
        if process is not None and process.poll() is None:
            try:
                send({'op': 'shutdown'})
                process.stdin.close()
                process.wait(timeout=20)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                process.terminate()
                process.wait(timeout=20)
        executor.shutdown()
        recognition.destroy_node()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
