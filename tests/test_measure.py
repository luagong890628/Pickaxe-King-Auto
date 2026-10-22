"""pkauto/measure.py 的交叉驗證測試（合成影像，不需要手機）。"""
import unittest

import cv2
import numpy as np

from pkauto import measure


def textured(h=3120, w=1440, seed=7):
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    return cv2.GaussianBlur(img, (3, 3), 0)


class WorldShiftTest(unittest.TestCase):
    def test_known_shift_is_character_displacement(self):
        """畫面內容往右移 40px ＝ 角色往左走 40px → dx 應為 -40。"""
        a = textured()
        b = np.roll(a, 40, axis=1)
        dx, dy, score, src = measure.world_shift(a, b)
        self.assertAlmostEqual(dx, -40, delta=2)
        self.assertAlmostEqual(dy, 0, delta=2)
        self.assertGreater(score, 0.9)
        self.assertIn(src, ("template", "scroll", "template!", "scroll!"))

    def test_downward_content_shift(self):
        a = textured(seed=11)
        b = np.roll(a, 35, axis=0)
        dx, dy, _, _ = measure.world_shift(a, b)
        self.assertAlmostEqual(dy, -35, delta=2)

    def test_flat_image_does_not_crash(self):
        a = np.full((3120, 1440, 3), 128, np.uint8)
        out = measure.world_shift(a, a.copy())
        self.assertEqual(len(out), 4)
        self.assertIn(out[3], ("scroll", "scroll?", "低信心"))


if __name__ == "__main__":
    unittest.main()
