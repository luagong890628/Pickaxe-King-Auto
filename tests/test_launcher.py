"""Exercise BAT input using fixtures; never connect or touch the phone."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ADB_LINE = r'set "ADB=D:\Tools\scrcpy-win64-v3.3.4\adb.exe"'
WIFI = '192.168.18.21:5555'
USB = 'R5GL15085ZJ'
DEVICES_HEADER = 'List of devices attached\n'


@unittest.skipUnless(os.name == 'nt', 'Windows CMD required')
class LauncherInputTest(unittest.TestCase):
    def run_launcher(self, inputs, devices=None, tcpip_adds_wifi=True, fake_adb=None):
        """Run the BAT against fixtures. devices=None means USB + fixed-port Wi-Fi both online."""
        source = (Path(__file__).resolve().parents[1] / 'Pickaxe-King-Auto.bat').read_text(encoding='ascii')
        replacements = [
            ('if not exist "%PY%" goto no_python', 'rem fixture Python available'),
            ('"%PY%" cycle_fixed.py %*', 'echo RUN %ANDROID_SERIAL% %* & cmd /c exit 0'),
        ]
        if fake_adb is None:
            replacements += [
                ('"%ADB%" server-status >nul 2>&1', 'ver >nul'),
                ('"%ADB%" -s %USBSERIAL% tcpip %PORT%', 'call "%~dp0tcpip.bat" %USBSERIAL% %PORT%'),
                ('"%ADB%" connect %SERIAL%', 'echo CONNECT %SERIAL%'),
                ('ping -n 5 127.0.0.1 >nul', 'ver >nul'),
                ('in (\'"%ADB%" devices\')', 'in (devices.txt)'),
            ]
        for old, new in replacements:
            self.assertIn(old, source, f'fixture target missing from BAT: {old}')
            source = source.replace(old, new)
        if fake_adb is not None:
            source = source.replace(ADB_LINE, f'set "ADB={fake_adb}"')
            source = source.replace('"%ADB%"', 'call "%ADB%"')
        if devices is None:
            devices = DEVICES_HEADER + f'{USB}\tdevice\n{WIFI}\tdevice\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'launch.bat').write_bytes(source.replace('\n', '\r\n').encode('ascii'))
            (root / 'devices.txt').write_bytes(devices.replace('\n', '\r\n').encode('ascii'))
            (root / 'input.txt').write_bytes(inputs.replace('\n', '\r\n').encode('ascii'))
            tcpip = '@echo off\r\necho TCPIP %1 %2\r\n'
            if tcpip_adds_wifi:
                tcpip += f'echo {WIFI}\tdevice>>"%~dp0devices.txt"\r\n'
            (root / 'tcpip.bat').write_bytes(tcpip.encode('ascii'))
            with (root / 'input.txt').open('rb') as stream:
                result = subprocess.run(['cmd.exe', '/d', '/c', 'launch.bat --dry-run'],
                                        cwd=root, stdin=stream, capture_output=True, timeout=20)
            return result.stdout.decode(errors='replace'), result.returncode

    def test_wifi_uses_fixed_port_without_asking(self):
        output, rc = self.run_launcher('1\n\n\n')
        self.assertEqual(rc, 0, output)
        self.assertIn(f'CONNECT {WIFI}', output)
        self.assertIn(f'RUN {WIFI} --dry-run', output)
        self.assertNotIn('Port:', output)

    def test_usb_does_not_connect_wirelessly(self):
        output, rc = self.run_launcher('2\n\n\n')
        self.assertEqual(rc, 0, output)
        self.assertNotIn('CONNECT ', output)
        self.assertIn(f'RUN {USB} --dry-run', output)

    def test_invalid_choice_reprompts(self):
        for invalid in ('abcde', '36545', '3'):
            with self.subTest(invalid=invalid):
                output, rc = self.run_launcher(invalid + '\n1\n\n\n')
                self.assertEqual(rc, 0, output)
                self.assertIn(f'RUN {WIFI} --dry-run', output)

    def test_wifi_recovery_reenables_fixed_port_over_usb(self):
        """Phone rebooted: port 5555 gone, USB present -> BAT runs tcpip itself."""
        output, rc = self.run_launcher('1\n\n\n', devices=DEVICES_HEADER + f'{USB}\tdevice\n')
        self.assertEqual(rc, 0, output)
        self.assertIn(f'TCPIP {USB} 5555', output)
        self.assertIn(f'RUN {WIFI} --dry-run', output)

    def test_wifi_recovery_without_usb_asks_for_cable(self):
        other = '192.168.18.99:5555'
        output, rc = self.run_launcher('1\n\n', devices=DEVICES_HEADER + f'{other}\tdevice\n')
        self.assertEqual(rc, 1, output)
        self.assertIn('not listening on port 5555', output)
        self.assertNotIn('TCPIP ', output)

    def test_wifi_recovery_is_attempted_only_once(self):
        output, rc = self.run_launcher('1\n\n', devices=DEVICES_HEADER + f'{USB}\tdevice\n',
                                       tcpip_adds_wifi=False)
        self.assertEqual(rc, 1, output)
        self.assertEqual(output.count('TCPIP '), 1, output)
        self.assertIn('even after re-enabling port 5555', output)

    def test_no_device_at_all_reports_it(self):
        output, rc = self.run_launcher('2\n\n', devices=DEVICES_HEADER)
        self.assertEqual(rc, 1, output)
        self.assertIn('No device found.', output)

    def test_bat_pins_fixed_port_and_drops_port_prompt(self):
        source = (Path(__file__).resolve().parents[1] / 'Pickaxe-King-Auto.bat').read_text(encoding='ascii')
        self.assertIn(ADB_LINE, source)
        self.assertIn('set "PORT=5555"', source)
        self.assertIn('tcpip %PORT%', source)
        self.assertNotIn('set /p "PORT=', source)

    def test_launcher_restarts_unhealthy_adb_server_before_connecting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_adb = root / 'fake-adb.bat'
            fake_adb.write_bytes((
                '@echo off\r\n'
                'if "%~1"=="server-status" (\r\n'
                '  if exist "%~dp0healthy" exit /b 0\r\n'
                '  exit /b 1\r\n'
                ')\r\n'
                'if "%~1"=="kill-server" echo KILL>>"%~dp0calls.txt"\r\n'
                'if "%~1"=="start-server" (\r\n'
                '  echo START>>"%~dp0calls.txt"\r\n'
                '  echo ok>"%~dp0healthy"\r\n'
                ')\r\n'
                'if "%~1"=="connect" echo CONNECT %~2>>"%~dp0calls.txt"\r\n'
                'if "%~1"=="devices" (\r\n'
                '  echo List of devices attached\r\n'
                f'  echo {WIFI}\tdevice\r\n'
                ')\r\n'
                'exit /b 0\r\n'
            ).encode('ascii'))
            output, rc = self.run_launcher('1\n\n\n', fake_adb=fake_adb)
            calls = (root / 'calls.txt').read_text()
        self.assertEqual(rc, 0, output)
        self.assertIn('ADB server is not responding; restarting it.', output)
        self.assertIn('KILL', calls)
        self.assertIn('START', calls)
        self.assertIn(f'CONNECT {WIFI}', calls)
        self.assertIn(f'RUN {WIFI} --dry-run', output)


if __name__ == '__main__':
    unittest.main()