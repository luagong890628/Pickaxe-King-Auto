"""vision 模組單元測試（合成影像，不需要裝置）。"""
import unittest

import cv2
import numpy as np

from pkauto import vision

SIZE = (1200, 1600)  # h, w
BOX = (0, SIZE[0], 0, SIZE[1])


def make_scene(seed=0):
    rng = np.random.default_rng(seed)
    noise = rng.normal(128, 40, (SIZE[0] // 8, SIZE[1] // 8)).astype(np.uint8)
    bg = cv2.resize(noise, (SIZE[1], SIZE[0]), interpolation=cv2.INTER_LINEAR)
    img = cv2.cvtColor(bg, cv2.COLOR_GRAY2BGR)
    for x, y, w, h, color in [
        (200, 300, 160, 160, (0, 0, 255)),
        (900, 700, 200, 120, (0, 255, 0)),
        (500, 950, 240, 90, (255, 128, 0)),
    ]:
        cv2.rectangle(img, (x, y), (x + w, y + h), color, -1)
    return img


def translate(img, dx, dy):
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]),
                          borderMode=cv2.BORDER_REPLICATE)


class ScrollTest(unittest.TestCase):
    def test_detects_known_shift(self):
        a = make_scene()
        for dx, dy in [(37, -61), (-120, 45), (0, 80)]:
            b = translate(a, dx, dy)
            gx, gy, r = vision.scroll(a, b, box=BOX)
            # 正負號與 warpAffine 同向：內容往右移 dx，量到 +dx
            self.assertAlmostEqual(gx, dx, delta=1.0, msg=f"dx {dx}")
            self.assertAlmostEqual(gy, dy, delta=1.0, msg=f"dy {dy}")
            self.assertGreater(r, 0.3)

    def test_identical_images_zero_shift(self):
        a = make_scene(3)
        gx, gy, r = vision.scroll(a, a.copy(), box=BOX)
        self.assertAlmostEqual(gx, 0.0, delta=0.5)
        self.assertAlmostEqual(gy, 0.0, delta=0.5)
        self.assertGreater(r, 0.9)


class FindTest(unittest.TestCase):
    def test_find_embedded_patch(self):
        img = make_scene(1)
        # 模板必須帶紋理：純色模板在 TM_CCOEFF_NORMED 下是退化情況
        tpl = img[640:840, 840:1160].copy()
        loc = vision.find(img, tpl, threshold=0.95)
        self.assertIsNotNone(loc)
        self.assertAlmostEqual(loc[0], 1000, delta=2)
        self.assertAlmostEqual(loc[1], 740, delta=2)
        self.assertGreater(loc[2], 0.99)

    def test_absent_template_returns_none(self):
        img = make_scene(2)
        checker = (
            np.add.outer(np.arange(96) // 12, np.arange(96) // 12) % 2 * 255
        ).astype(np.uint8)
        tpl = cv2.cvtColor(checker, cv2.COLOR_GRAY2BGR)
        self.assertIsNone(vision.find(img, tpl, threshold=0.9))

    def test_flat_template_rejected(self):
        img = make_scene(6)
        tpl = np.full((50, 50, 3), 128, np.uint8)
        with self.assertRaises(ValueError):
            vision.find(img, tpl)


class DiffTest(unittest.TestCase):
    def test_diff_zero_for_same_image(self):
        a = make_scene(4)
        self.assertEqual(vision.diff(a, a.copy()), 0.0)

    def test_diff_respects_box(self):
        a = make_scene(5)
        b = a.copy()
        b[100:200, 100:200] = 0  # 只在 box 外改動
        box = (300, 600, 300, 600)
        self.assertEqual(vision.diff(a, b, box=box), 0.0)
        self.assertGreater(vision.diff(a, b, box=(0, 300, 0, 300)), 0.0)


if __name__ == "__main__":
    unittest.main()
