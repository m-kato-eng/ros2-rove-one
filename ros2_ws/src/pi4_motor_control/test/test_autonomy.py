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
        self.assertGreater(speeds[-1], 0)

    def test_emergency_boundary_inclusive(self):
        for y in (0.75, 0.9, 1):
            command = plan(target(y=y))
            self.assertTrue(command['emergency_stop'])
            self.assertEqual(command['speed'], 0)
        self.assertFalse(plan(target(y=0.749))['emergency_stop'])

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

    def test_near_target_latches_motor_and_pc_can_stop(self):
        motor = Controller(Limits())
        motor.enable(True)
        motor.emergency_stop(plan(target(y=0.75))['emergency_stop'])
        self.assertFalse(motor.enable(True))
        motor.emergency_stop(False)
        self.assertFalse(motor.enabled)
        motor.enable(True)
        command = plan(target())
        motor.steer_command(command['speed'], command['turn'])
        motor.enable(False)  # PC stop overrides later autonomous commands
        motor.steer_command(command['speed'], command['turn'])
        self.assertEqual(motor.outputs(), [0, 0, 0, 0])


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
        node.horizon = 0.5
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
        with patch.object(module.time, 'monotonic', return_value=102):
            node.receive(msg)  # Repeated old frame cannot refresh the timeout.
            node.tick()
            self.assertEqual(json.loads(node.publisher.publish.call_args.args[0].data)['speed'], 0)
        node.receive(types.SimpleNamespace(data=json.dumps(dict(data, target_valid=False))))
        self.assertIsNone(node.latest)
        data['source_frame']['stamp']['sec'] = 1
        node.receive(types.SimpleNamespace(data=json.dumps(data)))
        self.assertIsNone(node.latest)
