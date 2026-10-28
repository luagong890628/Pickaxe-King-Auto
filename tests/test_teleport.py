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
        cf._last_teleport_area = None

    def tearDown(self):
        cf._last_teleport = 0.0
        cf._last_teleport_area = None

    def test_top_menu_gesture_wait_and_confirmed_destinations(self):
        for area, tile in [('farm', (350, 800)), ('village', (350, 1810)), ('start', (720, 1810))]:
            with self.subTest(area=area):
                cf._last_teleport = 0.0
                events = _run(area, now=1000.0)
                self.assertEqual(events, [('tap', cf.HEART), ('wait', cf.TELEPORT_WAIT),
                    ('swipe', (720, 850, 720, 2250, 300)), ('wait', cf.TELEPORT_WAIT),
                    ('tap', tile), ('wait', cf.TELEPORT_WAIT)])

    def test_gesture_wait_is_0_3_seconds(self):
        # 2026-10-26 使用者指示 0.5 → 0.3（三個手勢都改）
        self.assertEqual(cf.TELEPORT_WAIT, 0.3)

    def test_waits_for_cooldown_before_tapping(self):
        """冷卻 12 秒、上次傳送在 6 秒前 → 先等 6 秒才點愛心。"""
        cf._last_teleport = 1000.0
        events = _run('village', now=1006.0)
        self.assertEqual(events[0], ('wait', 6.0))
        self.assertEqual(events[1], ('tap', cf.HEART))

    def test_ice_source_keeps_margin_at_exact_game_cooldown_boundary(self):
        cf._last_teleport = 1000.0
        cf._last_teleport_area = 'ice'
        events = _run('village', now=1000.0 + cf.TELEPORT_COOLDOWN)
        self.assertEqual(events[0], ('wait', cf.TELEPORT_COOLDOWN_MARGIN_BY_SOURCE['ice']))
        self.assertEqual(events[1], ('tap', cf.HEART))

    def test_all_island_sources_keep_one_second_margin(self):
        for area in cf.ISLANDS:
            self.assertEqual(cf.TELEPORT_COOLDOWN_MARGIN_BY_SOURCE[area], 1.0)

    def test_no_wait_once_cooldown_elapsed(self):
        cf._last_teleport = 1000.0
        events = _run('village', now=1020.0)
        self.assertEqual(events[0], ('tap', cf.HEART))

    def test_cooldown_starts_at_destination_not_heart(self):
        events = []
        now = [1000.0]

        def sleep(seconds):
            events.append(('wait', seconds))
            now[0] += seconds

        def tap(*point):
            events.append(('tap', point))
            now[0] += 0.1

        with (patch.object(cf.time, 'time', side_effect=lambda: now[0]),
              patch.object(cf.time, 'sleep', side_effect=sleep),
              patch.object(cf.adb, 'tap', side_effect=tap),
              patch.object(cf.adb, 'swipe', side_effect=lambda *a: events.append(('swipe', a)))):
            cf.teleport('ice', lambda _: None)
            self.assertAlmostEqual(cf._last_teleport, 1000.8)
            cf.teleport('village', lambda _: None)
        self.assertAlmostEqual(events[6][1], 12.7)
        self.assertEqual(events[7], ('tap', cf.HEART))

    def test_records_tap_time_for_next_cooldown(self):
        cf._last_teleport = 0.0
        _run('village', now=1234.5)
        self.assertEqual(cf._last_teleport, 1234.5)


if __name__ == '__main__':
    unittest.main()
