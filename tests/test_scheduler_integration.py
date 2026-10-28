import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cycle_fixed as cf


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class SchedulerIntegrationTest(unittest.TestCase):
    def run_main(self, minutes, run_area, filler):
        clock = FakeClock()
        stations = []

        def area(area, rec, no_pearl=False):
            stations.append((area, clock.now))
            return run_area(area, rec, no_pearl, clock)

        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with (patch('sys.argv', ['cycle_fixed.py', '--minutes', str(minutes)]),
                      patch.object(cf.time, 'time', side_effect=clock.time),
                      patch.object(cf.time, 'sleep', side_effect=clock.sleep),
                      patch.object(cf, 'run_area', side_effect=area),
                      patch.object(cf, 'run_island_filler', side_effect=filler(clock)),
                      contextlib.redirect_stdout(io.StringIO())):
                    cf.main()
                log_path = next(Path('captures').glob('*/log.jsonl'))
                rows = [json.loads(line) for line in log_path.read_text(encoding='utf-8').splitlines()]
            finally:
                os.chdir(cwd)
        return clock, stations, rows

    def test_village_first_cut_anchor_enforces_105_seconds_with_pearl_skip(self):
        def run_area(area, rec, no_pearl, clock):
            # village first-cut is at station start + 5s; other work is short.
            clock.now += 5.0 if area == 'village' else 10.0
            return (clock.now if area == 'village' else None), None

        def filler(clock):
            def fill(rec, deadline, no_pearl=False):
                clock.sleep(20.0)
                return False
            return fill

        clock, stations, _ = self.run_main(2.2, run_area, filler)
        villages = [t for a, t in stations if a == 'village']
        self.assertGreaterEqual(len(villages), 2)
        self.assertGreaterEqual(villages[1] - (villages[0] + 5.0), 105.0)
        self.assertEqual([a for a, _ in stations[:3]], ['village', 'start', 'farm'])
        self.assertGreaterEqual(clock.sleeps.count(20.0), 1)

    def test_farm_is_not_repeated_before_240_but_runs_when_available(self):
        def run_area(area, rec, no_pearl, clock):
            clock.now += 10.0
            return (clock.now if area == 'village' else None), None

        def filler(clock):
            def fill(rec, deadline, no_pearl=False):
                clock.sleep(min(30.0, max(0.1, deadline - clock.now)))
                return False
            return fill

        _, stations, _ = self.run_main(6.0, run_area, filler)
        farms = [t for a, t in stations if a == 'farm']
        self.assertGreaterEqual(len(farms), 2)
        self.assertGreaterEqual(farms[1] - farms[0], 240.0)

    def test_no_filler_available_sleeps_instead_of_spinning(self):
        def run_area(area, rec, no_pearl, clock):
            clock.now += 10.0
            return (clock.now if area == 'village' else None), None

        def filler(clock):
            def fill(rec, deadline, no_pearl=False):
                return False
            return fill

        clock, stations, _ = self.run_main(1.9, run_area, filler)
        self.assertLess(len(stations), 5)
        self.assertTrue(any(seconds > 0 for seconds in clock.sleeps))
        self.assertLess(len(clock.sleeps), 100)

    def real_main_events(self, minutes):
        clock = FakeClock()
        clock.now = 100.0
        events = []

        def tap(x, y):
            events.append(('tap', (x, y), clock.now))

        def swipe(*args):
            events.append(('swipe', args, clock.now))
            clock.now += args[-1] / 1000

        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with (patch('sys.argv', ['cycle_fixed.py', '--minutes', str(minutes), '--no-pearl']),
                      patch.object(cf, '_last_teleport', 0.0),
                      patch.object(cf.time, 'time', side_effect=clock.time),
                      patch.object(cf.time, 'perf_counter', side_effect=clock.time),
                      patch.object(cf.time, 'sleep', side_effect=clock.sleep),
                      patch.object(cf.adb, 'tap', side_effect=tap),
                      patch.object(cf.adb, 'swipe', side_effect=swipe),
                      patch.object(cf.adb, 'screencap', side_effect=AssertionError('no phone')),
                      patch.object(cf.random, 'choices', side_effect=lambda items, weights, k: [items[0]]),
                      contextlib.redirect_stdout(io.StringIO())):
                    cf.main()
            finally:
                os.chdir(cwd)
        return clock, events

    def test_real_main_minutes_expiry_on_island_stops_without_village_transfer(self):
        clock, events = self.real_main_events(1.5)
        transfers = [(point, at) for kind, point, at in events if kind == 'tap' and point in cf.TILE.values()]
        self.assertGreaterEqual(clock.now, 190.0)
        self.assertLess(clock.now, 210.0)
        self.assertEqual(sum(point == cf.TILE['village'] for point, _ in transfers), 1)
        self.assertIn(transfers[-1][0], [cf.TILE[a] for a in cf.ISLANDS])
        movement = [args for kind, args, _ in events if kind == 'swipe' and args[:2] == cf.DRAG]
        self.assertEqual(movement[-1][2:4], (420, 2600))  # ice loop's last west gesture

    def test_real_main_filler_and_run_area_have_one_village_transfer(self):
        clock, events = self.real_main_events(2.3)
        transfers = [point for kind, point, _ in events if kind == 'tap' and point in cf.TILE.values()]
        village = cf.TILE['village']
        self.assertIn(cf.TILE['ice'], transfers)
        self.assertEqual(transfers.count(village), 2)  # initial village + exactly one return
        self.assertFalse(any(a == b == village for a, b in zip(transfers, transfers[1:])))
        self.assertFalse(any(s > 1 for s in clock.sleeps if s != cf.REST_WAIT))

    def test_real_filler_path_switches_without_immediate_repeats(self):
        clock = FakeClock()
        teleports = []
        legs = []

        def fake_teleport(area, rec):
            teleports.append(area)
            clock.now += cf.TELEPORT_WAIT * 3

        def fake_leg(img, direction, px, rec, label, **kwargs):
            legs.append(label)
            clock.now += 1.0
            return img

        perf_now = [0.0]
        def fake_perf_counter():
            value = perf_now[0]
            perf_now[0] += 13.0
            return value

        with (patch.object(cf.time, 'time', side_effect=clock.time),
              patch.object(cf.time, 'sleep', side_effect=clock.sleep),
              patch.object(cf.time, 'perf_counter', side_effect=fake_perf_counter),
              patch.object(cf, 'teleport', side_effect=fake_teleport),
              patch.object(cf, 'leg', side_effect=fake_leg),
              patch.object(cf.random, 'choices', side_effect=lambda items, weights, k: [items[0]])):
            worked = cf.run_island_filler(lambda _: None, 100.0)

        self.assertTrue(worked)
        islands = [a for a in teleports if a in cf.ISLANDS]
        self.assertGreaterEqual(len(islands), 2)
        self.assertTrue(all(a != b for a, b in zip(islands, islands[1:])))
        self.assertNotIn('village', teleports)
        self.assertGreaterEqual(len(legs), 2 * 6)


if __name__ == '__main__':
    unittest.main()
