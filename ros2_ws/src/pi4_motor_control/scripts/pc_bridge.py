#!/usr/bin/env python3
"""Private ROS session over SSH; hardware requires explicit --hardware.

Losing stdin or the command heartbeat disarms the node.
"""
import argparse
import json
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

import rclpy
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from std_srvs.srv import SetBool


def emit(message):
    print(json.dumps(message, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hardware', action='store_true')
    args = parser.parse_args()
    dry_run = not args.hardware
    rclpy.init()
    namespace = '/pc_trial_' + str(os.getpid())
    node = rclpy.create_node('pc_bridge', namespace=namespace)
    commands = queue.Queue(maxsize=100)
    eof = threading.Event()
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())

    def reader():
        try:
            for line in sys.stdin:
                if len(line) > 4096:
                    break
                try:
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError('message must be an object')
                    commands.put_nowait((time.monotonic(), message))
                except (ValueError, queue.Full):
                    break
        finally:
            eof.set()

    publisher = node.create_publisher(Twist, namespace + '/cmd_vel', 1)
    wheel_publisher = node.create_publisher(String, namespace + '/wheel_command', 1)
    enable = node.create_client(SetBool, namespace + '/motor_controller/enable')
    estop = node.create_client(SetBool, namespace + '/motor_controller/emergency_stop')
    state = {'value': None}

    def on_status(msg):
        status = json.loads(msg.data)
        if status['dry_run'] is not dry_run:
            stopping.set()
            raise RuntimeError('Bridge mode mismatch')
        state['value'] = status
        emit({'type': 'status', 'status': status})

    subscription = node.create_subscription(
        String, namespace + '/motor_controller/status', on_status, 1)
    process = None
    pending = []
    vector = [0.0, 0.0]
    wheel = None
    last_drive = None
    heartbeat_lost = False
    last_publish = 0.0

    def request_service(client, value, request_id=None):
        future = client.call_async(SetBool.Request(data=value))
        pending.append((future, request_id, time.monotonic()))

    def disable():
        nonlocal wheel
        wheel = None
        vector[:] = [0.0, 0.0]
        publisher.publish(Twist())
        if enable.service_is_ready():
            request_service(enable, False)

    try:
        with (Path.home() / ('motor-pc-bridge-' + str(os.getpid()) + '.log')).open('w') as log:
            hardware_params = []
            if not dry_run:
                import yaml
                config_path = Path(__file__).resolve().parents[1] / 'config/motors-hardware-test.yaml'
                params = yaml.safe_load(config_path.read_text())['motor_controller']['ros__parameters']
                # Explicit overrides apply inside this session's private namespace.
                for name, value in params.items():
                    hardware_params.extend(['-p', name + ':=' + json.dumps(value)])
            process = subprocess.Popen([
                'ros2', 'run', 'pi4_motor_control', 'motor_controller', '--ros-args',
                '-r', '__ns:=' + namespace, *hardware_params,
                '-p', 'dry_run:=' + str(dry_run).lower(),
                '-p', 'hardware_confirmed:=' + str(args.hardware).lower()],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            threading.Thread(target=reader, daemon=True).start()
            deadline = time.monotonic() + 20
            while not (enable.service_is_ready() and estop.service_is_ready() and
                       state['value'] is not None and publisher.get_subscription_count()):
                if eof.is_set() or stopping.is_set() or process.poll() is not None:
                    raise RuntimeError('Bridge/node stopped during startup')
                if time.monotonic() > deadline:
                    raise RuntimeError('ROS node discovery timed out')
                rclpy.spin_once(node, timeout_sec=0.03)
            emit({'type': 'ready', 'dry_run': dry_run, 'namespace': namespace,
                  'heartbeat_timeout': 0.35})
            while not eof.is_set() and not stopping.is_set():
                if process.poll() is not None:
                    raise RuntimeError('Motor node exited unexpectedly')
                for _ in range(100):
                    try:
                        received, message = commands.get_nowait()
                    except queue.Empty:
                        break
                    op = message.get('op')
                    request_id = message.get('id')
                    try:
                        # Never execute commands that sat queued during a stall.
                        if time.monotonic() - received > 0.35:
                            disable()
                            raise ValueError('expired command')
                        if op == 'drive':
                            x, z = message.get('linear', 0.0), message.get('angular', 0.0)
                            if (type(x) not in (int, float) or type(z) not in (int, float)
                                    or not math.isfinite(x) or not math.isfinite(z)):
                                disable()
                                raise ValueError('drive values must be finite numbers')
                            vector[:] = [max(-0.3, min(0.3, x)), max(-1.0, min(1.0, z))]
                            wheel = None
                            last_drive = received
                            heartbeat_lost = False
                        elif op == 'steer':
                            speed, turn = message.get('speed'), message.get('turn')
                            if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 0.3
                                   for v in (speed, turn)):
                                disable()
                                raise ValueError('invalid steering command')
                            wheel = {'mode': 'steer', 'speed': speed, 'turn': turn}
                            vector[:] = [0.0, 0.0]
                            last_drive = received
                            heartbeat_lost = False
                        elif op == 'wheel':
                            motor, speed = message.get('motor'), message.get('speed')
                            if (motor not in ('left_front', 'left_rear', 'right_front', 'right_rear')
                                    or type(speed) not in (int, float) or not math.isfinite(speed)
                                    or abs(speed) > 0.3):
                                disable()
                                raise ValueError('invalid wheel command')
                            wheel = (motor, speed)
                            vector[:] = [0.0, 0.0]
                            last_drive = received
                            heartbeat_lost = False
                        elif op in ('enable', 'estop'):
                            value = message.get('value')
                            if type(value) is not bool:
                                raise ValueError('value must be boolean')
                            if op == 'enable' and value:
                                if last_drive is None or time.monotonic() - last_drive > 0.35:
                                    raise ValueError('fresh zero heartbeat required before enable')
                                if any(vector):
                                    raise ValueError('release direction controls before enable')
                                if wheel is not None:
                                    raise ValueError('release direction controls before enable')
                            if op == 'estop' or not value:
                                wheel = None
                                vector[:] = [0.0, 0.0]
                                publisher.publish(Twist())
                            request_service(enable if op == 'enable' else estop, value, request_id)
                        elif op == 'shutdown':
                            stopping.set()
                            break
                        else:
                            disable()
                            raise ValueError('unknown operation')
                    except (ValueError, TypeError) as exc:
                        emit({'type': 'response', 'id': request_id, 'ok': False, 'message': str(exc)})
                now = time.monotonic()
                fresh = last_drive is not None and now - last_drive <= 0.35
                if not fresh and not heartbeat_lost:
                    disable()
                    wheel = None
                    heartbeat_lost = True
                    emit({'type': 'event', 'message': 'heartbeat_timeout'})
                if now - last_publish >= 0.1:
                    message = Twist()
                    if fresh and wheel is not None:
                        wheel_publisher.publish(String(data=json.dumps(
                            wheel if isinstance(wheel, dict) else {'motor': wheel[0], 'speed': wheel[1]})))
                    elif fresh:
                        message.linear.x, message.angular.z = vector
                    if wheel is None or not fresh:
                        publisher.publish(message)
                    last_publish = now
                for item in list(pending):
                    future, request_id, sent = item
                    if future.done():
                        result = future.result()
                        if request_id is not None:
                            emit({'type': 'response', 'id': request_id, 'ok': result.success,
                                  'message': result.message})
                        pending.remove(item)
                    elif now - sent > 3:
                        disable()
                        pending.remove(item)
                        if request_id is not None:
                            emit({'type': 'response', 'id': request_id, 'ok': False,
                                  'message': 'service_timeout'})
                rclpy.spin_once(node, timeout_sec=0.02)
    except BrokenPipeError:
        pass
    finally:
        try:
            disable()
            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.02)
        except (Exception, BrokenPipeError):
            pass
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
