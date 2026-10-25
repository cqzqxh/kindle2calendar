"""CalDAV -> real CLI/render/upload/readback -> real Kindle discovery/download.

Only external HTTP services and hardware are fixtures. Every application stage
runs as its normal subprocess, including the bounded Kodo HTTP worker.
"""
import base64
from datetime import datetime, timedelta
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from threading import Thread
import unittest
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from PIL import Image
from qiniu import Auth
from qiniu.utils import etag_stream

from publication import GenerationContext, build_artifact, validate_artifact
from renderer import render_calendar

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "tests/e2e_support"
AUTH = Auth("e2e-ak", "e2e-secret")
SCREEN = "demo-e2e"
BUCKET = "e2e-calendar"


class Services:
    def __init__(self):
        self.now = datetime.now(ZoneInfo("Asia/Shanghai"))
        self.objects = {}
        self.calls = []
        self.mode = "ok"
        day = self.now.strftime("%Y%m%d")
        self.ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//E2E//EN\r\n"
                    "BEGIN:VEVENT\r\nUID:family-fixture\r\nDTSTAMP:20260101T000000Z\r\n"
                    f"DTSTART;VALUE=DATE:{day}\r\nSUMMARY:模拟家庭安排\r\n"
                    "END:VEVENT\r\nEND:VCALENDAR\r\n").encode()

    @staticmethod
    def response(href, properties):
        return (f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>{properties}</d:prop>"
                "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")

    def handle(self, handler):
        host = handler.headers.get("Host")
        method = handler.command
        path = urlsplit(handler.path)
        body = handler.rfile.read(int(handler.headers.get("Content-Length", 0)))
        self.calls.append((host, method, path.path))  # Never record tokens or event bodies.
        if host == "dav.e2e.test":
            expected = "Basic " + base64.b64encode(b"e2e-user:e2e-password").decode()
            if handler.headers.get("Authorization") != expected:
                return 401, b"", {"WWW-Authenticate": 'Basic realm="E2E"'}
            if method == "GET":
                if self.mode == "source_failure":
                    return 503, b"", {}
                return 200, self.ics, {"Content-Type": "text/calendar"}
            if method == "PROPFIND":
                if path.path == "/":
                    props = "<d:current-user-principal><d:href>/principal/</d:href></d:current-user-principal>"
                    rows = self.response("/", props)
                elif path.path == "/principal/":
                    rows = self.response(path.path, "<c:calendar-home-set><d:href>/calendars/</d:href></c:calendar-home-set>")
                else:
                    rows = self.response("/calendars/family/", "<d:displayname>Family</d:displayname>"
                                         "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>")
            elif method == "REPORT":
                rows = "" if self.mode == "empty" else self.response(
                    "/calendars/family/event.ics", '<d:getetag>"fixture-1"</d:getetag>'
                    + "<c:calendar-data>" + escape(self.ics.decode()) + "</c:calendar-data>")
            else:
                raise AssertionError("Unexpected CalDAV method")
            xml = ('<?xml version="1.0" encoding="utf-8"?>'
                   '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                   + rows + "</d:multistatus>")
            return 207, xml.encode(), {"Content-Type": "application/xml; charset=utf-8"}
        if host == "geocoding-api.open-meteo.com":
            return 503, b"", {}
        if host == "upload.e2e.test":
            assert method == "POST"
            message = BytesParser(policy=default).parsebytes(
                b"Content-Type: " + handler.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
            fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                      for part in message.iter_parts()}
            key, token, image = fields["key"].decode(), fields["token"].decode(), fields["file"]
            access, signature, policy64 = token.split(":")
            assert access == "e2e-ak" and AUTH.token(policy64) == access + ":" + signature
            policy = json.loads(base64.urlsafe_b64decode(policy64))
            assert policy["scope"] == BUCKET + ":" + key and policy["insertOnly"] == 1
            assert validate_artifact(image, expected_screen=SCREEN).object_key() == key
            if self.mode == "upload_failure":
                return 403, b"", {}
            if key in self.objects:
                return 614, b"", {}
            self.objects[key] = image
            return 200, json.dumps({"key": key, "hash": etag_stream(io.BytesIO(image))}).encode(), {}
        if host == "rsf.qiniuapi.com":
            signing = (f"GET {handler.path}\nHost: {host}\nContent-Type: application/x-www-form-urlencoded\n"
                       f"X-Qiniu-Date: {handler.headers['X-Qiniu-Date']}\n\n")
            assert handler.headers["Authorization"] == "Qiniu " + AUTH.token(signing)
            params = parse_qs(path.query, keep_blank_values=True)
            assert params["bucket"] == [BUCKET]
            if self.mode == "list_failure" and params["marker"] != [""]:
                return 403, b"", {}
            keys = sorted(key for key in self.objects if key.startswith(params["prefix"][0]))
            # Force pagination even for one object; the first page is incomplete.
            if keys and params["marker"] == [""]:
                result = {"items": [], "marker": "page+/="}
            else:
                assert params["marker"] in ([""], ["page+/="])
                result = {"items": [{"key": key} for key in keys]}
            return 200, json.dumps(result).encode(), {}
        if host == "images.e2e.test":
            unsigned, supplied = handler.path.rsplit("&token=", 1)
            assert supplied == AUTH.token("https://" + host + unsigned)
            assert int(parse_qs(path.query)["e"][0]) >= int(datetime.now().timestamp())
            if self.mode == "download_failure":
                return 403, b"", {}
            key = path.path.lstrip("/")
            if key not in self.objects:
                return 404, b"", {}
            image = b"broken image" if self.mode == "readback_failure" else self.objects[key]
            return 200, image, {}
        raise AssertionError("Unexpected service")


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.services = Services()
        self.server_errors = []
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                try:
                    status, data, headers = test.services.handle(self)
                except Exception as error:
                    test.server_errors.append(type(error).__name__)
                    status, data, headers = 500, b"", {}
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            do_PROPFIND = do_REPORT = do_GET = do_POST = handle_request

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("CALDAV_", "TECENT_", "QINIU_", "KODO_", "WEATHER_", "GITHUB_", "CALENDAR_"))}
        self.env.update(PYTHONPATH=str(SUPPORT), E2E_ORIGIN=f"http://127.0.0.1:{self.server.server_port}",
                        CALDAV_URL="https://dav.e2e.test/", CALDAV_USERNAME="e2e-user",
                        CALDAV_PASSWORD="e2e-password", QINIU_ACCESS_KEY="e2e-ak", QINIU_SECRET_KEY="e2e-secret",
                        KODO_BUCKET=BUCKET, KODO_DOMAIN="https://images.e2e.test",
                        KODO_UPLOAD_HOST="https://upload.e2e.test", SCREEN_ID=SCREEN, TIMEZONE="Asia/Shanghai")
        self.output = self.root / "generated/calendar.png"
        self.device = self.root / "device"
        self.device.mkdir()
        for name in ("run.sh", "common.sh", "power.sh", "discover.sh", "statusbar.sh"):
            shutil.copyfile(ROOT / "kindle" / name, self.device / name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for name in ("curl", "fbink", "lipc-get-prop", "lipc-set-prop"):
            command = bin_dir / name
            command.write_text(f"#!{sys.executable}\n" + (SUPPORT / "device_command.py").read_text())
            command.chmod(0o700)
        config = {"access_key": "e2e-ak", "secret_key": "e2e-secret", "bucket": BUCKET,
                  "domain": "https://images.e2e.test", "screen_id": SCREEN}
        (self.device / "discovery.json").write_text(json.dumps(config))
        (self.device / "discovery.json").chmod(0o600)
        (self.device / "ca.pem").touch()
        (self.device / "config.sh").write_text(
            "POWER_MODE=awake\n" + "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in {
                "DISCOVERY_CONFIG": self.device / "discovery.json", "CA_CERT": self.device / "ca.pem",
                "FBINK": bin_dir / "fbink"}.items()) + "\n")
        self.env.update(PATH=str(bin_dir) + os.pathsep + os.environ["PATH"], E2E_DEVICE=str(self.device),
                        E2E_CURL=shutil.which("curl"))
        old_png = io.BytesIO()
        Image.new("L", (1072, 1448), 255).save(old_png, "PNG")
        old = build_artifact(old_png.getvalue(), GenerationContext(
            self.services.now - timedelta(days=1), SCREEN, "previous", 1))
        self.previous = old.png_bytes
        self.services.objects[old.object_key()] = self.previous
        (self.device / "calendar.png").write_bytes(self.previous)
        (self.device / "display.png").write_bytes(self.previous)

    def command(self, args):
        result = subprocess.run(args, cwd=ROOT, env=self.env, capture_output=True, timeout=45)
        self.assertFalse(self.server_errors, self.server_errors)
        for secret in (b"e2e-secret", b"e2e-password", b"token=", "模拟家庭安排".encode()):
            self.assertNotIn(secret, result.stdout + result.stderr)
        return result

    def sync(self):
        result = self.command([sys.executable, "-m", "scripts.sync_calendar", "--output", str(self.output)])
        state = json.loads(result.stdout)
        self.assertEqual(state["exit_code"], result.returncode)
        self.assertEqual(json.loads((self.output.parent / "status.json").read_text()), state)
        return result, state

    def poll(self, expected="updated"):
        result = self.command(["sh", str(self.device / "run.sh"), "--once"])
        state = dict(line.split("=", 1) for line in (self.device / "state").read_text().splitlines())
        self.assertEqual(state["status"], expected)
        self.assertEqual(result.returncode, 0 if expected == "updated" else 1)
        self.assertFalse((self.device / ".running").exists())

    def assert_previous(self):
        for name in ("calendar.png", "display.png"):
            self.assertEqual((self.device / name).read_bytes(), self.previous)

    def test_calendar_to_device_and_weather_failure(self):
        self.env["WEATHER_CITY"] = "E2E City"  # Weather failure must not block publishing.
        result, state = self.sync()
        self.assertEqual(result.returncode, 0, state)
        self.assertEqual(state["status"], "published")
        generated = validate_artifact(self.output.read_bytes(), expected_screen=SCREEN)
        day = generated.generated_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
        rows = [{"title": "模拟家庭安排", "day": day.isoformat(), "time": "", "member": "",
                 "source_id": "0:family-fixture", "start": datetime.combine(day, datetime.min.time(), ZoneInfo("Asia/Shanghai")).isoformat(),
                 "end": datetime.combine(day + timedelta(days=1), datetime.min.time(), ZoneInfo("Asia/Shanghai")).isoformat(), "all_day": True}]
        expected = render_calendar(rows, generated.generated_at.astimezone(ZoneInfo("Asia/Shanghai")),
                                   {"city": "E2E City", "days": []}, compact=True, update_interval_minutes=5)
        with Image.open(io.BytesIO(expected)) as image, Image.open(self.output) as actual:
            self.assertEqual(image.tobytes(), actual.tobytes())
        self.assertEqual(self.services.objects[state["object_key"]], generated.png_bytes)
        self.poll()
        self.assertEqual((self.device / "calendar.png").read_bytes(), generated.png_bytes)
        self.assertEqual((self.device / "display.png").read_bytes(), generated.png_bytes)
        hosts = [host for host, _, _ in self.services.calls]
        self.assertIn("geocoding-api.open-meteo.com", hosts)
        self.assertEqual(hosts.count("rsf.qiniuapi.com"), 2)
        self.assertEqual(hosts.count("images.e2e.test"), 2)
        self.assertLess(hosts.index("upload.e2e.test"), hosts.index("images.e2e.test"))

    def test_successful_empty_calendar_is_published_and_displayed(self):
        self.services.mode = "empty"
        result, state = self.sync()
        self.assertEqual(result.returncode, 0, state)
        self.poll()
        self.assertEqual((self.device / "calendar.png").read_bytes(), self.output.read_bytes())

    def test_source_failure_never_publishes_stale_local_image(self):
        self.output.parent.mkdir()
        self.output.write_bytes(self.previous)
        self.services.mode = "source_failure"
        result, state = self.sync()
        self.assertEqual(result.returncode, 2, state)
        self.assertEqual(state["status"], "source_or_render_failed")
        self.assertEqual(self.output.read_bytes(), self.previous)
        self.assertFalse(any(host == "upload.e2e.test" for host, _, _ in self.services.calls))
        self.assertEqual(len(self.services.objects), 1)
        self.assert_previous()

    def test_upload_failure_preserves_cloud_and_device_previous_image(self):
        self.services.mode = "upload_failure"
        result, state = self.sync()
        self.assertEqual(result.returncode, 5, state)
        self.assertEqual(state["status"], "upload_failed")
        self.assertEqual(len(self.services.objects), 1)
        self.poll()  # Today's empty prefix falls back to yesterday's committed image.
        self.assert_previous()

    def test_readback_failure_does_not_report_success(self):
        self.services.mode = "readback_failure"
        result, state = self.sync()
        self.assertEqual(result.returncode, 5, state)
        self.assertEqual(state["status"], "publication_unconfirmed")
        self.assertEqual(state["error_code"], "readback_failed")
        self.assert_previous()

    def test_partial_list_failure_preserves_previous_image(self):
        self.assertEqual(self.sync()[0].returncode, 0)
        self.services.mode = "list_failure"
        self.poll("discovery_failed")
        self.assert_previous()

    def test_download_failure_preserves_previous_image(self):
        self.assertEqual(self.sync()[0].returncode, 0)
        self.services.mode = "download_failure"
        self.poll("http_403")
        self.assert_previous()

    def test_display_failure_restores_previous_image(self):
        self.assertEqual(self.sync()[0].returncode, 0)
        self.env["E2E_DRAW_FAIL"] = "1"
        self.poll("draw_failed")
        self.assert_previous()


if __name__ == "__main__":
    unittest.main()
