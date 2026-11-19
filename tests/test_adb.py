"""以 Python 子程序替代 adb，驗證成功與失敗，不連手機。"""
import sys
import unittest
from unittest.mock import patch

from pkauto import adb


class AdbCommandTest(unittest.TestCase):
    def test_nonzero_exit_reports_stderr(self):
        with patch.object(adb, 'adb_path', return_value=sys.executable):
            with self.assertRaisesRegex(RuntimeError, 'device offline'):
                adb._run(['-c', "import sys; sys.stderr.write('device offline'); sys.exit(1)"])

    def test_success_preserves_binary_output(self):
        with patch.object(adb, 'adb_path', return_value=sys.executable):
            result = adb._run(['-c', "import sys; sys.stdout.buffer.write(b'\\x00\\xff')"])
        self.assertEqual(result.stdout, b'\x00\xff')

    def test_command_pins_selected_transport(self):
        with patch.dict(adb.os.environ, {'ANDROID_SERIAL': '192.168.18.21:36545'}, clear=False):
            with patch.object(adb, 'adb_path', return_value='adb.exe'):
                self.assertEqual(
                    adb._command(['shell', 'input', 'tap', '1', '2']),
                    ['adb.exe', '-s', '192.168.18.21:36545',
                     'shell', 'input', 'tap', '1', '2'],
                )

    def test_command_without_selected_transport_preserves_legacy_shape(self):
        with patch.dict(adb.os.environ, {}, clear=True):
            with patch.object(adb, 'adb_path', return_value='adb.exe'):
                self.assertEqual(
                    adb._command(['devices']),
                    ['adb.exe', 'devices'],
                )

    def test_run_uses_selected_transport(self):
        completed = adb.subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b'', stderr=b''
        )
        with patch.dict(adb.os.environ, {'ANDROID_SERIAL': 'SERIAL'}, clear=False):
            with patch.object(adb, 'adb_path', return_value='adb.exe'):
                with patch.object(adb.subprocess, 'run', return_value=completed) as run:
                    adb._run(['shell', 'input', 'tap', '1', '2'])
        self.assertEqual(
            run.call_args.args[0],
            ['adb.exe', '-s', 'SERIAL', 'shell', 'input', 'tap', '1', '2'],
        )


if __name__ == '__main__':
    unittest.main()
