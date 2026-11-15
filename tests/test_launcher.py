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
        source = source.replace('"%ADB%" connect %PHONE%:%PORT%', 'echo CONNECT %PHONE%:%PORT%')
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
