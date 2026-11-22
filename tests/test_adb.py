"""以 Python 子程序替代 adb，驗證成功與失敗，不連手機。"""
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from pkauto import adb


def completed(returncode, stdout=b'', stderr=b''):
    return adb.subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@contextmanager
def patched_adb(run, env=None):
    """把 adb 執行換成測試用的 run(argv, **kwargs)，並跳過重試等待。"""
    with patch.dict(adb.os.environ, env or {}, clear=True):
        with patch.object(adb, 'adb_path', return_value='adb.exe'):
            with patch.object(adb.subprocess, 'run', side_effect=run):
                with patch.object(adb.time, 'sleep'):
                    yield


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
        with patch.dict(adb.os.environ, {'ANDROID_SERIAL': 'SERIAL'}, clear=False):
            with patch.object(adb, 'adb_path', return_value='adb.exe'):
                with patch.object(adb.subprocess, 'run', return_value=completed(0)) as run:
                    adb._run(['shell', 'input', 'tap', '1', '2'])
        self.assertEqual(
            run.call_args.args[0],
            ['adb.exe', '-s', 'SERIAL', 'shell', 'input', 'tap', '1', '2'],
        )


DEAD_DAEMON = (b'error: * daemon still not running\r\n'
               b'adb.exe: cannot connect to daemon at tcp:5037: '
               b'cannot connect to 127.0.0.1:5037 (10060)\r\n')
TAP = ['adb.exe', 'shell', 'input', 'tap', '1', '2']


class NotDeliveredDetectionTest(unittest.TestCase):
    """用實機 stderr 與 AOSP 原始碼位置驗證判斷，不靠推測。"""

    def test_not_delivered_errors_are_retryable(self):
        cases = [
            # 實測：kill-server 後的第一條指令，client 自己拉起 server、無線裝置沒接回
            b"* daemon not running; starting now at tcp:5037\r\n"
            b"* daemon started successfully\r\n"
            b"adb.exe: device '192.168.18.21:44643' not found\r\n",
            # 使用者 111 站崩潰時的原始 stderr
            b"error: * daemon still not running\r\n"
            b"adb.exe: cannot connect to daemon at tcp:5037: "
            b"cannot connect to 127.0.0.1:5037 (10060)\r\n",
            # 無線 transport 掉了，但 server 還活著
            b"adb.exe: device '192.168.18.21:44643' not found\r\n",
            # transport.cpp acquire_one_transport()：選 transport 階段就拒絕，指令沒轉送
            b"error: device offline\r\n",
            b"error: device offline (no transport)\r\n",
            b"error: device offline (transport offline)\r\n",
            b"error: device still connecting\r\n",
            b"error: device still authorizing\r\n",
        ]
        for stderr in cases:
            self.assertTrue(adb._not_delivered(stderr), stderr)

    def test_delivered_errors_are_not_retryable(self):
        cases = [
            b"sh: socat: not found\r\n",   # 手機上指令自己噴的，代表指令已送達
            b"error: closed\r\n",          # 轉送後中途斷線，手勢可能已執行
            b"",
        ]
        for stderr in cases:
            self.assertFalse(adb._not_delivered(stderr), stderr)


class AdbRecoveryTest(unittest.TestCase):
    """指令沒送到手機時重開 server 再重送；已送達的失敗一律不重試。"""

    def test_daemon_gone_restarts_server_and_retries_command(self):
        calls = []
        queue = [completed(1, stderr=DEAD_DAEMON), completed(0), completed(0),
                 completed(0, stdout=b'ok')]

        def run(argv, **_kwargs):
            calls.append(argv)
            return queue.pop(0)

        with patched_adb(run):
            result = adb._run(['shell', 'input', 'tap', '1', '2'])
        self.assertEqual(calls, [TAP, ['adb.exe', 'kill-server'],
                                 ['adb.exe', 'start-server'], TAP])
        self.assertEqual(result.stdout, b'ok')

    def test_restart_reconnects_wireless_transport(self):
        calls = []
        queue = [completed(1, stderr=DEAD_DAEMON), completed(0), completed(0),
                 completed(0), completed(0, stdout=b'ok')]

        def run(argv, **_kwargs):
            calls.append(argv)
            return queue.pop(0)

        with patched_adb(run, {'ANDROID_SERIAL': '192.168.18.21:36545'}):
            adb._run(['shell', 'input', 'tap', '1', '2'])
        self.assertIn(['adb.exe', 'connect', '192.168.18.21:36545'], calls)
        self.assertEqual(calls[-1],
                         ['adb.exe', '-s', '192.168.18.21:36545',
                          'shell', 'input', 'tap', '1', '2'])

    def test_stalled_command_restarts_server_and_retries(self):
        calls = []
        stalled = {'done': False}

        def run(argv, **kwargs):
            calls.append(argv)
            if argv[-1] in ('kill-server', 'start-server'):
                return completed(0)
            if not stalled['done']:
                stalled['done'] = True
                raise adb.subprocess.TimeoutExpired(argv, kwargs['timeout'])
            return completed(0, stdout=b'ok')

        with patched_adb(run):
            result = adb._run(['shell', 'input', 'tap', '1', '2'])
        self.assertEqual(result.stdout, b'ok')
        self.assertEqual(calls, [TAP, ['adb.exe', 'kill-server'],
                                 ['adb.exe', 'start-server'], TAP])

    def test_device_offline_is_retried_because_nothing_was_delivered(self):
        calls = []
        swipe = ['adb.exe', 'shell', 'input', 'swipe', '1', '2', '3', '4', '300']
        queue = [completed(1, stderr=b'error: device offline'), completed(0),
                 completed(0), completed(0, stdout=b'ok')]

        def run(argv, **_kwargs):
            calls.append(argv)
            return queue.pop(0)

        with patched_adb(run):
            result = adb._run(['shell', 'input', 'swipe', '1', '2', '3', '4', '300'])
        self.assertEqual(result.stdout, b'ok')
        self.assertEqual(calls, [swipe, ['adb.exe', 'kill-server'],
                                 ['adb.exe', 'start-server'], swipe])

    def test_delivered_failure_is_never_retried(self):
        calls = []

        def run(argv, **_kwargs):
            calls.append(argv)
            return completed(1, stderr=b'sh: socat: not found')

        with patched_adb(run):
            with self.assertRaisesRegex(RuntimeError, 'socat'):
                adb._run(['shell', 'socat'])
        self.assertEqual(len(calls), 1)

    def test_restart_server_survives_hung_adb(self):
        calls = []

        def run(argv, **_kwargs):
            calls.append(argv)
            raise adb.subprocess.TimeoutExpired(argv, 30)

        with patched_adb(run, {'ANDROID_SERIAL': '192.168.18.21:36545'}):
            adb.restart_server()  # 不應拋出，交給 _run 的重試上限回報
        self.assertEqual([call[1] for call in calls],
                         ['kill-server', 'start-server', 'connect'])

    def test_daemon_error_gives_up_after_bounded_restarts(self):
        def run(argv, **_kwargs):
            if argv[-1] in ('kill-server', 'start-server'):
                return completed(0)
            return completed(1, stderr=DEAD_DAEMON)

        with patched_adb(run):
            with self.assertRaisesRegex(RuntimeError, '已重啟 adb server 3 次'):
                adb._run(['shell', 'input', 'tap', '1', '2'])

    def test_timeout_gives_up_with_clear_reason(self):
        def run(argv, **kwargs):
            if argv[-1] in ('kill-server', 'start-server'):
                return completed(0)
            raise adb.subprocess.TimeoutExpired(argv, kwargs['timeout'])

        with patched_adb(run):
            with self.assertRaisesRegex(RuntimeError, '逾時.*3 次仍失敗'):
                adb._run(['shell', 'input', 'tap', '1', '2'])


class AdbPathTest(unittest.TestCase):
    def test_adb_path_honours_override(self):
        with patch.dict(adb.os.environ, {}, clear=True):
            self.assertEqual(adb.adb_path(), adb.DEFAULT_ADB)
        with patch.dict(adb.os.environ, {'PKAUTO_ADB': 'X:/adb.exe'}, clear=True):
            self.assertEqual(adb.adb_path(), 'X:/adb.exe')


if __name__ == '__main__':
    unittest.main()
