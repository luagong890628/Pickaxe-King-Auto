"""執行時間與手動停止：模擬時鐘及手機操作，不觸碰 adb。"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cycle_fixed as cf


class TestRunControl(unittest.TestCase):
    def run_simulated(self, args):
        clock = [0.0]
        calls = []

        def teleport(area, rec):
            calls.append(area)
            if len(calls) == 5:
                raise KeyboardInterrupt
            clock[0] += 18000  # 每區模擬五小時，確認預設不受四小時限制

        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with (patch('sys.argv', ['cycle_fixed.py'] + args),
                      patch.object(cf.time, 'time', side_effect=lambda: clock[0]),
                      patch.object(cf, 'teleport', side_effect=teleport),
                      patch.object(cf, 'leg', return_value=None),
                      patch.object(cf, 'rest', return_value=None),
                      contextlib.redirect_stdout(io.StringIO())):
                    cf.main()
                rows = [json.loads(line) for line in
                        next(Path('captures').glob('*/log.jsonl')).read_text(encoding='utf-8').splitlines()]
            finally:
                os.chdir(cwd)
        return calls, rows

    def test_default_runs_until_keyboard_interrupt(self):
        calls, rows = self.run_simulated([])
        self.assertEqual(len(calls), 5)
        self.assertTrue(any(row.get('note') == '使用者停止（Ctrl+C）' for row in rows))
        self.assertEqual(rows[-1]['note'], '收工')

    def test_explicit_time_limit_stops_between_stations(self):
        # 時間到就在「站與站之間」停，不會把某一區走到一半丟著
        calls, rows = self.run_simulated(['--minutes', '1'])
        self.assertEqual(calls, ['village'])
        self.assertEqual(rows[-1]['站數'], 1)


if __name__ == '__main__':
    unittest.main()
