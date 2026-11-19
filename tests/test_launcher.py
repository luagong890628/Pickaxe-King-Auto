"""Exercise BAT input using fixtures; never connect or touch the phone."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == 'nt', 'Windows CMD required')
class LauncherInputTest(unittest.TestCase):
    def run_launcher(self, inputs):
        source = (Path(__file__).resolve().parents[1] / 'Pickaxe-King-Auto.bat').read_text()
        source = source.replace('if not exist "%PY%" goto no_python', 'rem fixture Python available')
        source = source.replace('"%ADB%" server-status >nul 2>&1', 'ver >nul')
        source = source.replace('if defined SERIAL "%ADB%" connect %SERIAL%', 'if defined SERIAL echo CONNECT %SERIAL%')
        source = source.replace('in (\'"%ADB%" devices\')', 'in (devices.txt)')
        source = source.replace('"%PY%" cycle_fixed.py %*', 'echo RUN %ANDROID_SERIAL% %*')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'launch.bat').write_bytes(source.replace('\n', '\r\n').encode('ascii'))
            (root / 'devices.txt').write_text('List of devices attached\nother device\n192.168.18.21:36545 device\n')
            (root / 'input.txt').write_bytes(inputs.replace('\n', '\r\n').encode('ascii'))
            with (root / 'input.txt').open('rb') as stream:
                result = subprocess.run(['cmd.exe', '/d', '/c', 'launch.bat --dry-run'],
                                        cwd=root, stdin=stream, capture_output=True, timeout=10)
            return result.stdout.decode(errors='replace')

    def test_direct_five_digit_port_selects_wireless_target(self):
        output = self.run_launcher('36545\n\n\n')
        self.assertIn('CONNECT 192.168.18.21:36545', output)
        self.assertIn('RUN 192.168.18.21:36545 --dry-run', output)

    def test_existing_wifi_mode_still_prompts_for_port(self):
        output = self.run_launcher('1\n36545\n\n\n')
        self.assertIn('CONNECT 192.168.18.21:36545', output)
        self.assertIn('RUN 192.168.18.21:36545 --dry-run', output)

    def test_usb_does_not_connect_wirelessly(self):
        output = self.run_launcher('2\n\n\n')
        self.assertNotIn('CONNECT ', output)
        self.assertIn('RUN other --dry-run', output)

    def test_invalid_choice_reprompts(self):
        for invalid in ('abcde', '1234', '65536'):
            with self.subTest(invalid=invalid):
                output = self.run_launcher(invalid + '\n36545\n\n\n')
                self.assertNotIn('CONNECT 192.168.18.21:' + invalid, output)
                self.assertIn('RUN 192.168.18.21:36545 --dry-run', output)

    def test_launcher_checks_server_before_device_enumeration(self):
        source = (Path(__file__).resolve().parents[1] / 'Pickaxe-King-Auto.bat').read_text()
        self.assertIn('server-status', source)
        self.assertIn('if not errorlevel 1', source)
        self.assertIn('goto check_devices', source)
        self.assertIn('start-server', source)
        self.assertIn('set "SERIAL="', source)
        self.assertIn('ADB server could not be started or is not responding.', source)
    def test_launcher_restarts_unhealthy_adb_server_before_connecting(self):
        source = (Path(__file__).resolve().parents[1] / 'Pickaxe-King-Auto.bat').read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_adb = root / 'fake-adb.bat'
            source = source.replace(
                r'set "ADB=D:\Tools\scrcpy-win64-v3.3.4\adb.exe"',
                f'set "ADB={fake_adb}"',
            )
            source = source.replace('"%ADB%"', 'call "%ADB%"')
            source = source.replace('if not exist "%PY%" goto no_python', 'rem fixture Python available')
            source = source.replace('"%PY%" cycle_fixed.py %*', 'echo RUN %ANDROID_SERIAL% %*')
            (root / 'launch.bat').write_bytes(source.replace('\n', '\r\n').encode('ascii'))
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
                '  echo 192.168.18.21:36545 device\r\n'
                ')\r\n'
                'exit /b 0\r\n'
            ).encode('ascii'))
            (root / 'input.txt').write_bytes(b'36545\r\n\r\n\r\n')
            with (root / 'input.txt').open('rb') as stream:
                result = subprocess.run(
                    ['cmd.exe', '/d', '/c', 'launch.bat --dry-run'],
                    cwd=root, stdin=stream, capture_output=True, timeout=10,
                )
            output = result.stdout.decode(errors='replace')
            calls = (root / 'calls.txt').read_text()
        self.assertIn('ADB server is not responding; restarting it.', output)
        self.assertIn('Connected: 192.168.18.21:36545', output)
        self.assertIn('RUN 192.168.18.21:36545 --dry-run', output)
        self.assertIn('KILL', calls)
        self.assertIn('START', calls)
        self.assertIn('CONNECT 192.168.18.21:36545', calls)
