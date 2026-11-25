"""以 Python 子程序替代 adb，驗證成功與失敗，不連手機。"""
import itertools
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
    """沒送到手機就重試：daemon 問題重開 server，裝置暫態只等待重送；已送達的失敗不重試。"""

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

    def test_first_timeout_retries_without_killing_server(self):
        """逾時代表 connect 成功、指令已送到 server：先只重送，別毀掉 traced server。"""
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if len(calls) == 1:
                raise adb.subprocess.TimeoutExpired(argv, kwargs['timeout'])
            return completed(0, stdout=b'ok')

        with patched_adb(run):
            result = adb._run(['shell', 'input', 'tap', '1', '2'])
        self.assertEqual(result.stdout, b'ok')
        self.assertEqual(calls, [TAP, TAP])

    def test_timeout_restarts_server_when_it_repeats(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if argv[-1] in ('kill-server', 'start-server'):
                return completed(0)
            if len(calls) <= 2:
                raise adb.subprocess.TimeoutExpired(argv, kwargs['timeout'])
            return completed(0, stdout=b'ok')

        with patched_adb(run):
            result = adb._run(['shell', 'input', 'tap', '1', '2'])
        self.assertEqual(result.stdout, b'ok')
        self.assertEqual(calls, [TAP, TAP, ['adb.exe', 'kill-server'],
                                 ['adb.exe', 'start-server'], TAP])

    def test_device_offline_retries_without_killing_server(self):
        """裝置暫態：mDNS 會自己重連，不該砍掉整個 server。"""
        calls = []
        swipe = ['adb.exe', 'shell', 'input', 'swipe', '1', '2', '3', '4', '300']
        queue = [completed(1, stderr=b'error: device offline'), completed(0, stdout=b'ok')]

        def run(argv, **_kwargs):
            calls.append(argv)
            return queue.pop(0)

        with patched_adb(run):
            result = adb._run(['shell', 'input', 'swipe', '1', '2', '3', '4', '300'])
        self.assertEqual(result.stdout, b'ok')
        self.assertEqual(calls, [swipe, swipe])

    def test_device_offline_with_ip_port_only_reconnects(self):
        calls = []
        queue = [completed(1, stderr=b'error: device offline'), completed(0),
                 completed(0, stdout=b'ok')]

        def run(argv, **_kwargs):
            calls.append(argv)
            return queue.pop(0)

        with patched_adb(run, {'ANDROID_SERIAL': '192.168.18.21:41951'}):
            adb._run(['shell', 'echo', 'ok'])
        self.assertIn(['adb.exe', 'connect', '192.168.18.21:41951'], calls)
        self.assertNotIn(['adb.exe', 'kill-server'], calls)

    def test_device_offline_with_mdns_name_does_not_connect(self):
        """mDNS 名稱由 adb 自動重連，補 connect 反而多餘。"""
        calls = []
        queue = [completed(1, stderr=b'error: device offline'), completed(0, stdout=b'ok')]

        def run(argv, **_kwargs):
            calls.append(argv)
            return queue.pop(0)

        with patched_adb(run, {'ANDROID_SERIAL': 'adb-R5GL15085ZJ-QZEuM7._adb-tls-connect._tcp'}):
            adb._run(['shell', 'echo', 'ok'])
        self.assertEqual(len(calls), 2)
        self.assertFalse(any(c[1] in ('connect', 'kill-server') for c in calls))

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
            with self.assertRaisesRegex(RuntimeError, '已重試 3 次、重啟 server 3 次'):
                adb._run(['shell', 'input', 'tap', '1', '2'])

    def test_timeout_gives_up_with_clear_reason(self):
        def run(argv, **kwargs):
            if argv[-1] in ('kill-server', 'start-server'):
                return completed(0)
            raise adb.subprocess.TimeoutExpired(argv, kwargs['timeout'])

        with patched_adb(run):
            # 4 次逾時、第 1 次用掉寬限 → 只重開 2 次
            with self.assertRaisesRegex(RuntimeError, '逾時.*已重試 3 次、重啟 server 2 次仍失敗'):
                adb._run(['shell', 'input', 'tap', '1', '2'])


LOOPBACK_TIMEOUT = (b'adb.exe: cannot connect to daemon at tcp:5037: '
                    b'cannot connect to 127.0.0.1:5037 (10060)\r\n')


class LoopbackStallTest(unittest.TestCase):
    """2026-11-26 整晚 4 次 21.07 秒／10060 是本機 loopback connect 被丟包，server 全程活著。

    舊行為一律 kill-server：毀掉 traced server（trace 停 4.5 小時），
    並把別的 client 在途的指令打成 rc=255／空 stderr。指令逾時走同一條寬限。
    """

    def test_only_local_connect_timeout_counts(self):
        self.assertTrue(adb._loopback_stalled(LOOPBACK_TIMEOUT))
        # client 連 spawn 都失敗 → server 真的死了，必須重開
        self.assertFalse(adb._loopback_stalled(DEAD_DAEMON))
        self.assertFalse(adb._loopback_stalled(b'error: device offline\r\n'))
        self.assertFalse(adb._loopback_stalled(b''))

    def test_loopback_timeout_retries_without_killing_server(self):
        calls = []
        queue = [completed(1, stderr=LOOPBACK_TIMEOUT), completed(0, stdout=b'ok')]

        def run(argv, **_kwargs):
            calls.append(argv)
            return queue.pop(0)

        with patched_adb(run):
            result = adb._run(['shell', 'input', 'tap', '1', '2'])
        self.assertEqual(result.stdout, b'ok')
        self.assertEqual(calls, [TAP, TAP])

    def test_timeout_after_loopback_stall_still_honours_the_single_grace(self):
        """寬限一次為限：loopback 已用掉，接著逾時就照舊重開。"""
        calls = []
        queue = [completed(1, stderr=LOOPBACK_TIMEOUT), completed(0), completed(0),
                 completed(0, stdout=b'ok')]

        def run(argv, **kwargs):
            calls.append(argv)
            if len(calls) == 2:
                raise adb.subprocess.TimeoutExpired(argv, kwargs['timeout'])
            return queue.pop(0)

        with patched_adb(run):
            result = adb._run(['shell', 'input', 'tap', '1', '2'])
        self.assertEqual(result.stdout, b'ok')
        self.assertEqual(calls, [TAP, TAP, ['adb.exe', 'kill-server'],
                                 ['adb.exe', 'start-server'], TAP])

    def test_loopback_timeout_restarts_server_when_it_repeats(self):
        calls = []
        queue = [completed(1, stderr=LOOPBACK_TIMEOUT), completed(1, stderr=LOOPBACK_TIMEOUT),
                 completed(0), completed(0), completed(0, stdout=b'ok')]

        def run(argv, **_kwargs):
            calls.append(argv)
            return queue.pop(0)

        with patched_adb(run):
            result = adb._run(['shell', 'input', 'tap', '1', '2'])
        self.assertEqual(result.stdout, b'ok')
        self.assertEqual(calls, [TAP, TAP, ['adb.exe', 'kill-server'],
                                 ['adb.exe', 'start-server'], TAP])


class AdbPathTest(unittest.TestCase):
    def test_adb_path_honours_override(self):
        with patch.dict(adb.os.environ, {}, clear=True):
            self.assertEqual(adb.adb_path(), adb.DEFAULT_ADB)
        with patch.dict(adb.os.environ, {'PKAUTO_ADB': 'X:/adb.exe'}, clear=True):
            self.assertEqual(adb.adb_path(), 'X:/adb.exe')


class DetectTargetTest(unittest.TestCase):
    """自動偵測：優先 mDNS 名稱，其次無線 IP:PORT，最後 USB；使用者不需輸入埠號。"""

    MDNS = 'adb-R5GL15085ZJ-QZEuM7._adb-tls-connect._tcp'

    def detect(self, stdout):
        with patch.object(adb, 'adb_path', return_value='adb.exe'):
            with patch.object(adb.subprocess, 'run', return_value=completed(0, stdout=stdout)):
                with patch.object(adb.time, 'sleep'):
                    return adb.detect_target(wait_s=0)

    def test_prefers_mdns_name_over_ip_port_and_usb(self):
        out = (b'List of devices attached\n'
               b'R5GL15085ZJ\tdevice\n'
               b'192.168.18.21:41951\tdevice\n'
               + self.MDNS.encode() + b'\tdevice\n')
        self.assertEqual(self.detect(out), self.MDNS)

    def test_falls_back_to_wireless_ip_port(self):
        out = (b'List of devices attached\n'
               b'R5GL15085ZJ\tdevice\n'
               b'192.168.18.21:41951\tdevice\n')
        self.assertEqual(self.detect(out), '192.168.18.21:41951')

    def test_falls_back_to_usb(self):
        self.assertEqual(self.detect(b'List of devices attached\nR5GL15085ZJ\tdevice\n'),
                         'R5GL15085ZJ')

    def test_ignores_offline_and_unauthorized(self):
        out = (b'List of devices attached\n'
               + self.MDNS.encode() + b'\toffline\n'
               b'192.168.18.21:41951\tunauthorized\n'
               b'R5GL15085ZJ\tdevice\n')
        self.assertEqual(self.detect(out), 'R5GL15085ZJ')

    def detect_with_responses(self, responses):
        """依序回放 adb 輸出；多要一次回應就 IndexError（= 呼叫順序變了）。"""
        calls = []
        queue = list(responses)

        def run(argv, **_kwargs):
            calls.append(argv)
            return queue.pop(0)

        with patch.object(adb, 'adb_path', return_value='adb.exe'):
            with patch.object(adb.subprocess, 'run', side_effect=run):
                with patch.object(adb.time, 'sleep'):
                    return adb.detect_target(wait_s=0), calls

    MDNS_SERVICES = (b'List of discovered mdns services\n'
                     b'adb-R5GL15085ZJ-QZEuM7\t_adb-tls-connect._tcp\t'
                     b'192.168.18.21:41951\n')

    def test_discovers_via_mdns_when_no_transport_online(self):
        """mDNS 名稱真的在線時回名稱（跨埠跳動較穩定）。"""
        got, calls = self.detect_with_responses([
            completed(0, stdout=b'List of devices attached\n'),
            completed(0, stdout=self.MDNS_SERVICES),
            completed(0, stdout=b'connected to 192.168.18.21:41951\n'),
            completed(0, stdout=b'List of devices attached\n'
                                + self.MDNS.encode() + b'\tdevice\n'),
        ])
        self.assertEqual(got, self.MDNS)
        self.assertIn(['adb.exe', 'connect', '192.168.18.21:41951'], calls)

    def test_mdns_fallback_returns_online_endpoint_when_name_not_registered(self):
        """2026-11-23 的 bug：server 重開後只有 IP:PORT 在線，名稱別名不存在。

        舊行為直接回名稱 → 之後每條指令都 `device '...' not found`，重試 3 次整個流程停掉。
        現在必須回 devices 裡真的 `device` 的那一個。
        """
        got, calls = self.detect_with_responses([
            completed(0, stdout=b'List of devices attached\n'),
            completed(0, stdout=self.MDNS_SERVICES),
            completed(0, stdout=b'already connected to 192.168.18.21:41951\n'),
            completed(0, stdout=b'List of devices attached\n'
                                b'192.168.18.21:41951\tdevice\n'),
        ])
        self.assertEqual(got, '192.168.18.21:41951')
        self.assertIn(['adb.exe', 'connect', '192.168.18.21:41951'], calls)

    def test_mdns_fallback_raises_when_connect_never_comes_online(self):
        responses = [completed(0, stdout=b'List of devices attached\n'),
                     completed(0, stdout=self.MDNS_SERVICES),
                     completed(0, stdout=b'connected to 192.168.18.21:41951\n')]
        responses += [completed(0, stdout=b'List of devices attached\n')] * 20
        with self.assertRaisesRegex(RuntimeError, '找不到任何 adb 裝置'):
            self.detect_with_responses(responses)

    def test_raises_when_nothing_found(self):
        with self.assertRaisesRegex(RuntimeError, '找不到任何 adb 裝置'):
            self.detect(b'List of devices attached\n')

    def detect_over_time(self, responses, wait_s=5.0):
        """假時鐘：monotonic 每呼叫一次前進 1 秒，讓重試的路徑可預測。"""
        calls = []
        queue = list(responses)
        clock = itertools.count()

        def run(argv, **_kwargs):
            calls.append(argv)
            return queue.pop(0)

        with patch.dict(adb.os.environ, {}, clear=True):
            with patch.object(adb, 'adb_path', return_value='adb.exe'):
                with patch.object(adb.subprocess, 'run', side_effect=run):
                    with patch.object(adb.time, 'sleep'):
                        with patch.object(adb.time, 'monotonic',
                                          side_effect=lambda: next(clock)):
                            return adb.detect_target(wait_s=wait_s), calls

    def test_rescans_mdns_and_follows_port_change(self):
        """2026-11-26：手機開著但 mDNS 晚幾秒才註冊／中間換埠，舊碼掃一次就報找不到裝置。"""
        got, calls = self.detect_over_time([
            completed(0, stdout=b'List of devices attached\n'),
            completed(0, stdout=b'List of discovered mdns services\n'),
            completed(0, stdout=b'List of devices attached\n'),
            completed(0, stdout=self.MDNS_SERVICES),
            completed(0, stdout=b'connected to 192.168.18.21:41951\n'),
            completed(0, stdout=b'List of devices attached\n'),
            completed(0, stdout=b'List of devices attached\n'),
            completed(0, stdout=b'List of discovered mdns services\n'
                                b'adb-R5GL15085ZJ-QZEuM7\t_adb-tls-connect._tcp\t'
                                b'192.168.18.21:42549\n'),
            completed(0, stdout=b'connected to 192.168.18.21:42549\n'),
            completed(0, stdout=b'List of devices attached\n'
                                b'192.168.18.21:42549\tdevice\n'),
        ])
        self.assertEqual(got, '192.168.18.21:42549')
        self.assertIn(['adb.exe', 'connect', '192.168.18.21:41951'], calls)
        self.assertIn(['adb.exe', 'connect', '192.168.18.21:42549'], calls)

    def test_auto_started_server_is_not_treated_as_error(self):
        """`adb devices` 自己把 server 拉起來時 rc=0、stderr 有 `daemon not running` —— 不能因此重設 server。"""
        got, calls = self.detect_over_time([
            completed(0, stdout=b'List of devices attached\n'
                      + self.MDNS.encode() + b'\tdevice\n',
                      stderr=b'* daemon not running; starting now at tcp:5037\n'
                             b'* daemon started successfully\n'),
        ])
        self.assertEqual(got, self.MDNS)
        self.assertNotIn(['adb.exe', 'kill-server'], calls)

    def test_restarts_dead_server_once_then_detects(self):
        """devices 的 stderr 是 daemon 錯誤時，先重開 server 再偵測（不是「手機沒開」）。"""
        got, calls = self.detect_over_time([
            completed(1, stdout=b'List of devices attached\n',
                      stderr=b'error: cannot connect to daemon\n'),
            completed(0),
            completed(0),
            completed(0, stdout=b'List of devices attached\n'
                                + self.MDNS.encode() + b'\tdevice\n'),
        ])
        self.assertEqual(got, self.MDNS)
        self.assertIn(['adb.exe', 'kill-server'], calls)
        self.assertIn(['adb.exe', 'start-server'], calls)


if __name__ == '__main__':
    unittest.main()
