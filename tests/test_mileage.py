"""里程模型（px ↔ 按住毫秒）的單元測試：不需要手機，不碰 adb。

模型：距離 ≈ SPEED × (按住秒 − STARTUP)
所以：按住毫秒 = px / SPEED * 1000 + STARTUP_MS（下限 MIN_HOLD_MS）
現況：SPEED = 346px/秒、STARTUP_MS = 0（同場兩點實測，見 cycle_fixed.py 註解）
"""
import math
import unittest

import cycle_fixed as cf


class TestMileage(unittest.TestCase):
    def test_hold_back_to_px(self):
        """按住毫秒換回 px 要能還原（誤差 ≤ 1px）。"""
        for px in (250, 300, 600, 970, 1035):
            h = cf.hold_ms(px)
            back = (h - cf.STARTUP_MS) / 1000 * cf.SPEED
            self.assertLessEqual(abs(back - px), 1.0, f"{px}px → {h}ms → {back:.1f}px")

    def test_reference_points(self):
        """按住毫秒對照（SPEED=346、無起步補償）。"""
        self.assertEqual(cf.hold_ms(960), 2774)
        self.assertEqual(cf.hold_ms(250), 722)

    def test_matches_measured_legs(self):
        """2026-10-21 同場實測兩點：2809ms→978px、847ms→291px，模型誤差 <2%。"""
        for hold_ms, measured in ((2809, 978), (847, 291)):
            pred = (hold_ms - cf.STARTUP_MS) / 1000 * cf.SPEED
            self.assertLess(abs(pred - measured) / measured, 0.02, f"{hold_ms}ms 預測 {pred:.0f}px")

    def test_min_hold(self):
        """極短距離不可低於 500ms（否則被遊戲判成點擊）。"""
        self.assertEqual(cf.hold_ms(50), cf.MIN_HOLD_MS)

    def test_split_count(self):
        """單段不超過 MAX_HOLD_MS；拆段後每段都要含起步補償且在上限內。"""
        self.assertEqual(cf.split_count(970), 1)
        for px in (1100, 1500, 2400):
            n = cf.split_count(px)
            self.assertGreaterEqual(n, 2)
            seg = px / n
            self.assertLessEqual(cf.hold_ms(seg), cf.MAX_HOLD_MS, f"{px}px 拆 {n} 段超出上限")
            # 拆段後總距離仍等於 px（每段各自補起步）
            self.assertAlmostEqual(seg * n, px, places=6)

    def test_split_usable_window(self):
        """拆段判斷用「MAX_HOLD_MS − STARTUP_MS」的可用時長（不是整段上限）。"""
        usable = cf.MAX_HOLD_MS - cf.STARTUP_MS
        px = usable / 1000 * cf.SPEED - 1        # 剛好塞得進一段
        self.assertEqual(cf.split_count(px), 1)
        px = usable / 1000 * cf.SPEED + 1        # 多 1px 就要拆
        self.assertEqual(cf.split_count(px), 2)


if __name__ == "__main__":
    unittest.main()
