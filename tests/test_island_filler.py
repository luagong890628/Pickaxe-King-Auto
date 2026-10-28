import itertools
import unittest
from unittest.mock import patch

import cycle_fixed as cf


class IslandFillerContractTest(unittest.TestCase):
    def test_weights_and_exclusion(self):
        self.assertEqual(cf.ISLAND_WEIGHTS, {"ice": 30, "shark": 25, "duck": 25, "truffle": 20})
        with patch.object(cf.random, "choices", return_value=["shark"]) as choices:
            self.assertEqual(cf.choose_island({"ice"}), "shark")
        choices.assert_called_once_with(
            ["shark", "duck", "truffle"], weights=[25, 25, 20], k=1)

    def test_weighted_choice_uses_only_unused_candidates(self):
        with patch.object(cf.random, "choices", return_value=["shark"]) as choices:
            self.assertEqual(cf.choose_island(), "shark")
        choices.assert_called_once_with(["ice", "shark", "duck", "truffle"], weights=[30, 25, 25, 20], k=1)

    def test_island_route_entry_once_then_unbounded_laps(self):
        actions = list(itertools.islice(cf.island_actions("shark"), 2 + 4 * 4))
        self.assertEqual(actions[:2], cf.ISLAND_ROUTES["shark"][:2])
        self.assertEqual(actions[2:], cf.ISLAND_ROUTES["shark"][2:] * 4)

    def test_island_dwell_uses_real_elapsed_seconds(self):
        self.assertEqual(cf.ISLAND_MIN_DWELL, 12.0)
        with patch.object(cf.time, "time", return_value=100.0), \
             patch.object(cf.time, "perf_counter", return_value=112.5):
            self.assertEqual(cf.island_dwell_elapsed(100.0), 12.5)

    def test_switch_island_excludes_only_island_just_left(self):
        with patch.object(cf.random, "choices", return_value=["shark"]) as choices:
            self.assertEqual(cf.choose_island({"ice"}), "shark")
        choices.assert_called_once_with(
            ["shark", "duck", "truffle"], weights=[25, 25, 20], k=1)

    def test_farm_fill_pairs_is_not_shortened_by_deadline(self):
        self.assertEqual(cf.FILL_PAIRS, 6)

    def test_farm_fill_executes_all_six_pairs(self):
        calls = []
        with patch.object(cf, "leg", side_effect=lambda img, d, px, rec, label, **kw:
                          calls.append((d, px)) or img):
            cf.fill_cycle("farm", lambda _: None, None)
        self.assertEqual(calls, [("R", 700.0), ("L", 700.0)] * 6)

    def exercise_filler(self, seconds, deadline, choices, cooldown=lambda: True):
        now = [100.0]
        moves, transfers, rows = [], [], []

        def move(img, d, px, rec, label, **kw):
            moves.append((label, d, px))
            now[0] += seconds
            return img

        with (patch.object(cf, 'choose_island', side_effect=choices) as choose,
              patch.object(cf, 'teleport', side_effect=lambda area, rec: transfers.append((area, now[0]))),
              patch.object(cf, 'leg', side_effect=move),
              patch.object(cf, '_teleport_cooldown_ready', side_effect=lambda: cooldown()),
              patch.object(cf.time, 'time', side_effect=lambda: now[0]),
              patch.object(cf.time, 'perf_counter', side_effect=lambda: now[0])):
            worked = cf.run_island_filler(rows.append, deadline)
        return moves, transfers, rows, choose, worked

    def test_few_seconds_left_switches_at_minimum_and_new_island_keeps_minimum(self):
        moves, transfers, rows, choose, worked = self.exercise_filler(
            3.0, 121.0, ['ice', 'shark'])
        self.assertTrue(worked)
        self.assertEqual(transfers[:2], [('ice', 100.0), ('shark', 118.0)])
        self.assertEqual([r['gesture'] for r in rows if r.get('decision') == 'switch'], [6])
        self.assertGreaterEqual(len([m for m in moves if m[0] == '鯊魚島補空檔']), 6)
        self.assertEqual(choose.call_args_list[1].args, ({'ice'},))

    def test_cooldown_unready_continues_complete_loops_without_menu_or_sleep(self):
        checks = iter([False, False, True])
        with patch.object(cf.time, 'sleep', side_effect=AssertionError('stationary wait')):
            moves, transfers, rows, _, _ = self.exercise_filler(
                0.5, 101.0, ['ice', None], cooldown=lambda: next(checks))
        self.assertEqual([a for a, _ in transfers], ['ice'])
        self.assertEqual(len(moves), 34)  # entry 2 + eight full loops
        self.assertEqual(rows[-1]['decision'], 'return')

    def test_switch_waits_for_cooldown_by_walking_more_loops(self):
        checks = iter([False, False, True, True])
        moves, transfers, _, _, _ = self.exercise_filler(
            3.0, 145.0, ['ice', 'shark', None], cooldown=lambda: next(checks, True))
        self.assertEqual(transfers[:2], [('ice', 100.0), ('shark', 142.0)])
        self.assertEqual(len([m for m in moves if m[0] == '冰雪魔像島補空檔']), 14)

    def test_minimum_dwell_and_log_use_complete_loop_boundary(self):
        moves, transfers, rows, _, _ = self.exercise_filler(1.0, 101.0, ['ice'])
        self.assertEqual(len(moves), 14)  # 2 entry + 3 complete loops, 14s dwell
        self.assertEqual([a for a, _ in transfers], ['ice'])
        runtime = [r for r in rows if 'dwell_s' in r]
        self.assertEqual(runtime[-1]['dwell_s'], 14.0)
        self.assertEqual(runtime[-1]['circle'], 3)

    def test_no_next_candidate_never_teleports_village_early(self):
        moves, transfers, _, _, worked = self.exercise_filler(3.0, 200.0, ['ice', None])
        self.assertTrue(worked)
        self.assertEqual(transfers, [('ice', 100.0)])
        self.assertEqual(len(moves), 34)  # remain on this island until due, no re-entry

    def test_main_cycles_one_is_primary_three_only(self):
        self.assertEqual(cf.primary_cycle_limit(1), 3)

    def test_filler_runs_full_laps_without_adb_and_stops_at_boundary(self):
        calls = []
        now = [90.0]

        def fake_leg(img, d, px, rec, label, **kwargs):
            calls.append((d, px))
            return img

        with (patch.object(cf, "choose_island", return_value="ice"),
              patch.object(cf, "teleport"),
              patch.object(cf, "leg", side_effect=fake_leg),
              patch.object(cf.time, "time", side_effect=lambda: now[0]),
              patch.object(cf.time, "perf_counter", side_effect=lambda: now[0])):
            # The deadline arrives during loop gesture #3. Finish #4 too,
            # rather than leaving the island at a mid-loop coordinate.
            def finish_after_gesture(*args, **kwargs):
                calls.append((args[1], args[2]))
                now[0] += 3.0
                return args[0]
            with patch.object(cf, "leg", side_effect=finish_after_gesture):
                cf.run_island_filler(lambda _: None, 105.0)

        self.assertEqual(calls, [cf.route_act(act)[:2] for act in cf.ROUTES['ice']])
        self.assertEqual(now[0], 108.0)


if __name__ == "__main__":
    unittest.main()
