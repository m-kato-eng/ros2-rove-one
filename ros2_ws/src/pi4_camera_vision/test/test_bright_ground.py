from io import BytesIO
import unittest

from PIL import Image, ImageDraw

from pi4_camera_vision.bright_ground import BrightGroundDetector


def frame(points=()):
    image = Image.new('RGB', (320, 240), (60, 60, 60))
    draw = ImageDraw.Draw(image)
    for x, y, value in points:
        draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=(value,) * 3)
    stream = BytesIO()
    image.save(stream, format='JPEG', quality=95)
    return stream.getvalue()


class BrightGroundTests(unittest.TestCase):
    def setUp(self):
        self.detector = BrightGroundDetector()

    def test_top_half_is_excluded_and_lower_target_is_confirmed(self):
        data = frame([(60, 50, 250), (230, 190, 225)])
        self.detector.detect(data, 320, 240)
        self.assertFalse(self.detector.last_target['target_valid'])
        self.detector.detect(data, 320, 240)
        target = self.detector.last_target
        self.assertTrue(target['target_valid'])
        self.assertEqual(target['candidate_count'], 1)
        self.assertAlmostEqual(target['target']['target_px']['x'], 230, delta=3)
        self.assertAlmostEqual(target['target']['target_px']['y'], 190, delta=3)
        self.assertGreater(target['target']['target_normalized']['x'], 0.5)
        self.assertIsNone(target['target']['ground'])

    def test_only_upper_light_does_not_create_target(self):
        for _ in range(3):
            self.detector.detect(frame([(80, 50, 230)]), 320, 240)
        self.assertEqual(self.detector.last_target['candidate_count'], 0)
        self.assertFalse(self.detector.last_target['target_valid'])

    def test_equal_candidates_are_ambiguous(self):
        self.detector.detect(frame([(70, 180, 225), (250, 180, 225)]), 320, 240)
        self.assertEqual(self.detector.last_target['state'], 'ambiguous')
        self.assertIsNone(self.detector.last_target['target'])

    def test_lost_and_jump_require_reconfirmation(self):
        left = frame([(60, 180, 225)])
        self.detector.detect(left, 320, 240)
        self.detector.detect(left, 320, 240)
        self.assertTrue(self.detector.last_target['target_valid'])
        self.detector.detect(frame([(260, 180, 225)]), 320, 240)
        self.assertFalse(self.detector.last_target['target_valid'])
        self.detector.detect(frame(), 320, 240)
        self.assertFalse(self.detector.last_target['target_valid'])
        self.assertIsNone(self.detector.last_target['target'])
        self.detector.detect(left, 320, 240)
        self.assertFalse(self.detector.last_target['target_valid'])

    def test_boundary_and_saturated_spot_are_rejected(self):
        for point in [(160, 120, 225), (160, 180, 255), (0, 180, 225)]:
            self.detector.reset()
            self.detector.detect(frame([point]), 320, 240)
            self.assertFalse(self.detector.last_target['target_valid'])

    def test_debug_is_decodable_same_size_and_wrong_dimensions_fail(self):
        data = frame([(160, 180, 225)])
        self.detector.detect(data, 320, 240)
        with Image.open(BytesIO(self.detector.last_debug)) as image:
            self.assertEqual(image.size, (320, 240))
        with self.assertRaises(ValueError):
            self.detector.detect(data, 640, 480)


if __name__ == '__main__':
    unittest.main()
