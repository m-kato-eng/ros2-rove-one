#!/usr/bin/env python3
"""Exercise the installed launch/ROS graph in dry-run mode; never use GPIO.

Run in a dedicated ROS_DOMAIN_ID, after sourcing the built workspace.
"""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time

import rclpy
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from std_srvs.srv import SetBool


def main():
    if os.environ.get('ROS_DOMAIN_ID') != '87':
        raise RuntimeError('Run with ROS_DOMAIN_ID=87 to isolate this test')
    log = Path.home() / 'motor-node-smoke.log'
    rclpy.init()
    node = rclpy.create_node('motor_smoke_test')
    statuses = []
    publisher = node.create_publisher(Twist, '/cmd_vel', 1)
    subscription = node.create_subscription(
        String, '/motor_controller/status',
        lambda msg: statuses.append(json.loads(msg.data)), 10)
    enable = node.create_client(SetBool, '/motor_controller/enable')
    estop = node.create_client(SetBool, '/motor_controller/emergency_stop')

    def wait_for(predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.03)
            if predicate():
                return
        raise AssertionError('Condition timed out; see ' + str(log))

    def service(client, value):
        assert client.wait_for_service(timeout_sec=10)
        future = client.call_async(SetBool.Request(data=value))
        wait_for(future.done)
        return future.result()

    def command(x=0.0, z=0.0, y=0.0):
        message = Twist()
        message.linear.x, message.angular.z, message.linear.y = x, z, y
        publisher.publish(message)

    def state(predicate, timeout=4):
        wait_for(lambda: statuses and predicate(statuses[-1]), timeout)
        assert statuses[-1]['dry_run'], 'Smoke test must never enable GPIO'
        return statuses[-1]

    def zero(status):
        return all(value == 0 for value in status['duties'].values())

    def clear():
        statuses.clear()

    process = None
    try:
        with log.open('w') as output:
            process = subprocess.Popen(
                ['ros2', 'launch', 'pi4_motor_control', 'motors.launch.py'],
                stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            state(lambda s: not s['enabled'] and zero(s), timeout=15)
            wait_for(lambda: publisher.get_subscription_count() == 1)
            print('PASS startup: disarmed, four zero outputs', flush=True)

            command(0.2)
            clear()
            state(lambda s: not s['enabled'] and zero(s))
            print('PASS commands ignored before enabling', flush=True)

            assert service(enable, True).success
            command(0.2)
            clear()
            state(lambda s: s['enabled'] and all(v > 0 for v in s['duties'].values()))
            print('PASS forward command reaches all four virtual motors', flush=True)
            command(-0.2)
            clear()
            state(lambda s: s['enabled'] and all(v < 0 for v in s['duties'].values()))
            print('PASS reverse command', flush=True)
            command(0.0, 1.0)
            clear()
            state(lambda s: s['duties']['left_front'] < 0 < s['duties']['right_front'])
            print('PASS differential turn', flush=True)
            command(999.0, 999.0)
            clear()
            state(lambda s: 0 < s['duties']['left_front'] < s['duties']['right_front']
                  and max(abs(v) for v in s['duties'].values()) <= 0.35)
            print('PASS saturation with duty limit', flush=True)

            assert service(estop, True).success
            clear()
            state(lambda s: s['emergency_stop'] and not s['enabled'] and zero(s))
            assert not service(enable, True).success
            assert service(estop, False).success
            command(0.2)
            clear()
            state(lambda s: not s['emergency_stop'] and not s['enabled'] and zero(s))
            print('PASS latched stop, rejected arm, clear remains disarmed', flush=True)

            assert service(enable, True).success
            command(0.2)
            clear()
            state(lambda s: s['enabled'] and not zero(s))
            clear()
            state(lambda s: s['reason'] == 'command_timeout' and not s['enabled'] and zero(s))
            command(0.2)
            clear()
            state(lambda s: not s['enabled'] and zero(s))
            print('PASS command loss stops and cannot auto-resume', flush=True)

            for x, y, label in [(math.nan, 0.0, 'NaN'), (0.1, 0.1, 'unsupported axis')]:
                assert service(enable, True).success
                command(x, y=y)
                clear()
                state(lambda s: s['reason'] == 'invalid_command' and not s['enabled'] and zero(s))
                print('PASS invalid command: ' + label, flush=True)

            # Enable simulated ROS time without a /clock publisher.
            paused = subprocess.run(
                ['ros2', 'param', 'set', '/motor_controller', 'use_sim_time', 'true'],
                capture_output=True, text=True, timeout=15)
            assert paused.returncode == 0, paused.stdout + paused.stderr
            assert service(enable, True).success
            command(0.2)
            clear()
            state(lambda s: s['enabled'] and not zero(s))
            clear()
            state(lambda s: s['reason'] == 'command_timeout' and zero(s))
            print('PASS watchdog while ROS time is paused', flush=True)

            assert service(enable, True).success
            command(0.2)
            clear()
            state(lambda s: s['enabled'] and not zero(s))
            assert service(enable, False).success
            clear()
            state(lambda s: not s['enabled'] and zero(s))
            print('PASS explicit disable', flush=True)

            # Signal launch only; launch forwards to the child itself.
            process.send_signal(signal.SIGINT)
            assert process.wait(timeout=15) == 0
            output.flush()
            contents = log.read_text()
            assert 'Traceback' not in contents, contents
            assert 'process has died' not in contents, contents
            print('PASS launch shutdown; no node left running', flush=True)
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
