import io
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SIGNED_URL = 'https://calendar.example/family-calendar/screen/latest.png?e=1900000000&token=private-fixture'


def png(shade=255, size=(1072, 1448), mode='L'):
    output = io.BytesIO()
    Image.new(mode, size, shade).save(output, format='PNG')
    return output.getvalue()


PREVIOUS_PNG = png(255)
NEXT_PNG = png(17)
MOCK = r'''import json, os, pathlib, signal, sys, time
root = pathlib.Path(os.environ['MOCK_ROOT'])
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with (root/'calls').open('a') as stream:
    stream.write(json.dumps([name] + args) + '\n')
mode = os.environ.get('MOCK_MODE', 'valid')
if name == 'lipc-get-prop':
    print('7')
elif name == 'lipc-set-prop':
    if args[-1] == '7' and os.environ.get('MOCK_POWER_RESTORE_FAIL'):
        sys.exit(1)
elif name == 'df':
    print('Filesystem 1024-blocks Used Available Capacity Mounted on')
    print('/dev/test 100000 100 100 1% /' if mode == 'disk-full' else '/dev/test 100000 100 99900 1% /')
elif name == 'curl':
    config = pathlib.Path(args[args.index('--config')+1])
    (root/'request.config').write_text(config.read_text())
    (root/'config.mode').write_text(oct(config.stat().st_mode & 0o777))
    count = len([x for x in (root/'calls').read_text().splitlines() if json.loads(x)[0] == 'curl'])
    if mode == 'block':
        (root/'curl.pid').write_text(str(os.getpid()))
        def stop(*unused):
            (root/'curl.stopped').write_text('yes')
            sys.exit(143)
        signal.signal(signal.SIGTERM, stop)
        while True:
            time.sleep(0.02)
    if mode == 'offline':
        sys.exit(7)
    status = os.environ.get('MOCK_HTTP', '200')
    if mode == 'retry' and count == 1:
        status = '503'
    target = pathlib.Path(args[args.index('--output')+1])
    if mode in ('same', 'startup-fail'):
        data = (root/'calendar.png').read_bytes()
    elif mode == 'invalid':
        data = b'HTML error page'
    elif mode == 'oversize':
        data = (root/'candidate.png').read_bytes() + b'\0' * 2097152
    else:
        data = (root/'candidate.png').read_bytes()
    target.write_bytes(data)
    print(status, end='')
elif name == 'fbink':
    source = args[-1].removeprefix('file=')
    # Model FBInk's decoder boundary, rather than accepting a valid header alone.
    from PIL import Image
    try:
        with Image.open(source) as picture:
            picture.load()
    except Exception:
        sys.exit(1)
    if mode == 'all-draw-fail' or (mode == 'draw-fail' and source.endswith('next.png')):
        sys.exit(1)
    if mode == 'startup-fail' and source.endswith('calendar.png'):
        sys.exit(1)
elif name == 'mv':
    source, dest = args[-2:]
    if mode == 'save-fail' and dest.endswith('/calendar.png'):
        sys.exit(1)
    if mode == 'state-fail' and dest.endswith('/state'):
        sys.exit(1)
    os.replace(source, dest)
elif name == 'sleep':
    if args[0] == '5':
        pass
    elif args[0] in ('60', '1800') and not os.environ.get('MOCK_KEEP_ALIVE'):
        os.kill(os.getppid(), signal.SIGTERM)
    else:
        time.sleep(0.05 if args[0] == '1' else 60)
'''


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ('run.sh', 'common.sh', 'control.sh'):
            source = ROOT / 'kindle' / name
            if source.exists():
                (self.root / name).write_bytes(source.read_bytes())
        (self.root / 'ca-bundle.crt').write_text('test CA bundle')
        (self.root / 'calendar.png').write_bytes(PREVIOUS_PNG)
        (self.root / 'candidate.png').write_bytes(NEXT_PNG)
        for name in ('curl', 'fbink', 'lipc-get-prop', 'lipc-set-prop', 'sleep', 'mv', 'df'):
            target = self.bin / name
            target.write_text(f'#!{sys.executable}\n' + MOCK)
            target.chmod(0o700)
        self.env = {**os.environ, 'PATH': str(self.bin) + ':' + os.environ['PATH'],
                    'MOCK_ROOT': str(self.root), 'MOCK_MODE': 'valid'}
        self.config()

    def config(self, url=SIGNED_URL, expiry='1900000000', extra=''):
        (self.root / 'config.sh').write_text(
            f'CALENDAR_URL={shlex.quote(url)}\n'
            f"CA_CERT={shlex.quote(str(self.root / 'ca-bundle.crt'))}\n"
            f"FBINK={shlex.quote(str(self.bin / 'fbink'))}\nINTERVAL=60\n"
            + (f'URL_EXPIRES_AT={shlex.quote(expiry)}\n' if expiry is not None else '') + extra)

    def run_device(self, mode='valid', once=True, **env):
        result = subprocess.run(['sh', str(self.root / 'run.sh')] + (['--once'] if once else []),
                                env={**self.env, 'MOCK_MODE': mode, **env}, capture_output=True, timeout=8)
        self.assertNotIn(b'private-fixture', result.stdout + result.stderr)
        self.assertNotIn('private-fixture', json.dumps(self.calls()))
        return result

    def calls(self, name=None):
        path = self.root / 'calls'
        calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [call for call in calls if name is None or call[0] == name]

    def state(self):
        return dict(line.split('=', 1) for line in (self.root / 'state').read_text().splitlines())

    def assert_previous(self):
        self.assertEqual((self.root / 'calendar.png').read_bytes(), PREVIOUS_PNG)

    def test_once_success_is_saved_and_cleanup_restores_original_power_setting(self):
        result = self.run_device()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'calendar.png').read_bytes(), NEXT_PNG)
        self.assertFalse((self.root / '.running').exists())
        self.assertIn(['lipc-set-prop', 'com.lab126.powerd', 'preventScreenSaver', '7'], self.calls())
        self.assertEqual(self.state()['status'], 'updated')
        self.assertEqual(self.state()['failures'], '0')
        self.assertGreater(int(self.state()['last_success']), 0)
        self.assertEqual((self.root / 'config.mode').read_text(), '0o600')
        self.assertEqual((self.root / 'request.config').read_text(), f'url = "{SIGNED_URL}"\n')
        curl = self.calls('curl')[0]
        for flag in ('--location', '--insecure', '--show-error'):
            self.assertNotIn(flag, curl)
        self.assertEqual(curl[curl.index('--connect-timeout') + 1], '10')
        self.assertEqual(curl[curl.index('--max-time') + 1], '40')

    def test_network_failure_retries_once_and_keeps_previous(self):
        self.assertEqual(self.run_device('offline').returncode, 1)
        self.assert_previous()
        self.assertEqual(len(self.calls('curl')), 2)
        self.assertEqual(self.state()['status'], 'network_failed')
        self.assertEqual(self.state()['failures'], '1')
        self.assertFalse(self.calls('fbink'))

    def test_only_http_200_is_accepted(self):
        for status in ('204', '302', '401', '403', '404', '500'):
            with self.subTest(status=status):
                (self.root / 'calls').write_text('')
                self.assertEqual(self.run_device(MOCK_HTTP=status).returncode, 1)
                self.assert_previous()
                self.assertFalse(self.calls('fbink'))
                self.assertEqual(len(self.calls('curl')), 2 if status == '500' else 1)
                self.assertEqual(self.state()['status'], f'http_{status}')

    def test_transient_server_failure_can_recover(self):
        self.assertEqual(self.run_device('retry').returncode, 0)
        self.assertEqual(len(self.calls('curl')), 2)
        self.assertIn(['sleep', '5'], self.calls())

    def test_invalid_png_size_ihdr_depth_and_color_preserve_previous(self):
        variants = [b'HTML', png(size=(1071, 1448)), png(mode='RGB'),
                    NEXT_PNG[:8] + b'\0\0\0\x0c' + NEXT_PNG[12:],
                    NEXT_PNG[:12] + b'IDAT' + NEXT_PNG[16:],
                    NEXT_PNG[:24] + b'\x04' + NEXT_PNG[25:], NEXT_PNG[:20]]
        for candidate in variants:
            with self.subTest(header=candidate[:30]):
                (self.root / 'candidate.png').write_bytes(candidate)
                self.assertEqual(self.run_device().returncode, 1)
                self.assert_previous()
                self.assertEqual(self.state()['status'], 'invalid_png')
        self.assertEqual(self.run_device('oversize').returncode, 1)
        self.assertEqual(self.state()['status'], 'too_large')
        self.assert_previous()

    def test_loop_redraws_cache_offline_and_unchanged_skips_second_draw(self):
        self.assertEqual(self.run_device('same', once=False).returncode, 0)
        self.assertEqual(len(self.calls('fbink')), 1)
        self.assertTrue(self.calls('fbink')[0][-1].endswith('calendar.png'))
        self.assertEqual(self.state()['status'], 'unchanged')
        (self.root / 'calls').write_text('')
        self.assertEqual(self.run_device('offline', once=False).returncode, 0)
        self.assertEqual(len(self.calls('fbink')), 1)

    def test_once_same_content_requires_successful_drawing(self):
        self.assertEqual(self.run_device('same').returncode, 0)
        self.assertEqual(len(self.calls('fbink')), 1)

    def test_failed_startup_draw_does_not_skip_identical_download(self):
        self.assertEqual(self.run_device('startup-fail', once=False).returncode, 0)
        self.assertEqual(len(self.calls('fbink')), 2)
        self.assertEqual(self.state()['status'], 'updated')

    def test_draw_and_save_failures_restore_previous_without_success(self):
        for mode, status in (('draw-fail', 'draw_failed'), ('save-fail', 'save_failed'),
                             ('all-draw-fail', 'draw_failed')):
            with self.subTest(mode=mode):
                (self.root / 'calls').write_text('')
                self.assertEqual(self.run_device(mode).returncode, 1)
                self.assert_previous()
                self.assertEqual(len(self.calls('fbink')), 2)
                state = self.state()
                self.assertEqual(state['status'], status)
                self.assertEqual(state['last_success'], '0')
                self.assertEqual(state['recovery'], 'restore_failed' if mode == 'all-draw-fail' else 'restored')

    def test_first_run_failure_does_not_claim_recovery_or_success(self):
        (self.root / 'calendar.png').unlink()
        for mode in ('draw-fail', 'save-fail'):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_device(mode).returncode, 1)
                self.assertFalse((self.root / 'calendar.png').exists())
                self.assertEqual(self.state()['last_success'], '0')
                self.assertEqual(self.state()['recovery'], 'no_previous')
                self.assertEqual(self.state()['display_known'], '0')

    def test_disk_space_preflight_prevents_download(self):
        self.assertEqual(self.run_device('disk-full').returncode, 1)
        self.assertFalse(self.calls('curl'))
        self.assertEqual(self.state()['status'], 'disk_full')

    def test_expired_signature_skips_network_but_keeps_cached_image(self):
        self.config(SIGNED_URL.replace('1900000000', '1000000000'), '1000000000')
        self.assertEqual(self.run_device().returncode, 1)
        self.assertFalse(self.calls('curl'))
        self.assert_previous()
        self.assertEqual(self.state()['status'], 'url_expired')

    def test_expiry_can_be_derived_but_explicit_mismatch_is_configuration_error(self):
        self.config(expiry=None)
        self.assertEqual(self.run_device().returncode, 0)
        self.config(expiry='1900000001')
        self.assertEqual(self.run_device().returncode, 2)

    def test_url_cannot_inject_curl_configuration(self):
        for url in ('http://example/a', 'https://example/secret\noutput=other',
                    'https://example/a"b', 'https://example/a\\b', 'https://example/a b',
                    "https://example/a'b?e=1900000000",
                    'https://example/a?e=1900000000&e=1900000000',
                    'https://user@example/a?e=1900000000', 'https://example/a?e=1900000000#x'):
            with self.subTest(url=url):
                self.config(url)
                self.assertEqual(self.run_device().returncode, 2)
                self.assertFalse((self.root / '.running').exists())

    def test_stale_lock_is_never_removed_or_modified(self):
        lock = self.root / '.running'
        lock.mkdir()
        (lock / 'pid').write_text('999999\n')
        self.assertEqual(self.run_device().returncode, 3)
        self.assertEqual((lock / 'pid').read_text(), '999999\n')
        self.assertFalse(self.calls())

    def test_state_write_failure_keeps_saved_image_and_success_result(self):
        result = self.run_device('state-fail')
        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.root / 'calendar.png').read_bytes(), NEXT_PNG)
        self.assertIn(b'state_write_failed', result.stderr)

    def test_logs_are_bounded_and_have_one_backup(self):
        (self.root / 'run.log').write_text('x' * 131070)
        self.assertEqual(self.run_device().returncode, 0)
        self.assertLessEqual((self.root / 'run.log').stat().st_size, 131072)
        self.assertLessEqual((self.root / 'run.log.1').stat().st_size, 131072)
        self.assertNotIn('private-fixture', (self.root / 'run.log').read_text())

    def wait_file(self, name):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (self.root / name).exists():
                return
            time.sleep(0.02)
        self.fail(f'{name} was not created')

    def control(self, action):
        return subprocess.run(['sh', str(self.root / 'control.sh'), action],
                              env={**self.env, 'MOCK_MODE': 'block', 'MOCK_KEEP_ALIVE': '1'},
                              capture_output=True, timeout=8)

    def test_stop_during_curl_reaps_child_and_restores_power(self):
        process = subprocess.Popen(['sh', str(self.root / 'run.sh')],
                                   env={**self.env, 'MOCK_MODE': 'block'},
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        self.addCleanup(cleanup)
        self.wait_file('curl.pid')
        duplicate = self.run_device()
        self.assertEqual(duplicate.returncode, 3)
        self.assertIsNone(process.poll())
        status = self.control('status')
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn(b'running', status.stdout)
        self.assertNotIn(b'private-fixture', status.stdout + status.stderr)
        stopped = self.control('stop')
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertTrue((self.root / 'curl.stopped').exists())
        self.assertFalse((self.root / '.running').exists())
        child_pid = int((self.root / 'curl.pid').read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)
        self.assertIn(['lipc-set-prop', 'com.lab126.powerd', 'preventScreenSaver', '7'], self.calls())

    def test_control_refuses_reused_pid_and_preserves_stale_lock(self):
        lock = self.root / '.running'
        lock.mkdir()
        (lock / 'pid').write_text(str(os.getpid()))
        (lock / 'started').write_text('wrong-start-identity')
        (lock / 'script').write_text(str(self.root / 'run.sh'))
        result = self.control('stop')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(lock.exists())
        self.assertNotEqual(self.control('start').returncode, 0)
        self.assertNotEqual(self.control('status').returncode, 0)

    def test_control_start_confirms_lock_and_start_failure_is_reported(self):
        started = self.control('start')
        self.assertEqual(started.returncode, 0, started.stderr)
        self.addCleanup(lambda: self.control('stop'))
        self.wait_file('curl.pid')
        self.assertTrue((self.root / '.running' / 'started').read_text().strip())
        self.assertNotEqual(self.control('start').returncode, 0)
        self.assertEqual(self.control('stop').returncode, 0)
        self.config(url='http://invalid')
        self.assertNotEqual(self.control('start').returncode, 0)

    def test_status_before_first_sync_reports_no_success(self):
        result = self.control('status')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('尚无成功同步'.encode(), result.stdout)
        self.assertIn(b'1900000000', result.stdout)

    def test_interrupted_once_is_not_reported_as_success(self):
        process = subprocess.Popen(['sh', str(self.root / 'run.sh'), '--once'],
                                   env={**self.env, 'MOCK_MODE': 'block'},
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.wait_file('curl.pid')
        process.terminate()
        self.assertEqual(process.wait(timeout=5), 1)
        self.assertFalse((self.root / '.running').exists())
        self.assert_previous()

    def test_corrupt_png_with_correct_ihdr_is_rejected_by_decoder(self):
        (self.root / 'candidate.png').write_bytes(NEXT_PNG[:50])
        self.assertEqual(self.run_device().returncode, 1)
        self.assertEqual(self.state()['status'], 'draw_failed')
        self.assertEqual(self.state()['recovery'], 'restored')
        self.assert_previous()

    def test_default_interval_is_1800_and_failures_preserve_last_success(self):
        self.assertEqual(self.run_device().returncode, 0)
        success = self.state()['last_success']
        config = self.root / 'config.sh'
        config.write_text(config.read_text().replace('INTERVAL=60\n', ''))
        self.assertEqual(self.run_device('offline', once=False).returncode, 0)
        self.assertIn(['sleep', '1800'], self.calls())
        self.assertEqual(self.state()['last_success'], success)
        self.assertEqual(self.state()['failures'], '1')

    def test_force_kill_leaves_saved_power_value_and_lock_for_manual_recovery(self):
        process = subprocess.Popen(['sh', str(self.root / 'run.sh')],
                                   env={**self.env, 'MOCK_MODE': 'block'},
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.wait_file('curl.pid')
        child_pid = int((self.root / 'curl.pid').read_text())
        process.kill()
        process.wait(timeout=5)
        os.kill(child_pid, signal.SIGTERM)
        self.wait_file('curl.stopped')
        self.assertEqual((self.root / '.running' / 'powerd.previous').read_text(), '7\n')
        self.assertEqual(self.run_device().returncode, 3)
        self.assertNotEqual(self.control('stop').returncode, 0)
        self.assertTrue((self.root / '.running').exists())

    def test_log_failure_does_not_remove_successful_image(self):
        (self.root / 'run.log').mkdir()
        result = self.run_device()
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'log_write_failed', result.stderr)
        self.assertEqual((self.root / 'calendar.png').read_bytes(), NEXT_PNG)

    def test_managed_int_hup_are_ignored_and_term_cleanup_is_explicit(self):
        self.assertEqual(self.control('start').returncode, 0)
        self.addCleanup(lambda: self.control('stop'))
        self.wait_file('curl.pid')
        pid = int((self.root / '.running' / 'pid').read_text())
        for sig in (signal.SIGINT, signal.SIGHUP):
            os.kill(pid, sig)
            time.sleep(0.1)
            self.assertEqual(self.control('status').returncode, 0)
            self.assertFalse((self.root / 'curl.stopped').exists())
        self.assertIn(b'signals=TERM:stop,INT:ignore,HUP:ignore', self.control('status').stdout)
        self.assertEqual(self.control('stop').returncode, 0)
        self.assertTrue((self.root / 'curl.stopped').exists())
        self.assertFalse((self.root / '.running').exists())
        self.assertIn(['lipc-set-prop', 'com.lab126.powerd', 'preventScreenSaver', '7'], self.calls())

    def test_foreground_int_and_hup_stop_and_restore_power(self):
        for sig in (signal.SIGINT, signal.SIGHUP):
            with self.subTest(signal=sig):
                (self.root / 'curl.pid').unlink(missing_ok=True)
                process = subprocess.Popen(['sh', str(self.root / 'run.sh')],
                                           env={**self.env, 'MOCK_MODE': 'block'},
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.wait_file('curl.pid')
                os.kill(process.pid, sig)
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertFalse((self.root / '.running').exists())
        self.assertEqual(self.calls('lipc-set-prop').count(
            ['lipc-set-prop', 'com.lab126.powerd', 'preventScreenSaver', '7']), 2)

    def test_power_restore_failure_keeps_original_value_and_fails_once(self):
        result = self.run_device(MOCK_POWER_RESTORE_FAIL='1')
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'power_restore_failed', result.stderr)
        self.assertEqual((self.root / 'calendar.png').read_bytes(), NEXT_PNG)
        lock = self.root / '.running'
        self.assertEqual((lock / 'powerd.previous').read_text(), '7\n')
        self.assertTrue((lock / 'powerd.restore_failed').exists())
        self.assertFalse((lock / 'curl.conf').exists())
        self.assertFalse((lock / 'ready').exists())
        self.assertEqual(self.state()['status'], 'power_restore_failed')
        self.assertIn('power_restore_failed', (self.root / 'run.log').read_text())
        status = self.control('status')
        self.assertNotEqual(status.returncode, 0)
        self.assertIn(b'power_restore_failed previous=7', status.stdout)
        self.assertNotEqual(self.control('start').returncode, 0)
        stopped = self.control('stop')
        self.assertNotEqual(stopped.returncode, 0)
        self.assertIn(b'power_restore_failed previous=7', stopped.stdout + stopped.stderr)
        self.assertTrue(lock.exists())

    def test_managed_stop_reports_power_restore_failure(self):
        self.env['MOCK_POWER_RESTORE_FAIL'] = '1'
        self.assertEqual(self.control('start').returncode, 0)
        self.addCleanup(lambda: self.control('stop'))
        self.wait_file('curl.pid')
        result = self.control('stop')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'power_restore_failed previous=7', result.stdout + result.stderr)
        self.assertTrue((self.root / 'curl.stopped').exists())
        self.assertEqual(self.state()['status'], 'power_restore_failed')
        self.assertEqual((self.root / '.running' / 'powerd.previous').read_text(), '7\n')

    def test_power_restore_failure_remains_diagnosable_when_state_write_fails(self):
        self.assertEqual(self.run_device('state-fail', MOCK_POWER_RESTORE_FAIL='1').returncode, 1)
        self.assertFalse((self.root / 'state').exists())
        status = self.control('status')
        self.assertNotEqual(status.returncode, 0)
        self.assertIn(b'power_restore_failed previous=7', status.stdout)
        self.assertEqual((self.root / 'calendar.png').read_bytes(), NEXT_PNG)


if __name__ == '__main__':
    unittest.main()
