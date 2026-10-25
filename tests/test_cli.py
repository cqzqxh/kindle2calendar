from contextlib import redirect_stdout
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from scripts.publish_calendar import main as publish_main
from scripts.sign_download_url import main as sign_main
from test_kodo import ENV
from test_publication import artifact, MemoryStorage


class CLITests(unittest.TestCase):
    def test_publish_cli_emits_verified_result(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, ENV, clear=True):
            path = Path(folder) / "image.png"
            path.write_bytes(artifact().png_bytes)
            store = MemoryStorage()
            out = io.StringIO()
            with patch("scripts.publish_calendar.KodoStorage", return_value=store), redirect_stdout(out):
                self.assertEqual(publish_main(["--image", str(path)]), 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result["status"], "published")
            self.assertNotIn("fixture-secret", out.getvalue())

    def test_missing_config_or_invalid_image_never_initializes_storage(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            path = Path(folder) / "bad.png"
            path.write_bytes(b"bad")
            with patch("scripts.publish_calendar.KodoStorage") as factory, redirect_stdout(io.StringIO()):
                self.assertEqual(publish_main(["--image", str(path)]), 2)
            factory.assert_not_called()

    def test_unexpected_errors_are_redacted(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, ENV, clear=True):
            path = Path(folder) / "image.png"
            path.write_bytes(artifact().png_bytes)
            out = io.StringIO()
            with patch("scripts.publish_calendar.KodoStorage", side_effect=RuntimeError("secret-url")), redirect_stdout(out):
                self.assertEqual(publish_main(["--image", str(path)]), 5)
            self.assertNotIn("secret", out.getvalue())

    def test_signature_file_private_non_overwriting_and_not_printed(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, ENV, clear=True):
            path = Path(folder) / "download.txt"
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(sign_main(["--output", str(path)]), 0)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            url = path.read_text().strip()
            params = parse_qs(urlsplit(url).query)
            self.assertEqual(int(params["e"][0]), json.loads(out.getvalue())["expires_at"])
            self.assertNotIn("token", out.getvalue())
            self.assertNotIn("fixture-secret", url)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(sign_main(["--output", str(path)]), 2)
            self.assertEqual(path.read_text().strip(), url)

    def test_invalid_signature_duration_or_missing_secrets_creates_no_file(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, ENV, clear=True):
            path = Path(folder) / "download.txt"
            for days in ("0", "-1", "366"):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(sign_main(["--output", str(path), "--expires-days", days]), 2)
                self.assertFalse(path.exists())
