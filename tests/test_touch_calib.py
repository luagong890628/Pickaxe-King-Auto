"""record_touch_calib 的純函式測試：不需要手機、不碰 adb。"""
import unittest

import record_touch_calib as rc

GETEVENT_PL = '''add device 1: /dev/input/event10
  name:     "akm-digital-hall"
add device 3: /dev/input/event8
  name:     "sec_touchpad"
    ABS_MT_POSITION_X     : value 0, min 0, max 4095, fuzz 0, flat 0, resolution 0
    ABS_MT_POSITION_Y     : value 0, min 0, max 4095, fuzz 0, flat 0, resolution 0
add device 4: /dev/input/event7
  name:     "sec_touchscreen"
    ABS_MT_POSITION_X     : value 0, min 0, max 4095, fuzz 0, flat 0, resolution 0
    ABS_MT_POSITION_Y     : value 0, min 0, max 4095, fuzz 0, flat 0, resolution 0
'''


class ParseTest(unittest.TestCase):
    def test_line_without_devname(self):
        ts, typ, code, val = rc.parse_line(
            "[   744359.853412] EV_KEY              BTN_TOUCH            DOWN")
        self.assertAlmostEqual(ts, 744359.853412)
        self.assertEqual((typ, code, val), ("EV_KEY", "BTN_TOUCH", "DOWN"))

    def test_line_with_devname(self):
        ts, typ, code, val = rc.parse_line(
            "[   744360.123456] /dev/input/event7: EV_ABS       ABS_MT_POSITION_X    0000062a")
        self.assertEqual((typ, code), ("EV_ABS", "ABS_MT_POSITION_X"))
        self.assertEqual(rc._num(val), 0x62A)

    def test_garbage(self):
        self.assertIsNone(rc.parse_line("no timestamp here"))

    def test_down_up_flags(self):
        """值可能是 DOWN/UP 字串，也可能是十六進位 1/0（踩過的坑）。"""
        for v in ("DOWN", "00000001", "1"):
            self.assertTrue(rc._is_down(v), v)
        for v in ("UP", "00000000", "0"):
            self.assertTrue(rc._is_up(v), v)
        self.assertFalse(rc._is_down("00000100"))


class DeviceTest(unittest.TestCase):
    def test_picks_touchscreen_not_touchpad(self):
        devs = rc.list_devices(GETEVENT_PL)
        self.assertEqual(len(devs), 3)
        dev = rc.pick_touch_device(devs)
        self.assertEqual(dev["name"], "sec_touchscreen")
        self.assertEqual(dev["path"], "/dev/input/event7")
        self.assertEqual(dev["ranges"]["ABS_MT_POSITION_X"]["max"], 4095)

    def test_no_candidate(self):
        self.assertIsNone(rc.pick_touch_device(rc.list_devices("add device 1: /dev/input/event0\n")))


class FitTest(unittest.TestCase):
    def test_recovers_true_model(self):
        v, t0 = 400.0, 0.1
        pts = [(h, v * (h - t0)) for h in (0.7, 1.1, 1.5, 2.0, 2.6)]
        speed, startup, r2 = rc.fit_mileage(pts)
        self.assertAlmostEqual(speed, v, places=6)
        self.assertAlmostEqual(startup, t0, places=6)
        self.assertAlmostEqual(r2, 1.0, places=6)

    def test_ignores_missing(self):
        pts = [(0.7, None), (1.5, 500.0)]
        self.assertIsNone(rc.fit_mileage(pts))


if __name__ == "__main__":
    unittest.main()
