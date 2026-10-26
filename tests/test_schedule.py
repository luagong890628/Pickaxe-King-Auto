"""排程器：只去已刷新的地區，全部都在刷新就等最快好的那個。"""
import unittest

import cycle_fixed as cf


class NextStopTest(unittest.TestCase):
    def test_first_pass_visits_every_zone_once_in_order(self):
        # 都沒去過 → 依三個主區的宣告順序；島嶼只由 filler 明確選擇
        last = {}
        now = 1000.0
        got = []
        for _ in range(3):
            area, wait = cf.next_stop(now, last)
            self.assertEqual(wait, 0.0)
            got.append(area)
            last[area] = now
        self.assertEqual(got, ["village", "start", "farm"])

    def test_skips_zone_that_is_still_refreshing(self):
        # 小村莊、起始之地剛採完（還要等 50 秒），農場早就好了 → 只能去農場
        last = {"village": 950.0, "start": 950.0, "farm": 0.0}
        area, wait = cf.next_stop(1000.0, last)
        self.assertEqual(area, "farm")
        self.assertEqual(wait, 0.0)

    def test_never_visited_zone_outranks_a_visited_one(self):
        # 農場從沒去過，小村莊雖然已經超時很多，還是要先補農場
        last = {"village": 0.0, "start": 0.0}
        area, wait = cf.next_stop(5000.0, last)
        self.assertEqual(area, "farm")
        self.assertEqual(wait, 0.0)

    def test_does_not_immediately_revisit_the_same_zone(self):
        # 走完小村莊後，下一步不能又是小村莊（＝不會把其他區餓死）
        last = {"village": 1000.0, "start": 0.0, "farm": 0.0}
        area, _ = cf.next_stop(1001.0, last)
        self.assertNotEqual(area, "village")

    def test_waits_for_the_soonest_zone_when_all_are_refreshing(self):
        # 三區都剛採完：小村莊/起始之地 100 秒後好、農場 240 秒後好
        area, wait = cf.next_stop(10.0, {"village": 0.0, "start": 0.0, "farm": 0.0})
        self.assertIn(area, ("village", "start"))
        self.assertAlmostEqual(wait, cf.REFRESH[area] - 10.0)

    def test_village_anchor_cannot_bypass_village_refresh(self):
        area, wait = cf.next_stop(
            1099.0,
            {"village": 1000.0, "start": 1000.0, "farm": 0.0},
            village_first_cut=1000.0,
        )
        self.assertNotEqual(area, "village")
        self.assertEqual(wait, 0.0)

    def test_every_route_has_a_refresh_entry(self):
        # 加新場地時忘了在 REFRESH 登記 → 排程器永遠不會排它，這裡擋下來
        self.assertEqual(set(cf.REFRESH), set(cf.ROUTES))

    def test_refresh_values_match_the_game(self):
        self.assertEqual(cf.REFRESH["farm"], 240.0)     # 作物刷新 4 分鐘
        self.assertEqual(cf.REFRESH["village"], 100.0)  # 樹重生約 100 秒
        self.assertEqual(cf.REFRESH["start"], 100.0)
        # 珍珠不在 REFRESH：它附掛在小村莊，用 PEARL_COOLDOWN 另外控
        self.assertNotIn("pearl", cf.REFRESH)
        self.assertEqual(cf.PEARL_COOLDOWN, 600.0)


if __name__ == '__main__':
    unittest.main()
