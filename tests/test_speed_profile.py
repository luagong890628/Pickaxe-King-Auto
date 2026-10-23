"""進場快、林內慢；路線 px 不變，取消移動後停頓，不連手機。"""
import contextlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

import cycle_fixed as cf


class SpeedProfileTest(unittest.TestCase):
    def test_main_uses_fast_entry_and_slow_forest_without_settle(self):
        calls = []
        clock = [0.0]

        def leg(img, d, px, rec, label, **kwargs):
            calls.append((d, px, kwargs))
            clock[0] += 10

        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with (patch('sys.argv', ['cycle_fixed.py', '--minutes', '.1']),
                      patch.object(cf.time, 'time', side_effect=lambda: clock[0]),
                      patch.object(cf, 'teleport'), patch.object(cf, 'rest'),
                      patch.object(cf, 'leg', side_effect=leg),
                      patch.object(cf, 'shot', side_effect=AssertionError('不應截圖')),
                      contextlib.redirect_stdout(io.StringIO())):
                    cf.main()
            finally:
                os.chdir(cwd)
        entry = {'village': {1, 2}, 'start': {1, 3}}
        expected = [(a, i, act) for a in ('village', 'start')
                    for i, act in enumerate(cf.ROUTES[a], 1) if act[0] != 'REST']
        self.assertEqual(len(calls), len(expected))
        for (d, px, kw), (area, i, act) in zip(calls, expected):
            self.assertEqual((d, px), act)
            self.assertEqual(kw.get('drag_len', cf.DRAG_LEN), (250 if act[0] == 'L' else 600) if i in entry[area] else 85)
            self.assertEqual(kw['settle'], 0)

    def test_movement_does_not_sleep_even_when_split(self):
        with (patch.object(cf, 'MEASURE', False), patch.object(cf.adb, 'swipe') as swipe,
              patch.object(cf.time, 'sleep') as sleep):
            cf.leg(None, 'L', 250, lambda o: None, 'test', drag_len=52, settle=0)
        self.assertGreater(swipe.call_count, 1)
        sleep.assert_not_called()

    def test_dry_run_reports_both_speeds(self):
        out = io.StringIO()
        with patch('sys.argv', ['cycle_fixed.py', '--dry-run']), contextlib.redirect_stdout(out):
            cf.main()
        text = out.getvalue()
        self.assertIn('拖 600px', text)
        self.assertIn('拖 85px', text)
        entry = {'village': {1, 2}, 'start': {1, 3}}
        sections = text.split('\n[')[1:]
        self.assertEqual(len(sections), 2)
        for area, section in zip(('village', 'start'), sections):
            for i, act in enumerate(cf.ROUTES[area], 1):
                if act[0] == 'REST':
                    self.assertIn(f'{i}. 休息（點 {cf.REST_TAP}，等 {cf.REST_WAIT}s）', section)
                    continue
                d, px = act
                drag = (250 if act[0] == 'L' else 600) if i in entry[area] else 85
                n = cf.split_count(px, drag)
                holds = ' + '.join(str(cf.hold_ms(px / n, drag)) for _ in range(n))
                self.assertIn(f'{i}. {cf.NAMES[d]} {px:.0f}px → 拖 {drag}px／按住 {holds}ms', section)
            self.assertIn(str(cf.TILE[area]), section)
        self.assertIn(f'愛心{cf.HEART}', text)
        self.assertIn(f'休息{cf.REST_TAP}', text)


if __name__ == '__main__':
    unittest.main()
