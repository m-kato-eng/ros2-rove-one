import math
import unittest
from pi4_motor_control.autonomy import plan
from pi4_motor_control.control import Controller, Limits


def target(x=0.5, y=0.5):
    return dict(state='tracking', target_valid=True,
                target={'target_normalized': {'x': x, 'y': y}})


class AutonomyTests(unittest.TestCase):
    def test_speed_decreases_toward_stop_boundary(self):
        speeds = [plan(target(y=y))['speed'] for y in (0.5, 0.6, 0.7, 0.749)]
        self.assertEqual(speeds, sorted(speeds, reverse=True))
        self.assertAlmostEqual(speeds[0], 0.2)
        self.assertGreaterEqual(speeds[-1], 0.10)
        self.assertAlmostEqual(plan(target(y=0.625))['speed'], 0.15)

    def test_normal_stop_boundary_inclusive(self):
        for y in (0.75, 0.9, 1):
            command = plan(target(y=y))
            self.assertFalse(command['emergency_stop'])
            self.assertEqual(command['reason'], 'target_near_stop')
            self.assertEqual(command['turn'], 0)
            self.assertEqual(command['speed'], 0)
        self.assertFalse(plan(target(y=0.749))['emergency_stop'])

    def test_near_target_rotates_toward_valid_left_and_right(self):
        motor = Controller(Limits(max_duty=0.8))
        motor.enable(True)
        for x in (0.2, 0.8):
            command = plan(target(x=x, y=0.8))
            self.assertEqual(command['speed'], 0)
            self.assertNotEqual(command['turn'], 0)
            motor.steer_command(command['speed'], command['turn'], steering_gain=2)
            lf, lr, rf, rr = motor.outputs()
            self.assertEqual((lr, rr), (0, 0))
            self.assertEqual(lf > 0, x > 0.5)
            self.assertEqual(rf > 0, x < 0.5)
        for data in (target(y=0.8), None):
            command = plan(data)
            motor.steer_command(command['speed'], command['turn'], steering_gain=2)
            self.assertEqual(motor.outputs(), [0, 0, 0, 0])

    def test_unknown_and_malformed_stop(self):
        self.assertEqual(plan(None)['reason'], 'unknown')
        for data in (None, {}, [], target(y=math.nan), target(x=True), target(x=2),
                     dict(target(), state='Unknown'), dict(target(), target_valid=False)):
            self.assertEqual(plan(data)['speed'], 0)
        self.assertEqual(plan(target(y=0.49))['speed'], 0)

    def test_steering_sign_and_center(self):
        self.assertGreater(plan(target(x=0.2))['turn'], 0)
        self.assertLess(plan(target(x=0.8))['turn'], 0)
        self.assertEqual(plan(target())['turn'], 0)
        motor = Controller(Limits())
        motor.enable(True)
        command = plan(target(x=0.8))
        motor.steer_command(command['speed'], command['turn'])
        lf, lr, rf, rr = motor.outputs()
        self.assertGreater(lf, rf)  # right target -> turn right

    def test_near_target_stops_and_resumes_without_enable(self):
        motor = Controller(Limits())
        motor.enable(True)
        for y in (0.6, 0.75, 0.9, 0.6):
            command = plan(target(y=y))
            motor.steer_command(command['speed'], command['turn'])
            self.assertTrue(motor.enabled)
            self.assertFalse(motor.estop)
            self.assertEqual(any(motor.outputs()), y < 0.75)
        motor.enable(False)
        command = plan(target())
        motor.steer_command(command['speed'], command['turn'])
        self.assertEqual(motor.outputs(), [0, 0, 0, 0])

    def test_estop_requires_explicit_enable_and_discards_old_motion(self):
        motor = Controller(Limits())
        motor.enable(True)
        motor.steer_command(0.2, 0.1)
        motor.emergency_stop(True)
        motor.steer_command(0.2, 0.1)
        motor.enable(False)
        self.assertTrue(motor.estop)
        self.assertEqual(motor.outputs(), [0, 0, 0, 0])
        self.assertTrue(motor.enable(True))
        self.assertFalse(motor.estop)
        self.assertEqual(motor.outputs(), [0, 0, 0, 0])
        motor.steer_command(0.2, 0.1)
        self.assertTrue(any(motor.outputs()))


class TargetFreshnessTests(unittest.TestCase):
    def test_frame_expiry_unknown_and_duplicate(self):
        import importlib.util
        import json
        import sys
        import types
        from pathlib import Path
        from unittest.mock import MagicMock, patch
        stubs = {name: types.ModuleType(name) for name in
                 ('rclpy', 'rclpy.node', 'rclpy.clock', 'std_msgs', 'std_msgs.msg')}
        stubs['rclpy.node'].Node = object
        stubs['rclpy.clock'].Clock = object
        stubs['rclpy.clock'].ClockType = MagicMock()
        stubs['std_msgs.msg'].String = lambda **kwargs: types.SimpleNamespace(**kwargs)
        path = Path(__file__).parents[1] / 'pi4_motor_control/autonomous_node.py'
        spec = importlib.util.spec_from_file_location('pi4_motor_control._autonomy_test', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, stubs):
            spec.loader.exec_module(module)
        node = module.AutonomousDriving.__new__(module.AutonomousDriving)
        from pi4_motor_control.prediction import TargetPredictor
        node.predictor = TargetPredictor()
        node.horizon = 0.5
        node.target_timeout = 0.3
        node.latest = None
        node.received = 0.0
        node.frame_stamp = None
        node.publisher = MagicMock()
        node.get_clock = lambda: types.SimpleNamespace(now=lambda: types.SimpleNamespace(nanoseconds=10_000_000_000))
        data = dict(target(), source_frame={'stamp': {'sec': 10, 'nanosec': 0}})
        msg = types.SimpleNamespace(data=json.dumps(data))
        with patch.object(module.time, 'monotonic', return_value=100):
            node.receive(msg)
            node.tick()
            self.assertGreater(json.loads(node.publisher.publish.call_args.args[0].data)['speed'], 0)
        with patch.object(module.time, 'monotonic', return_value=100.299):
            node.tick()
            self.assertGreater(json.loads(node.publisher.publish.call_args.args[0].data)['speed'], 0)
        with patch.object(module.time, 'monotonic', return_value=100.301):
            node.receive(msg)  # Repeated old frame cannot refresh the timeout.
            node.tick()
            self.assertEqual(json.loads(node.publisher.publish.call_args.args[0].data)['speed'], 0)
        node.receive(types.SimpleNamespace(data=json.dumps(dict(data, target_valid=False))))
        self.assertIsNone(node.latest)
        data['source_frame']['stamp']['sec'] = 1
        node.receive(types.SimpleNamespace(data=json.dumps(data)))
        self.assertIsNone(node.latest)
