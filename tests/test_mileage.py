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
        v = cf.speed_of(275)                       # 250→343、300→405 的中點
        self.assertGreater(v, 343)
        self.assertLess(v, 405)
        self.assertAlmostEqual(v, (343 + 405) / 2, places=6)

    def test_clamps_outside_table(self):
        self.assertEqual(cf.speed_of(10), cf.SPEED_TABLE[0][1])
        self.assertEqual(cf.speed_of(9999), cf.SPEED_TABLE[-1][1])

    def test_monotonic(self):
        """拖越遠越快（使用者描述的遊戲機制）。"""
        vs = [cf.speed_of(L) for L in range(50, 501, 25)]
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
        """拖 250px（343px/秒）與拖 400px（488px/秒）的按住毫秒。"""
        self.assertEqual(cf.hold_ms(960, 250), 2798)
        self.assertEqual(cf.hold_ms(250, 250), 728)
        self.assertEqual(cf.hold_ms(960, 400), 1967)

    def test_matches_measured_legs(self):
        """2026-10-21 實測：拖 250px 按住 2809ms→978px、847ms→291px（誤差 <2%）。"""
        for hold, measured in ((2809, 978), (847, 291)):
            pred = (hold - cf.STARTUP_MS) / 1000 * cf.speed_of(250)
            self.assertLess(abs(pred - measured) / measured, 0.02, f"{hold}ms 預測 {pred:.0f}px")

    def test_matches_fast_legs(self):
        """拖 400px 實測 970px→968px；拖 500px 實測 949px（誤差 <3%）。"""
        for drag, target, measured in ((400, 970, 968), (500, 970, 949)):
            self.assertLess(abs(measured - target) / target, 0.03)
            self.assertGreater(cf.hold_ms(target, drag), 0)

    def test_min_hold(self):
        """極短距離不可低於 MIN_HOLD_MS。"""
        self.assertEqual(cf.hold_ms(20, 400), cf.MIN_HOLD_MS)

    def test_split_count(self):
        """單段不超過 MAX_HOLD_MS；拆段後每段都要在上限內。"""
        self.assertEqual(cf.split_count(970, 250), 1)
        self.assertEqual(cf.split_count(970, 400), 1)
        for drag in (250, 400):
            for px in (2400, 3000):
                n = cf.split_count(px, drag)
                self.assertGreaterEqual(n, 2)
                self.assertLessEqual(cf.hold_ms(px / n, drag), cf.MAX_HOLD_MS)

    def test_split_usable_window(self):
        """拆段判斷用「MAX_HOLD_MS − STARTUP_MS」的可用時長（不是整段上限）。"""
        usable = cf.MAX_HOLD_MS - cf.STARTUP_MS
        v = cf.speed_of(250)
        self.assertEqual(cf.split_count(usable / 1000 * v - 1, 250), 1)
        self.assertEqual(cf.split_count(usable / 1000 * v + 1, 250), 2)


if __name__ == "__main__":
    unittest.main()
