import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StatusbarTests(unittest.TestCase):
    def run_case(self, *, initially_stopped=False, stale=False, enabled=True):
        child = subprocess.Popen(['sleep', '30'])
        try:
            if initially_stopped:
                os.kill(child.pid, signal.SIGSTOP)
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                tool = root / 'pidof'
                tool.write_text('#!/bin/sh\nprintf "%s\\n" '+str(child.pid)+'\n')
                tool.chmod(0o700)
                script = '. "$1"; . "$2"; HIDE_STATUS_BAR=$3; STATUSBAR_PID=; STATUSBAR_STARTED=; '
                script += 'pause_statusbar || exit 1; ps -p "$4" -o stat=; '
                if stale:
                    script += 'STATUSBAR_STARTED=stale; '
                script += 'restore_statusbar || exit 1; ps -p "$4" -o stat='
                result = subprocess.run(['sh', '-c', script, 'test', str(ROOT/'kindle/common.sh'),
                    str(ROOT/'kindle/statusbar.sh'), '1' if enabled else '0', str(child.pid)],
                    env={**os.environ, 'PATH':str(root)+':'+os.environ['PATH']},
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout.splitlines()
        finally:
            os.kill(child.pid, signal.SIGCONT)
            child.terminate()
            child.wait(timeout=5)

    def test_pause_and_restore_only_our_driver(self):
        states = self.run_case()
        self.assertIn('T', states[0])
        self.assertNotIn('T', states[1])

    def test_already_stopped_driver_is_left_stopped(self):
        states = self.run_case(initially_stopped=True)
        self.assertIn('T', states[0])
        self.assertIn('T', states[1])

    def test_stale_identity_is_not_resumed(self):
        states = self.run_case(stale=True)
        self.assertIn('T', states[1])

    def test_disabled_option_does_not_pause(self):
        self.assertTrue(all('T' not in state for state in self.run_case(enabled=False)))
