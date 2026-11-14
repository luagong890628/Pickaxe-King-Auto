"""休息完成後固定點磁鐵，不連手機。"""
import unittest
from unittest.mock import patch

import cycle_fixed as cf


class RestMagnetTest(unittest.TestCase):
    def test_magnet_is_tapped_once_after_rest_wait_without_screenshot(self):
        events = []
        image = object()
        with (patch.object(cf, 'MEASURE', False),
              patch.object(cf.adb, 'tap', side_effect=lambda *p: events.append(('tap', p))),
              patch.object(cf.time, 'sleep', side_effect=lambda s: events.append(('wait', s))),
              patch.object(cf, 'shot', side_effect=AssertionError('不應截圖'))):
            result = cf.rest(lambda event: None, image, '起始之地')
        self.assertIs(result, image)
        self.assertEqual(events, [('tap', cf.REST_TAP), ('wait', cf.REST_WAIT),
                                  ('tap', (1330, 1855))])


if __name__ == '__main__':
    unittest.main()
