"""選單歸頂固定操作；不連手機。"""
import unittest
from unittest.mock import patch
import cycle_fixed as cf


class TeleportTest(unittest.TestCase):
    def test_top_menu_gesture_wait_and_confirmed_destinations(self):
        for area, tile in [('farm', (350, 800)), ('village', (350, 1810)), ('start', (720, 1810))]:
            with self.subTest(area=area):
                events = []
                with (patch.object(cf.adb, 'tap', side_effect=lambda *a: events.append(('tap', a))),
                      patch.object(cf.adb, 'swipe', side_effect=lambda *a: events.append(('swipe', a))),
                      patch.object(cf.time, 'sleep', side_effect=lambda s: events.append(('wait', s)))):
                    cf.teleport(area, lambda o: None)
                self.assertEqual(events, [('tap', cf.HEART), ('wait', 1.0),
                    ('swipe', (720, 850, 720, 2250, 300)), ('wait', 2.0),
                    ('tap', tile), ('wait', 1.0)])


if __name__ == '__main__':
    unittest.main()
