"""里程模型（px ↔ 按住毫秒）與搖桿速度表的單元測試：不需要手機，不碰 adb。

模型：距離 = 速度(拖曳長度) × 按住秒
      按住毫秒 = px / 速度 * 1000（下限 MIN_HOLD_MS）
速度表：SPEED_TABLE（實測拖曳 50–500px → px/秒）
"""
import unittest

import cycle_fixed as cf


class TestSpeedTable(unittest.TestCase):
    def test_measured_points(self):
        for drag, v in cf.SPEED_TABLE:
            self.assertAlmostEqual(cf.speed_of(drag), v, places=6)

    def test_interpolates_between_points(self):
        v = cf.speed_of(275)                       # 250→466、300→552 的中點
        self.assertGreater(v, 466)
        self.assertLess(v, 552)
        self.assertAlmostEqual(v, (466 + 552) / 2, places=6)

    def test_clamps_outside_table(self):
        self.assertEqual(cf.speed_of(10), cf.SPEED_TABLE[0][1])
        self.assertEqual(cf.speed_of(9999), cf.SPEED_TABLE[-1][1])

    def test_monotonic(self):
        """拖越遠越快（使用者描述的遊戲機制）。"""
        vs = [cf.speed_of(L) for L in range(85, 1201, 25)]
        self.assertEqual(vs, sorted(vs))
        self.assertEqual(len(set(vs)), len(vs))


class TestMileage(unittest.TestCase):
    def test_hold_back_to_px(self):
        """按住毫秒換回 px 要能還原（誤差 ≤ 1px）。"""
        for drag in (250, 400, 500):
            for px in (250, 300, 600, 970, 1035):
                h = cf.hold_ms(px, drag)
                back = (h - cf.STARTUP_MS) / 1000 * cf.speed_of(drag)
                self.assertLessEqual(abs(back - px), 1.0, f"拖{drag} {px}px → {h}ms → {back:.1f}px")

    def test_reference_points(self):
        """2026-10-26 重標後的按住毫秒：拖 250（466px/秒）、拖 400（650px/秒）。"""
        self.assertEqual(cf.hold_ms(960, 250), 2060)
        self.assertEqual(cf.hold_ms(250, 250), 536)
        self.assertEqual(cf.hold_ms(960, 400), 1476)

    def test_matches_measured_legs(self):
        """2026-10-26 實測：拖 1200 按住 924ms→800px、拖 85 按住 3798ms→587px（誤差 <2%）。"""
        for drag, hold, measured in ((1200, 924, 800), (85, 3798, 587)):
            pred = hold / 1000 * cf.speed_of(drag)
            self.assertLess(abs(pred - measured) / measured, 0.02,
                            f"拖{drag} {hold}ms 預測 {pred:.0f}px")

    def test_matches_other_drags(self):
        """拖 500 按住 739ms→532px、拖 250 按住 1457ms→676px（誤差 <3%）。"""
        for drag, hold, measured in ((500, 739, 532), (250, 1457, 676)):
            pred = hold / 1000 * cf.speed_of(drag)
            self.assertLess(abs(pred - measured) / measured, 0.03,
                            f"拖{drag} {hold}ms 預測 {pred:.0f}px")

    def test_min_hold(self):
        """極短距離不可低於 MIN_HOLD_MS。"""
        self.assertEqual(cf.hold_ms(20, 400), cf.MIN_HOLD_MS)

    def test_long_hold_has_no_upper_cap(self):
        self.assertGreater(cf.hold_ms(700, 85), 4000)
        self.assertGreater(cf.hold_ms(4000, 85), 20000)



class TestSpeedScale(unittest.TestCase):
    """全域速度倍率：遊戲改跑速後，整張表同比例放大，按住毫秒同比縮短。"""

    def setUp(self):
        self._old = cf.SPEED_SCALE

    def tearDown(self):
        cf.SPEED_SCALE = self._old

    def test_scale_multiplies_table_speed(self):
        cf.SPEED_SCALE = 1.3
        for drag, v in cf.SPEED_TABLE:
            self.assertAlmostEqual(cf.speed_of(drag), v * 1.3, places=6)

    def test_scale_shortens_hold(self):
        base = cf.hold_ms(850, 250)
        cf.SPEED_SCALE = 2.0
        self.assertAlmostEqual(cf.hold_ms(850, 250), base / 2, delta=1)

    def test_default_scale_is_one(self):
        self.assertEqual(self._old, 1.0)
        self.assertAlmostEqual(cf.speed_of(250), 466.0, places=6)

    def test_scale_keeps_curve_shape(self):
        """倍率不改曲線形狀：任何兩點的速度比不變。"""
        before = cf.speed_of(400) / cf.speed_of(250)
        cf.SPEED_SCALE = 1.45
        self.assertAlmostEqual(cf.speed_of(400) / cf.speed_of(250), before, places=9)


if __name__ == "__main__":
    unittest.main()
