from io import BytesIO
import unittest

from PIL import Image, ImageDraw

from pi4_camera_vision.red_laser import RedLaserDetector


def picture(spots=(), white_core=False):
    image = Image.new('RGB', (320, 240), (70, 70, 70))
    draw = ImageDraw.Draw(image)
    for x, y, radius, color in spots:
        if radius == 0:
            draw.point((x, y), fill=color)
        else:
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
        if white_core:
            draw.point((x, y), fill='white')
    stream = BytesIO()
    image.save(stream, 'JPEG', quality=100, subsampling=0)
    return stream.getvalue()


class RedLaserTests(unittest.TestCase):
    def setUp(self):
        self.detector = RedLaserDetector()

    def confirmed(self, data):
        self.detector.detect(data, 320, 240)
        self.detector.detect(data, 320, 240)
        return self.detector.last_target

    def test_tiny_red_pixel_survives_without_morphology(self):
        target = self.confirmed(picture([(160, 180, 0, (245, 20, 20))]))
        self.assertTrue(target['target_valid'])
        self.assertEqual(target['mode'], 'red_laser_spot')
        self.assertAlmostEqual(target['target']['target_px']['x'], 160, delta=1)
        self.assertNotIn('horizontal_error', target['target'])

    def test_white_core_attached_to_red_is_included(self):
        target = self.confirmed(picture([(230, 185, 2, (245, 20, 20))], white_core=True))
        self.assertTrue(target['target_valid'])
        self.assertAlmostEqual(target['target']['target_px']['x'], 230, delta=1)

    def test_white_reflection_and_blue_are_not_red_laser(self):
        target = self.confirmed(picture([(80, 180, 2, (255, 255, 255)), (230, 180, 2, (20, 20, 255))]))
        self.assertFalse(target['target_valid'])

    def test_top_half_and_large_red_region_are_rejected(self):
        target = self.confirmed(picture([(60, 80, 2, (245, 20, 20)), (230, 180, 18, (245, 20, 20))]))
        self.assertFalse(target['target_valid'])

    def test_equal_red_candidates_are_ambiguous(self):
        target = self.confirmed(picture([(60, 180, 2, (245, 20, 20)), (230, 180, 2, (245, 20, 20))]))
        self.assertEqual(target['state'], 'ambiguous')
        self.assertIsNone(target['target'])

    def test_motion_loss_and_reconfirmation(self):
        self.assertTrue(self.confirmed(picture([(150, 180, 2, (245, 20, 20))]))['target_valid'])
        old_id = self.detector.last_target['target']['track_id']
        self.detector.detect(picture([(155, 182, 2, (245, 20, 20))]), 320, 240)
        self.assertTrue(self.detector.last_target['target_valid'])
        self.assertEqual(old_id, self.detector.last_target['target']['track_id'])
        self.detector.detect(picture(), 320, 240)
        self.assertIsNone(self.detector.last_target['target'])
        self.detector.detect(picture([(155, 182, 2, (245, 20, 20))]), 320, 240)
        self.assertFalse(self.detector.last_target['target_valid'])

    def test_bottom_quarter_remains_detectable_for_emergency_stop(self):
        target = self.confirmed(picture([(160, 210, 2, (245, 20, 20))]))
        self.assertTrue(target['target_valid'])
        self.assertGreaterEqual(target['target']['target_normalized']['y'], 0.75)


if __name__ == '__main__':
    unittest.main()
