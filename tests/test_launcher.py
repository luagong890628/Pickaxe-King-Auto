"""Exercise BAT input using fixtures; never connect or touch the phone."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ADB_LINE = r'set "ADB=D:\Tools\scrcpy-win64-v3.3.4\adb.exe"'
MDNS = 'adb-R5GL15085ZJ-QZEuM7._adb-tls-connect._tcp'
WIFI = '192.168.18.21:41951'
USB = 'R5GL15085ZJ'


@unittest.skipUnless(os.name == 'nt', 'Windows CMD required')
class LauncherInputTest(unittest.TestCase):
    def run_launcher(self, inputs='\n\n', target=MDNS, fake_adb=None):
        """The BAT asks nothing except the final Enter; detection is stubbed via target.txt."""
        source = (Path(__file__).resolve().parents[1] / 'Pickaxe-King-Auto.bat').read_text(encoding='ascii')
        replacements = [
            ('if not exist "%PY%" goto no_python', 'rem fixture Python available'),
            ('"%PY%" cycle_fixed.py %*', 'echo RUN %ANDROID_SERIAL% %* & cmd /c exit 0'),
            ('"%PY%" -m pkauto.adb', 'type target.txt'),
        ]
        if fake_adb is None:
            replacements += [
                ('"%ADB%" server-status >nul 2>&1', 'ver >nul'),
            ]
        for old, new in replacements:
            self.assertIn(old, source, f'fixture target missing from BAT: {old}')
            source = source.replace(old, new)
        if fake_adb is not None:
            source = source.replace(ADB_LINE, f'set "ADB={fake_adb}"')
            source = source.replace('"%ADB%"', 'call "%ADB%"')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'launch.bat').write_bytes(source.replace('\n', '\r\n').encode('ascii'))
            (root / 'target.txt').write_bytes((target + '\n' if target else '').encode('ascii'))
            (root / 'input.txt').write_bytes(inputs.replace('\n', '\r\n').encode('ascii'))
            with (root / 'input.txt').open('rb') as stream:
                result = subprocess.run(['cmd.exe', '/d', '/c', 'launch.bat --dry-run'],
                                        cwd=root, stdin=stream, capture_output=True, timeout=20)
            return result.stdout.decode(errors='replace'), result.returncode

    def test_single_enter_starts_with_detected_mdns_target(self):
        output, rc = self.run_launcher()
        self.assertEqual(rc, 0, output)
        self.assertIn(f'Connected: {MDNS}', output)
        self.assertIn(f'RUN {MDNS} --dry-run', output)
        self.assertNotIn('Choose', output)
        self.assertNotIn('Port:', output)

    def test_detects_wireless_ip_port(self):
        output, rc = self.run_launcher(target=WIFI)
        self.assertEqual(rc, 0, output)
        self.assertIn(f'RUN {WIFI} --dry-run', output)

    def test_detects_usb_fallback(self):
        output, rc = self.run_launcher(target=USB)
        self.assertEqual(rc, 0, output)
        self.assertIn(f'RUN {USB} --dry-run', output)

    def test_empty_detection_reports_no_device(self):
        output, rc = self.run_launcher(target='')
        self.assertEqual(rc, 1, output)
        self.assertIn('No device found.', output)
        self.assertNotIn('RUN ', output)

    def test_bat_has_no_mode_or_port_prompt(self):
        source = (Path(__file__).resolve().parents[1] / 'Pickaxe-King-Auto.bat').read_text(encoding='ascii')
        self.assertIn(ADB_LINE, source)
        self.assertIn('-m pkauto.adb', source)
        self.assertNotIn('set /p "MODE=', source)
        self.assertNotIn('set /p "PORT=', source)
        self.assertNotIn('goto wifi', source)

    def test_restarts_unhealthy_server_then_detects(self):
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
                'exit /b 0\r\n'
            ).encode('ascii'))
            output, rc = self.run_launcher(fake_adb=fake_adb)
            calls = (root / 'calls.txt').read_text()
        self.assertEqual(rc, 0, output)
        self.assertIn('ADB server is not responding; restarting it.', output)
        self.assertIn('KILL', calls)
        self.assertIn('START', calls)
        self.assertIn(f'RUN {MDNS} --dry-run', output)


if __name__ == '__main__':
    unittest.main()