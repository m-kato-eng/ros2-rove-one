#!/usr/bin/env python3
"""Private dry-run ROS session over SSH JSON-lines stdin/stdout.

This bridge ALWAYS starts a GPIO-free node in its own namespace. It does not
provide a hardware switch. Losing stdin or the command heartbeat disarms it.
"""
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
    enable = node.create_client(SetBool, namespace + '/motor_controller/enable')
    estop = node.create_client(SetBool, namespace + '/motor_controller/emergency_stop')
    state = {'value': None}

    def on_status(msg):
        status = json.loads(msg.data)
        if not status['dry_run']:
            stopping.set()
            raise RuntimeError('Bridge refuses hardware mode')
        state['value'] = status
        emit({'type': 'status', 'status': status})

    subscription = node.create_subscription(
        String, namespace + '/motor_controller/status', on_status, 1)
    process = None
    pending = []
    vector = [0.0, 0.0]
    last_drive = None
    heartbeat_lost = False
    last_publish = 0.0

    def request_service(client, value, request_id=None):
        future = client.call_async(SetBool.Request(data=value))
        pending.append((future, request_id, time.monotonic()))

    def disable():
        vector[:] = [0.0, 0.0]
        publisher.publish(Twist())
        if enable.service_is_ready():
            request_service(enable, False)

    try:
        with (Path.home() / ('motor-pc-bridge-' + str(os.getpid()) + '.log')).open('w') as log:
            process = subprocess.Popen([
                'ros2', 'run', 'pi4_motor_control', 'motor_controller', '--ros-args',
                '-r', '__ns:=' + namespace, '-p', 'dry_run:=true',
                '-p', 'hardware_confirmed:=false'],
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
            emit({'type': 'ready', 'dry_run': True, 'namespace': namespace,
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
                            if op == 'estop' or not value:
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
                    heartbeat_lost = True
                    emit({'type': 'event', 'message': 'heartbeat_timeout'})
                if now - last_publish >= 0.1:
                    message = Twist()
                    if fresh:
                        message.linear.x, message.angular.z = vector
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
