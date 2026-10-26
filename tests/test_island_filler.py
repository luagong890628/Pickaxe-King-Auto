import contextlib
import io
import unittest
from unittest.mock import patch

import cycle_fixed as cf


class IslandFillerContractTest(unittest.TestCase):
    def test_weights_and_unused_candidates(self):
        self.assertEqual(cf.ISLAND_WEIGHTS, {"ice": 30, "shark": 25, "duck": 25, "truffle": 20})
        self.assertEqual(cf.eligible_islands(set()), list(cf.ISLANDS))
        self.assertEqual(cf.eligible_islands({"ice", "duck"}), ["shark", "truffle"])

    def test_weighted_choice_uses_only_unused_candidates(self):
        with patch.object(cf.random, "choices", return_value=["shark"]) as choices:
            self.assertEqual(cf.choose_island(set()), "shark")
        choices.assert_called_once_with(["ice", "shark", "duck", "truffle"], weights=[30, 25, 25, 20], k=1)

    def test_island_route_entry_once_then_four_laps(self):
        actions = list(cf.island_actions("shark"))
        self.assertEqual(actions[:2], cf.ISLAND_ROUTES["shark"][:2])
        self.assertEqual(actions[2:], cf.ISLAND_ROUTES["shark"][2:] * 4)

    def test_return_boundary_does_not_split_physical_gesture(self):
        self.assertTrue(cf.should_return_after_gesture(104.0, 105.0, 2.0))
        self.assertFalse(cf.should_return_after_gesture(104.0, 105.0, 0.5))

    def test_main_cycles_one_is_primary_three_only(self):
        self.assertEqual(cf.primary_cycle_limit(1), 3)

    def test_filler_runs_full_laps_without_adb_and_stops_at_boundary(self):
        calls = []
        clock = iter([0.0] * 19 + [104.0])

        def fake_leg(img, d, px, rec, label, **kwargs):
            calls.append((d, px))
            return img

        with (patch.object(cf, "choose_island", return_value="ice"),
              patch.object(cf, "teleport"),
              patch.object(cf, "leg", side_effect=fake_leg),
              patch.object(cf.time, "time", side_effect=lambda: next(clock))):
            used = set()
            cf.run_island_filler(lambda _: None, 105.0, used)

        self.assertEqual(used, {"ice"})
        self.assertEqual(len(calls), 2 + 4 * 4)
        self.assertEqual(calls[:2], [cf.route_act(a)[:2] for a in cf.ISLAND_ROUTES["ice"][:2]])


if __name__ == "__main__":
    unittest.main()
