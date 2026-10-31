"""工具回歸測試：替代手機輸入、截圖與等待，不碰實機或資料檔。"""
import contextlib
import io
import unittest
from unittest.mock import patch

import cycle_fixed as cf
import drift_test
import run_leg


class RouteToolsTest(unittest.TestCase):
    def _run_leg_sleeps(self, argv_tail):
        """跑 run_leg，回傳所有非 0 的 sleep 秒數。"""
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('sys.argv', ['run_leg.py'] + argv_tail))
            stack.enter_context(patch.object(cf, 'MEASURE', False))
            stack.enter_context(patch.object(cf, 'MEASURE_TEMPLATE', False))
            stack.enter_context(patch.object(cf.adb, 'current_app', return_value='pickaxeking'))
            stack.enter_context(patch.object(cf.adb, 'swipe'))
            stack.enter_context(patch.object(cf, 'shot', side_effect=AssertionError('不應截圖')))
            wait = stack.enter_context(patch.object(cf.time, 'sleep'))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.assertEqual(run_leg.main(), 0)
            return [c.args[0] for c in wait.call_args_list if c.args and c.args[0]]

    def test_run_leg_fill_walks_the_padding_pairs(self):
        # 農場的補時來回不在 ROUTES 裡，--fill 才會走（等同正式程式的 fill_cycle）
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('sys.argv', ['run_leg.py', 'farm', '1', '2', '3', '4',
                                                   '--no-teleport', '--no-measure', '--fill']))
            stack.enter_context(patch.object(cf, 'MEASURE', False))
            stack.enter_context(patch.object(cf.adb, 'current_app', return_value='pickaxeking'))
            stack.enter_context(patch.object(cf.adb, 'swipe'))
            stack.enter_context(patch.object(cf, 'shot', return_value=None))
            stack.enter_context(patch.object(cf.time, 'sleep'))
            fill = stack.enter_context(patch.object(cf, 'fill_cycle', return_value=None))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.assertEqual(run_leg.main(), 0)
            fill.assert_called_once()
            self.assertEqual(fill.call_args.args[0], 'farm')

    def test_run_leg_without_settle_follows_route_setting(self):
        # 沒給 --settle 時要照 SETTLE_LEGS：目前只有第 3 段停 0.5 秒（補漏砍）
        self.assertEqual(cf.route_settle('village', 3), 0.5)
        self.assertEqual(
            self._run_leg_sleeps(['village', '1', '2', '3', '--no-teleport', '--no-measure']),
            [0.5])

    def test_run_leg_honours_configured_dwell(self):
        # 把第 3 段設成要停 0.5，不給 --settle 時就只停那一次
        with patch.dict(cf.SETTLE_LEGS['village'], {3: 0.5}, clear=True):
            self.assertEqual(
                self._run_leg_sleeps(['village', '1', '2', '3', '--no-teleport', '--no-measure']),
                [0.5])

    def test_run_leg_explicit_settle_overrides_route(self):
        # 給了 --settle 就每一段都停該值（量速度時想固定條件才用）
        self.assertEqual(
            self._run_leg_sleeps(['village', '1', '2', '3', '--no-teleport',
                                  '--no-measure', '--settle', '1']),
            [1.0, 1.0, 1.0])

    def test_run_leg_waits_only_requested_settle(self):
        for settle in ('0', '1', '5'):
            with self.subTest(settle=settle), contextlib.ExitStack() as stack:
                stack.enter_context(patch('sys.argv', ['run_leg.py', 'village', '1', '2',
                    '--no-teleport', '--no-measure', '--settle', settle, '--settle-first', '.5']))
                stack.enter_context(patch.object(cf, 'MEASURE', False))
                stack.enter_context(patch.object(cf, 'MEASURE_TEMPLATE', False))
                stack.enter_context(patch.object(cf.adb, 'current_app', return_value='pickaxeking'))
                stack.enter_context(patch.object(cf.adb, 'swipe'))
                stack.enter_context(patch.object(cf, 'shot', side_effect=AssertionError('不應截圖')))
                wait = stack.enter_context(patch.object(cf.time, 'sleep'))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                self.assertEqual(run_leg.main(), 0)
                self.assertEqual([c.args[0] for c in wait.call_args_list],
                                 [.5] + ([float(settle)] if float(settle) else []))

    def test_drift_waits_only_requested_settle(self):
        with (patch('sys.argv', ['drift_test.py', '--runs', '1', '--settle', '0', '--settle-first', '.5']),
              patch.object(cf, 'ROUTES', {'village': [('N', 100), ('REST',), ('L', 100)]}),
              patch.object(cf, 'MEASURE', False),
              patch.object(cf, 'teleport'), patch.object(cf.adb, 'swipe'),
              patch.object(cf.adb, 'tap'), patch.object(cf, 'shot', return_value='image'),
              patch.object(cf.time, 'sleep') as wait,
              patch.object(cf.measure, 'world_shift', return_value=(0, 0, 1, 'template')),
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(drift_test.main(), 0)
        self.assertEqual([c.args[0] for c in wait.call_args_list], [2.5, .5, cf.REST_WAIT, 0, 1.2])

    def test_run_leg_reuses_measurement_for_logging(self):
        for template in (False, True):
            with self.subTest(template=template), contextlib.ExitStack() as stack:
                argv = ['run_leg.py', 'village', '2', '--no-teleport']
                if template:
                    argv.append('--template')
                stack.enter_context(patch('sys.argv', argv))
                stack.enter_context(patch.object(cf, 'MEASURE', False))
                stack.enter_context(patch.object(cf, 'MEASURE_TEMPLATE', False))
                stack.enter_context(patch.object(cf.adb, 'current_app', return_value='pickaxeking'))
                stack.enter_context(patch.object(cf.adb, 'swipe'))
                stack.enter_context(patch.object(cf.time, 'sleep'))
                stack.enter_context(patch.object(cf, 'shot', side_effect=['before', 'after']))
                world = stack.enter_context(patch.object(cf.measure, 'world_shift', return_value=(-40, 0, .95, 'scroll')))
                tpl = stack.enter_context(patch.object(cf.vision, 'shift_by_template', return_value=(40, 0, .99, 4)))
                log = stack.enter_context(patch.object(run_leg, 'log_walk'))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                self.assertEqual(run_leg.main(), 0)
                self.assertEqual(world.call_count, 0 if template else 1)
                self.assertEqual(tpl.call_count, 1 if template else 0)
                row = log.call_args.args[0]
                self.assertEqual(row['measured'], [-40, 0])
                self.assertEqual(row['source'], 'template' if template else 'scroll')
                self.assertEqual(row['score'], .99 if template else .95)

    def test_long_leg_reuses_single_measurement(self):
        rows = []
        with (patch.object(cf, 'MEASURE', True),
              patch.object(cf, 'MEASURE_TEMPLATE', False),
              patch.object(cf.adb, 'swipe') as swipe,
              patch.object(cf.time, 'sleep'),
              patch.object(cf, 'shot', return_value='after'),
              patch.object(cf.measure, 'world_shift', return_value=(-1499, 0, .95, 'template')) as world):
            self.assertEqual(cf.leg('before', 'L', 1500, rows.append, 'test'), 'after')
        self.assertEqual(swipe.call_count, 1)
        self.assertEqual(world.call_count, 1)
        self.assertEqual(rows[0]['shift'], [1499, 0])
        self.assertEqual(rows[0]['score'], .95)
        self.assertEqual(rows[0]['source'], 'template')

    def test_missing_measurement_does_not_claim_valid_metadata(self):
        rows = []
        with (patch.object(cf, 'MEASURE', True),
              patch.object(cf, 'MEASURE_TEMPLATE', False),
              patch.object(cf.adb, 'swipe'), patch.object(cf.time, 'sleep'),
              patch.object(cf, 'shot', return_value='after'),
              patch.object(cf.measure, 'world_shift', return_value=None)):
            cf.leg('before', 'L', 100, rows.append, 'test')
        self.assertNotIn('source', rows[0])
        self.assertNotIn('score', rows[0])

    def test_template_shift_is_picture_displacement(self):
        rows = []
        with (patch.object(cf, 'MEASURE', True),
              patch.object(cf, 'MEASURE_TEMPLATE', True),
              patch.object(cf.adb, 'swipe'),
              patch.object(cf.time, 'sleep'),
              patch.object(cf, 'shot', return_value='after'),
              patch.object(cf.vision, 'shift_by_template', return_value=(40, 0, .99, 4))):
            cf.leg('before', 'L', 40, rows.append, 'test')
        self.assertEqual(rows[0]['shift'], [40, 0])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run_leg.rec_plain(rows[0])
        self.assertIn('實走 (-40,+0)', out.getvalue())


if __name__ == '__main__':
    unittest.main()
