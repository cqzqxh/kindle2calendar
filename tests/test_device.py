import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SIGNED_URL = "https://calendar.example/family-calendar/screen/latest.png?e=1900000000&token=private-fixture"
PREVIOUS_PNG = b"\x89PNG\r\n\x1a\nprevious"


class DeviceTests(unittest.TestCase):
    def device_run(self, mode):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            mock = root / "bin"
            mock.mkdir()
            (root / "run.sh").write_bytes((ROOT / "kindle/run.sh").read_bytes())
            (root / "ca-bundle.crt").write_text("test CA bundle")
            (root / "calendar.png").write_bytes(PREVIOUS_PNG)
            (root / "config.sh").write_text(
                f"CALENDAR_URL='{SIGNED_URL}'\n"
                f"CA_CERT='{root}/ca-bundle.crt'\nFBINK='{mock}/fbink'\nINTERVAL=60\n")
            script = f"#!{sys.executable}\n" + r'''import os, sys, signal, pathlib
root = pathlib.Path(os.environ['MOCK_ROOT'])
name = pathlib.Path(sys.argv[0]).name
with (root/'calls').open('a') as output:
    output.write(name+' '+' '.join(sys.argv[1:])+'\n')
mode = os.environ['MOCK_MODE']
if name == 'lipc-get-prop':
    print('0')
if name == 'curl':
    config = pathlib.Path(sys.argv[sys.argv.index('--config')+1]).read_text()
    (root/'request.config').write_text(config)
    if mode in ('offline', 'expired'):
        sys.exit(7 if mode == 'offline' else 22)
    target = pathlib.Path(sys.argv[sys.argv.index('--output')+1])
    if mode == 'invalid':
        data = b'HTTP error page'
    elif mode == 'same':
        data = (root/'calendar.png').read_bytes()
    else:
        data = bytes.fromhex('89504e470d0a1a0a') + b'new image'
    target.write_bytes(data)
if name == 'fbink' and mode == 'draw-fail' and 'next.png' in ' '.join(sys.argv):
    sys.exit(1)
if name == 'sleep':
    os.kill(os.getppid(), signal.SIGTERM)
'''
            for name in ("curl", "fbink", "lipc-get-prop", "lipc-set-prop", "sleep"):
                target = mock / name
                target.write_text(script)
                target.chmod(0o700)
            env = {**os.environ, "PATH": str(mock) + ":" + os.environ["PATH"],
                   "MOCK_ROOT": str(root), "MOCK_MODE": mode}
            result = subprocess.run(["sh", str(root / "run.sh")], env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / ".running").exists())
            calls = (root / "calls").read_text()
            self.assertIn("lipc-set-prop com.lab126.powerd preventScreenSaver 0", calls)
            self.assertEqual((root / "request.config").read_text(), f'url = "{SIGNED_URL}"\n')
            self.assertNotIn("private-fixture", calls)
            self.assertNotIn(b"private-fixture", result.stdout + result.stderr)
            self.assertNotIn("--show-error", calls)
            if mode == "valid":
                self.assertIn("fbink -c -f -g", calls)
                self.assertEqual((root / "calendar.png").read_bytes(), b"\x89PNG\r\n\x1a\nnew image")
            else:
                self.assertEqual((root / "calendar.png").read_bytes(), PREVIOUS_PNG)
                if mode == "draw-fail":
                    self.assertEqual(calls.count("fbink -c -f -g"), 2)
                    self.assertIn(f"file={root}/calendar.png", calls)
                else:
                    self.assertNotIn("fbink ", calls)

    def test_offline_keeps_previous_image(self):
        self.device_run("offline")

    def test_expired_signature_keeps_previous_image(self):
        self.device_run("expired")

    def test_non_png_response_keeps_previous_image(self):
        self.device_run("invalid")

    def test_signed_download_updates_image_without_logging_signature(self):
        self.device_run("valid")

    def test_unchanged_image_does_not_refresh_screen(self):
        self.device_run("same")

    def test_failed_drawing_restores_previous_image(self):
        self.device_run("draw-fail")

    def test_url_cannot_inject_curl_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "run.sh").write_bytes((ROOT / "kindle/run.sh").read_bytes())
            (root / "config.sh").write_text("CALENDAR_URL='https://example/secret\noutput=other'\n")
            result = subprocess.run(["sh", str(root / "run.sh")], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b"secret", result.stdout + result.stderr)
            self.assertFalse((root / ".running").exists())


if __name__ == "__main__":
    unittest.main()
