import unittest

from pi4_motor_control.prediction import TargetPredictor


class PredictionTests(unittest.TestCase):
    def observe(self, predictor, x, y, at, track=1):
        data = predictor.target(x, y)
        data['target']['track_id'] = track
        predictor.observe(data, at)

    def test_velocity_and_no_acceleration(self):
        p = TargetPredictor()
        self.observe(p, 0.4, 0.62, 10)
        self.observe(p, 0.42, 0.61, 10.1)
        p.miss(10.2)
        command = p.command(10.2)
        self.assertEqual(command['reason'], 'predicting')
        self.assertAlmostEqual(command['predicted_target_normalized']['x'], 0.44)
        self.assertAlmostEqual(command['predicted_target_normalized']['y'], 0.60)
        self.assertLessEqual(command['speed'], p.command(10.1)['speed'])

    def test_prediction_expires_from_real_observation_not_misses(self):
        p = TargetPredictor()
        self.observe(p, 0.5, 0.6, 10)
        for at in (10.2, 10.4, 10.6, 10.8, 10.999):
            p.miss(at)
            self.assertGreater(p.command(at)['speed'], 0)
        p.miss(11)
        self.assertEqual(p.command(11)['reason'], 'prediction_expired')
        self.assertEqual(p.command(11)['speed'], 0)

    def test_stream_dropout_is_not_prediction_permission(self):
        p = TargetPredictor()
        self.observe(p, 0.5, 0.6, 10)
        self.assertEqual(p.command(10.301)['speed'], 0)
        p.miss(10.4)
        self.assertGreater(p.command(10.4)['speed'], 0)
        self.assertEqual(p.command(10.701)['speed'], 0)
        p.clear()
        self.assertEqual(p.command(10.8)['speed'], 0)

    def test_near_boundary_and_outside_image_stop(self):
        for x, y, dx, dy in ((0.5, 0.73, 0, 0.01), (0.95, 0.6, 0.02, 0)):
            p = TargetPredictor()
            self.observe(p, x, y, 10)
            self.observe(p, x+dx, y+dy, 10.1)
            p.miss(10.25)
            self.assertEqual(p.command(10.25)['speed'], 0)
        p = TargetPredictor()
        self.observe(p, 0.5, 0.8, 10)
        p.miss(10.1)
        self.assertEqual(p.command(10.1)['speed'], 0)

    def test_new_track_or_gap_does_not_inherit_velocity(self):
        p = TargetPredictor()
        self.observe(p, 0.2, 0.6, 10)
        self.observe(p, 0.8, 0.6, 10.1, track=2)
        p.miss(10.2)
        self.assertEqual(p.command(10.2)['predicted_target_normalized']['x'], 0.8)
        self.observe(p, 0.4, 0.6, 11, track=2)
        p.miss(11.1)
        self.assertEqual(p.command(11.1)['predicted_target_normalized']['x'], 0.4)

    def test_reacquisition_and_disabled_prediction(self):
        p = TargetPredictor(grace=0)
        self.observe(p, 0.5, 0.6, 10)
        p.miss(10.1)
        self.assertEqual(p.command(10.1)['speed'], 0)
        self.observe(p, 0.6, 0.6, 10.2)
        self.assertEqual(p.command(10.2)['reason'], 'tracking')


    def test_missing_near_target_stops_stationary_rotation(self):
        p = TargetPredictor()
        self.observe(p, 0.2, 0.8, 10)
        self.assertNotEqual(p.command(10)['turn'], 0)
        p.miss(10.1)
        self.assertEqual(p.command(10.1)['turn'], 0)
        self.assertEqual(p.command(10.1)['speed'], 0)
