"""選單歸頂固定操作與傳送石冷卻；不連手機。"""
import unittest
from unittest.mock import patch
import cycle_fixed as cf


def _run(area, now):
    """跑一次 teleport，回傳事件序列（含冷卻等待）。"""
    events = []
    with (patch.object(cf.adb, 'tap', side_effect=lambda *a: events.append(('tap', a))),
          patch.object(cf.adb, 'swipe', side_effect=lambda *a: events.append(('swipe', a))),
          patch.object(cf.time, 'time', return_value=now),
          patch.object(cf.time, 'sleep', side_effect=lambda s: events.append(('wait', s)))):
        cf.teleport(area, lambda o: None)
    return events


class TeleportTest(unittest.TestCase):
    def setUp(self):
        cf._last_teleport = 0.0            # 每個測試都從「沒傳送過」開始

    def test_top_menu_gesture_wait_and_confirmed_destinations(self):
        for area, tile in [('farm', (350, 800)), ('village', (350, 1810)), ('start', (720, 1810))]:
            with self.subTest(area=area):
                cf._last_teleport = 0.0
                events = _run(area, now=1000.0)
                self.assertEqual(events, [('tap', cf.HEART), ('wait', 0.5),
                    ('swipe', (720, 850, 720, 2250, 300)), ('wait', 0.5),
                    ('tap', tile), ('wait', 0.5)])

    def test_waits_for_cooldown_before_tapping(self):
        """冷卻 12 秒、上次傳送在 6 秒前 → 先等 6 秒才點愛心。"""
        cf._last_teleport = 1000.0
        events = _run('village', now=1006.0)
        self.assertEqual(events[0], ('wait', 6.0))
        self.assertEqual(events[1], ('tap', cf.HEART))

    def test_no_wait_once_cooldown_elapsed(self):
        cf._last_teleport = 1000.0
        events = _run('village', now=1020.0)
        self.assertEqual(events[0], ('tap', cf.HEART))

    def test_records_tap_time_for_next_cooldown(self):
        cf._last_teleport = 0.0
        _run('village', now=1234.5)
        self.assertEqual(cf._last_teleport, 1234.5)


if __name__ == '__main__':
    unittest.main()
