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
            self.assertEqual((d, px), cf.route_act(act)[:2])
            self.assertEqual(kw.get('drag_len', cf.DRAG_LEN), cf.route_drag(area, i))
            self.assertEqual(kw['settle'], cf.route_settle(area, i))

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

        # 一組＝第 3 段（東 700）＋第 4 段（西 700），拖曳都 300、停頓照 route_settle
        self.assertEqual([(d, px, kw['drag_len'], kw['settle']) for d, px, kw in calls],
                         [('R', 700.0, 300, cf.route_settle('farm', 3)),
                          ('L', 700.0, 300, cf.route_settle('farm', 4))] * 2)

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
                d, px = cf.route_act(act)[:2]
                drag = cf.route_drag(area, i)
                holds = str(cf.hold_ms(px, drag))
                self.assertIn(f'{i}. {cf.NAMES[d]} {px:.0f}px → 拖 {drag}px／按住 {holds}ms', section)
            self.assertIn(str(cf.TILE[area]), section)
        self.assertIn(f'愛心{cf.HEART}', text)
        self.assertIn(f'休息{cf.REST_TAP}', text)


class PerLegDragOverrideTest(unittest.TestCase):
    """單段拖曳覆寫：只放慢漏砍的那一段，其餘維持該區預設。"""

    def setUp(self):
        self.saved = {a: list(cf.ROUTES[a]) for a in ('village', 'start', 'farm')}

    def tearDown(self):
        for a, v in self.saved.items():
            cf.ROUTES[a][:] = v

    def test_two_element_leg_has_no_override(self):
        self.assertEqual(cf.route_act(('N', 1000.0)), ('N', 1000.0, None))
        self.assertEqual(cf.route_drag('village', 1), cf.ENTRY_DRAG)

    def test_three_element_leg_overrides_route_drag(self):
        # 第 3 段（林內，預設拖 FOREST_DRAG）改成只拖 150
        cf.ROUTES['village'][2] = ('L', 300.0, 150)
        self.assertEqual(cf.route_act(cf.ROUTES['village'][2]), ('L', 300.0, 150.0))
        self.assertEqual(cf.route_drag('village', 3), 150)
        # 隔壁段不受影響
        self.assertEqual(cf.route_drag('village', 4), cf.FOREST_DRAG)

    def test_override_beats_entry_drag(self):
        cf.ROUTES['village'][0] = ('N', 1000.0, 600)
        self.assertEqual(cf.route_drag('village', 1), 600)

    def test_rest_entry_normalizes(self):
        self.assertEqual(cf.route_act(('REST',)), ('REST', 0.0, None))

    def test_override_is_used_by_leg_call(self):
        cf.ROUTES['village'][2] = ('L', 300.0, 150)
        calls = []

        def leg(img, d, px, rec, label, **kwargs):
            calls.append((d, px, kwargs['drag_len']))

        with patch.object(cf, 'leg', side_effect=leg):
            for i, act in enumerate(cf.ROUTES['village'], 1):
                d, px, _ = cf.route_act(act)
                cf.leg(None, d, px, lambda o: None, 'v', drag_len=cf.route_drag('village', i))
        self.assertEqual(calls[2], ('L', 300.0, 150))


class PerLegSettleTest(unittest.TestCase):
    """到點停頓：只有 SETTLE_LEGS 指到的段才停，其餘用 SETTLE（預設 0）。"""

    def test_only_listed_legs_pause(self):
        pauses = [n for n in range(1, 19) if cf.route_settle('village', n)]
        self.assertEqual(pauses, sorted(cf.SETTLE_LEGS['village']))

    def test_unlisted_leg_uses_global_default(self):
        self.assertEqual(cf.SETTLE, 0.0)
        self.assertEqual(cf.route_settle('village', 1), 0.0)
        self.assertEqual(cf.route_settle('village', 18), 0.0)

    def test_listed_leg_pauses(self):
        for n in (3, 5, 7, 12, 14, 15, 17):
            self.assertEqual(cf.route_settle('village', n), 0.5)

    def test_start_shares_village_tail_pauses(self):
        # 起始之地第 4 段起＝小村莊第 4 段起 → 停頓點必須一致（第 3 段是合併西走，也沿用）
        for n in range(3, len(cf.ROUTES['start']) + 1):
            self.assertEqual(cf.route_settle('start', n), cf.route_settle('village', n))
        # 前兩段是自己的（進場 + 休息），不停
        self.assertEqual(cf.route_settle('start', 1), 0.0)
        self.assertEqual(cf.route_settle('start', 2), 0.0)

    def test_farm_does_not_pause_yet(self):
        self.assertEqual([n for n in range(1, len(cf.ROUTES['farm']) + 1)
                          if cf.route_settle('farm', n)], [])

    def test_start_route_is_prefix_plus_village_tail(self):
        self.assertEqual(cf.ROUTES['start'][:3],
                         [('N', 425.0), ('REST',), ('L', 450.0)])
        self.assertEqual(cf.ROUTES['start'][3:], cf.VILLAGE[3:])

    def test_leg_12_north_is_longer(self):
        self.assertEqual(cf.route_act(cf.ROUTES['village'][11]), ('N', 150.0, None))


class PearlTest(unittest.TestCase):
    """珍珠：往西 1080 → 點 (721,1839) → 往東 1080 回原位；冷卻 10 分鐘。"""

    def setUp(self):
        self.saved = cf._pearl_at
        cf._pearl_at = 0.0

    def tearDown(self):
        cf._pearl_at = self.saved

    def _run(self):
        calls = []

        def leg(img, d, px, rec, label, **kw):
            calls.append((d, px, label, kw.get('drag_len')))
            return img

        with (patch.object(cf, 'leg', side_effect=leg),
              patch.object(cf.adb, 'tap') as tap,
              patch.object(cf.time, 'sleep')):
            cf.pearl(lambda o: None, None)
        return calls, tap

    def test_first_time_takes_pearl_and_returns(self):
        calls, tap = self._run()
        self.assertEqual([(d, px) for d, px, _, _ in calls],
                         [('L', cf.PEARL_WEST), ('R', cf.PEARL_EAST)])
        # 去程和回程距離必須相同，才會回到傳送落點
        self.assertEqual(cf.PEARL_WEST, cf.PEARL_EAST)
        tap.assert_called_once_with(*cf.REST_TAP)
        self.assertGreater(cf._pearl_at, 0)

    def test_skips_while_cooling_down(self):
        cf._pearl_at = cf.time.time()
        calls, tap = self._run()
        self.assertEqual(calls, [])
        tap.assert_not_called()

    def test_takes_again_after_cooldown(self):
        cf._pearl_at = cf.time.time() - (cf.PEARL_COOLDOWN + 1)
        calls, _ = self._run()
        self.assertEqual(len(calls), 2)

    def test_cooldown_is_ten_minutes(self):
        self.assertEqual(cf.PEARL_COOLDOWN, 600.0)


if __name__ == '__main__':
    unittest.main()
