import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts.sync_calendar import sync_once


class LocalSyncTests(unittest.TestCase):
    @patch.dict("os.environ", {"SCREEN_ID": "kindle-pw3", "QINIU_AK": "test-ak",
                               "QINIU_SK": "test-sk", "QINIU_BUCKET": "test-bucket"}, clear=True)
    def test_success_maps_local_credentials_and_uses_current_source(self):
        responses = [subprocess.CompletedProcess([], 0, b"", b""),
                     subprocess.CompletedProcess([], 0, json.dumps({"status": "published"}).encode(), b"")]
        with patch("scripts.sync_calendar.subprocess.run", side_effect=responses) as run:
            result = sync_once(Path("artifacts/test.png"))
        self.assertEqual(result["status"], "published")
        generation = run.call_args_list[0]
        self.assertIn("--caldav", generation.args[0])
        self.assertIn("5", generation.args[0])
        self.assertEqual(generation.kwargs["env"]["QINIU_ACCESS_KEY"], "test-ak")
        self.assertEqual(generation.kwargs["env"]["QINIU_SECRET_KEY"], "test-sk")

    @patch.dict("os.environ", {"SCREEN_ID": "kindle-pw3"}, clear=True)
    def test_failed_source_never_publishes_existing_file(self):
        for failure in [subprocess.CompletedProcess([], 2, b"private", b"private"),
                        subprocess.TimeoutExpired("preview", 120)]:
            with self.subTest(failure=failure):
                with patch("scripts.sync_calendar.subprocess.run") as run:
                    if isinstance(failure, Exception):
                        run.side_effect = failure
                    else:
                        run.return_value = failure
                    result = sync_once(Path("artifacts/old.png"))
                self.assertNotEqual(result["exit_code"], 0)
                self.assertEqual(run.call_count, 1)
                self.assertNotIn("private", json.dumps(result))
