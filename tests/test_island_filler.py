import itertools
import unittest
from unittest.mock import patch

import cycle_fixed as cf


class IslandFillerContractTest(unittest.TestCase):
    def test_fixed_order_round_robin(self):
        """固定順序：冰雪 → 鯊魚 → 鴨子 → 松露 → 冰雪…（排除剛離開的那座）。"""
        self.assertEqual(cf.choose_island(), "ice")
        self.assertEqual(cf.choose_island({"ice"}), "shark")
        self.assertEqual(cf.choose_island({"shark"}), "duck")
        self.assertEqual(cf.choose_island({"duck"}), "truffle")
        self.assertEqual(cf.choose_island({"truffle"}), "ice")     # 繞回第一座

    def test_selection_ignores_respawn_time(self):
        """不把重生時間寫成門檻：就算剛剛才去過，下一座照樣是固定順序的下一座。"""
        self.assertEqual(cf.REFRESH["ice"], 0.0)
        self.assertEqual(cf.choose_island({"ice"}), "shark")
        self.assertEqual(cf.choose_island({"ice", "shark"}), "duck")

    def test_skips_islands_without_route(self):
        with patch.dict(cf.ROUTES, {"duck": []}, clear=False):
            self.assertEqual(cf.choose_island({"shark"}), "truffle")
            self.assertEqual(cf.choose_island({"truffle"}), "ice")

    def test_returns_none_when_no_island_has_route(self):
        empty = {a: [] for a in cf.ISLANDS}
        with patch.dict(cf.ROUTES, empty, clear=False):
            self.assertIsNone(cf.choose_island())
            self.assertIsNone(cf.choose_island({"ice"}))

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
        self.assertEqual(cf.choose_island({"ice"}), "shark")

    def test_farm_fill_pairs_is_not_shortened_by_deadline(self):
        self.assertEqual(cf.FILL_PAIRS, 6)

    def test_farm_fill_executes_all_six_pairs(self):
        calls = []
        with patch.object(cf, "leg", side_effect=lambda img, d, px, rec, label, **kw:
                          calls.append((d, px)) or img):
            cf.fill_cycle("farm", lambda _: None, None)
        self.assertEqual(calls, [("R", 700.0), ("L", 700.0)] * 6)

    def exercise_filler(self, seconds, deadline, choices, cooldown=lambda: True,
                        visited=None):
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
            worked = cf.run_island_filler(rows.append, deadline, visited)
        return moves, transfers, rows, choose, worked

    def test_few_seconds_left_switches_at_minimum_and_new_island_keeps_minimum(self):
        moves, transfers, rows, choose, worked = self.exercise_filler(
            3.0, 121.0, ['ice', 'shark'])
        self.assertTrue(worked)
        self.assertEqual(transfers[:2], [('ice', 100.0), ('shark', 118.0)])
        self.assertEqual([r['gesture'] for r in rows if r.get('decision') == 'switch'], [6])
        self.assertGreaterEqual(len([m for m in moves if m[0] == '鯊魚島補空檔']), 6)
        self.assertEqual(len(choose.call_args_list), 2)   # 起點一次、換島一次
        # 註：mock 記的是同一個 set 的參考，事後看內容一定是累積後的，故只驗次數。

    def test_cooldown_unready_continues_complete_loops_without_menu_or_sleep(self):
        checks = iter([False, False, True])
        with patch.object(cf.time, 'sleep', side_effect=AssertionError('stationary wait')):
            moves, transfers, rows, _, _ = self.exercise_filler(
                0.5, 101.0, ['ice', None], cooldown=lambda: next(checks))
        self.assertEqual([a for a, _ in transfers], ['ice'])
        self.assertEqual(len(moves), 26)  # entry 2 + six full loops; teleport() owns cooldown
        self.assertEqual(rows[-1]['decision'], 'return')

    def test_switch_waits_for_cooldown_by_walking_more_loops(self):
        checks = iter([False, False, True, True])
        moves, transfers, _, _, _ = self.exercise_filler(
            3.0, 145.0, ['ice', 'shark', None], cooldown=lambda: next(checks, True))
        self.assertEqual(transfers[:2], [('ice', 100.0), ('shark', 118.0)])
        self.assertEqual(len([m for m in moves if m[0] == '冰雪魔像島補空檔']), 6)

    def test_minimum_dwell_and_log_use_complete_loop_boundary(self):
        moves, transfers, rows, _, _ = self.exercise_filler(1.0, 101.0, ['ice'])
        self.assertEqual(len(moves), 14)  # 2 entry + 3 complete loops, 14s dwell
        self.assertEqual([a for a, _ in transfers], ['ice'])
        runtime = [r for r in rows if 'dwell_s' in r]
        self.assertEqual(runtime[-1]['dwell_s'], 14.0)
        self.assertEqual(runtime[-1]['circle'], 3)

    def test_all_islands_used_up_returns_without_reentry(self):
        """四座都逛過（choose_island 回 None）→ 直接回主區，不再原地重複繞。"""
        moves, transfers, rows, _, worked = self.exercise_filler(3.0, 200.0, ['ice', None])
        self.assertTrue(worked)
        self.assertEqual(transfers, [('ice', 100.0)])
        self.assertEqual(len(moves), 6)  # 3s/手勢 → 第 6 個手勢（2 進場+1 圈）就滿 12 秒
        self.assertEqual(rows[-1]['decision'], 'return')

    def test_one_trip_per_island_per_window(self):
        """同一個窗口內每座島只去一次：逛完四座就回主區（實測一趟約 15 秒）。"""
        now = [100.0]
        transfers = []
        visited = set()

        def move(img, d, px, rec, label, **kw):
            now[0] += 3.0
            return img

        with (patch.object(cf, 'teleport', side_effect=lambda area, rec: transfers.append(area)),
              patch.object(cf, 'leg', side_effect=move),
              patch.object(cf, '_teleport_cooldown_ready', return_value=True),
              patch.object(cf.time, 'time', side_effect=lambda: now[0]),
              patch.object(cf.time, 'perf_counter', side_effect=lambda: now[0])):
            worked = cf.run_island_filler(lambda _: None, 1000.0, visited)
            again = cf.run_island_filler(lambda _: None, 1000.0, visited)

        self.assertTrue(worked)
        self.assertEqual(transfers, list(cf.ISLANDS))     # 固定順序、四座各一次
        self.assertEqual(visited, set(cf.ISLANDS))
        self.assertFalse(again)                            # 同一個窗口再問就沒島可去
        self.assertEqual(transfers, list(cf.ISLANDS))      # 不會再傳送

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
