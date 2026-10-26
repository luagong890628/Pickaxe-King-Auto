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
        expected = [(a, i, act) for a in ('village', 'start', 'farm')
                    for i, act in enumerate(cf.ROUTES[a], 1) if act[0] != 'REST']
        # 農場走完固定路線後，再補固定組數的 3、4 段來回（同一組速度、不停頓）
        expected += [('farm', n, cf.ROUTES['farm'][n - 1])
                     for _ in range(cf.FILL_PAIRS) for n in cf.FILL_LEGS['farm']]
        self.assertEqual(len(calls), len(expected))
        for (d, px, kw), (area, i, act) in zip(calls, expected):
            self.assertEqual((d, px), act)
            self.assertEqual(kw.get('drag_len', cf.DRAG_LEN), cf.route_drag(area, i))
            self.assertEqual(kw['settle'], 0)

    def test_farm_route_distances_and_per_leg_drag(self):
        self.assertEqual(cf.ROUTES['farm'],
                         [('N', 600.0), ('L', 350.0), ('R', 700.0), ('L', 700.0)])
        # 第 1 步維持進場速度；西 350、東 700、西 700 都拖 300
        self.assertEqual([cf.route_drag('farm', n) for n in (1, 2, 3, 4)],
                         [cf.ENTRY_DRAG, 300, 300, 300])

    def test_farm_fill_repeats_legs_3_4_by_fixed_pairs(self):
        calls = []

        def leg(img, d, px, rec, label, **kwargs):
            calls.append((d, px, kwargs))

        with patch.object(cf, 'leg', side_effect=leg):
            cf.fill_cycle('farm', lambda o: None, None, pairs=2)

        # 一組＝第 3 段（東 700）＋第 4 段（西 700），拖曳都 300、不停頓
        self.assertEqual([(d, px, kw['drag_len'], kw['settle']) for d, px, kw in calls],
                         [('R', 700.0, 300, 0), ('L', 700.0, 300, 0)] * 2)

    def test_farm_fill_defaults_to_configured_pair_count(self):
        with patch.object(cf, 'leg') as leg:
            cf.fill_cycle('farm', lambda o: None, None)
        self.assertEqual(leg.call_count, cf.FILL_PAIRS * len(cf.FILL_LEGS['farm']))

    def test_long_movement_is_one_gesture_without_sleep(self):
        with (patch.object(cf, 'MEASURE', False), patch.object(cf.adb, 'swipe') as swipe,
              patch.object(cf.time, 'sleep') as sleep):
            cf.leg(None, 'L', 450, lambda o: None, 'test', drag_len=85, settle=0)
        self.assertEqual(swipe.call_count, 1)
        self.assertEqual(swipe.call_args.args[-1], cf.hold_ms(450, 85))
        sleep.assert_not_called()

    def test_dry_run_reports_both_speeds(self):
        out = io.StringIO()
        with patch('sys.argv', ['cycle_fixed.py', '--dry-run']), contextlib.redirect_stdout(out):
            cf.main()
        text = out.getvalue()
        self.assertIn(f'拖 {cf.ENTRY_DRAG}px', text)
        self.assertIn(f'拖 {cf.FOREST_DRAG}px', text)
        sections = text.split('\n[')[1:]
        self.assertEqual(len(sections), 3)
        for area, section in zip(('village', 'start', 'farm'), sections):
            for i, act in enumerate(cf.ROUTES[area], 1):
                if act[0] == 'REST':
                    self.assertIn(f'{i}. 休息（點 {cf.REST_TAP}，等 {cf.REST_WAIT}s）', section)
                    continue
                d, px = act
                drag = cf.route_drag(area, i)
                holds = str(cf.hold_ms(px, drag))
                self.assertIn(f'{i}. {cf.NAMES[d]} {px:.0f}px → 拖 {drag}px／按住 {holds}ms', section)
            self.assertIn(str(cf.TILE[area]), section)
        self.assertIn(f'愛心{cf.HEART}', text)
        self.assertIn(f'休息{cf.REST_TAP}', text)


if __name__ == '__main__':
    unittest.main()
