import contextlib
import io
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

    def test_island_loop_count_switches_after_four_complete_loops(self):
        calls = []
        now = [0.0]
        with patch.object(cf, "choose_island", side_effect=["ice", "shark", None]), \
             patch.object(cf, "teleport"), \
             patch.object(cf, "leg", side_effect=lambda img, d, px, rec, label, **kw:
                          calls.append(label) or img), \
             patch.object(cf.time, "time", side_effect=lambda: now[0]), \
             patch.object(cf.time, "perf_counter", side_effect=lambda: now[0]):
            cf.run_island_filler(lambda _: None, 999.0)
        self.assertEqual(calls[:2 + 4 * 4],
                         ["冰雪魔像島補空檔"] * (2 + 4 * 4))
        self.assertIn("鯊魚島補空檔", calls)

    def test_minimum_dwell_is_kept_when_tree_deadline_arrives(self):
        now = [0.0]
        with patch.object(cf, "choose_island", side_effect=["ice", None]), \
             patch.object(cf, "teleport"), \
             patch.object(cf, "leg", side_effect=lambda img, *args, **kw: img), \
             patch.object(cf.time, "time", side_effect=lambda: now[0]), \
             patch.object(cf.time, "perf_counter", side_effect=lambda: now[0]), \
             patch.object(cf, "_teleport_cooldown_ready", return_value=True):
            def dwell_gesture(*args, **kwargs):
                now[0] += 3.0
                return args[0]
            with patch.object(cf, "leg", side_effect=dwell_gesture):
                cf.run_island_filler(lambda _: None, 1.0)
        self.assertGreaterEqual(now[0], cf.ISLAND_MIN_DWELL)

    def test_tree_ready_while_cooldown_not_ready_uses_safe_gesture_then_returns(self):
        events = []
        now = [0.0]
        with patch.object(cf, "choose_island", side_effect=["ice", None]), \
             patch.object(cf, "teleport", side_effect=lambda area, rec: events.append(area)), \
             patch.object(cf, "leg", side_effect=lambda img, *args, **kw: events.append("gesture") or img), \
             patch.object(cf.time, "time", side_effect=lambda: 0.0), \
             patch.object(cf.time, "perf_counter", side_effect=[0.0] + [12.0] * 32), \
             patch.object(cf, "_teleport_cooldown_ready", side_effect=[False, True]):
            cf.run_island_filler(lambda _: None, 0.0)
        self.assertNotIn("village", events[:-1])
        self.assertEqual(events[-1], "village")

    def test_switches_after_minimum_dwell_when_tree_is_not_ready(self):
        teleports = []
        with patch.object(cf, "choose_island", side_effect=["ice", "shark", None]), \
             patch.object(cf, "teleport", side_effect=lambda area, rec: teleports.append(area)), \
             patch.object(cf, "leg", return_value=None), \
             patch.object(cf.time, "time", return_value=0.0), \
             patch.object(cf.time, "perf_counter", return_value=12.0):
            cf.run_island_filler(lambda _: None, 100.0)
        self.assertEqual(teleports, ["ice", "shark", "village"])

    def test_island_runtime_log_has_dwell_and_circle_fields(self):
        rows = []
        with patch.object(cf, "choose_island", side_effect=["ice", None]), \
             patch.object(cf, "teleport"), \
             patch.object(cf, "leg", return_value=None), \
             patch.object(cf.time, "time", return_value=105.0), \
             patch.object(cf.time, "perf_counter", return_value=32.0), \
             patch.object(cf, "_teleport_cooldown_ready", return_value=True):
            cf.run_island_filler(rows.append, 105.0)
        runtime = [r for r in rows if "dwell_s" in r]
        self.assertGreaterEqual(len(runtime), 1)
        self.assertIn("circle", runtime[0])

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
            # The mocked gesture crosses the deadline on its first completion.
            # This verifies the physical gesture is not split and the filler
            # returns cleanly without a route-duration estimate.
            def finish_after_gesture(*args, **kwargs):
                calls.append((args[1], args[2]))
                now[0] = 105.0
                return args[0]
            with patch.object(cf, "leg", side_effect=finish_after_gesture):
                cf.run_island_filler(lambda _: None, 105.0)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], cf.route_act(cf.ISLAND_ROUTES["ice"][0])[:2])


if __name__ == "__main__":
    unittest.main()
