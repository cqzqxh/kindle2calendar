import base64
import io
import json
import subprocess
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import time
from unittest.mock import patch
from urllib.parse import urlsplit

import qiniu
from qiniu.utils import etag_stream

from publication import Deadline, InvalidArtifact, StorageError, publish_artifact
from storage.kodo import HTTPTransport, KodoConfig, KodoStorage
from storage.http_worker import perform
from test_publication import artifact, NOW


ENV = {"QINIU_ACCESS_KEY": "fixture-ak", "QINIU_SECRET_KEY": "fixture-secret",
       "KODO_BUCKET": "calendar-test", "KODO_DOMAIN": "https://images.example",
       "KODO_UPLOAD_HOST": "https://upload.qiniup.com", "SCREEN_ID": "demo-screen"}


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class KodoTests(unittest.TestCase):
    def storage(self, responses):
        http = FakeHTTP(responses)
        return KodoStorage(KodoConfig.from_env(ENV), transport=http, sleep=lambda _: None), http

    def test_config_is_strict_and_repr_does_not_expose_secrets(self):
        self.assertNotIn("fixture-secret", repr(KodoConfig.from_env(ENV)))
        for change in ({"KODO_DOMAIN": "http://images.example"}, {"KODO_DOMAIN": "https://user:secret@example"},
                       {"KODO_DOMAIN": "https://example?token=x"}, {"KODO_UPLOAD_HOST": ""},
                       {"SCREEN_ID": "../bad"}, {"QINIU_SECRET_KEY": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                KodoConfig.from_env({**ENV, **change})

    def test_only_404_is_absent(self):
        image = artifact()
        store, _ = self.storage([(404, {}, b"")])
        self.assertIsNone(store.read_image(image.latest_key))
        for status in (200, 204, 301, 401, 403):
            store, http = self.storage([(status, {}, b"bad")])
            with self.subTest(status=status), self.assertRaises((StorageError, InvalidArtifact)):
                store.read_image(image.latest_key)
            self.assertEqual(len(http.calls), 1)

    def test_insecure_download_is_explicit_and_does_not_disable_upload_verification(self):
        self.assertFalse(KodoConfig.from_env(ENV).insecure_download_tls)
        for value in ("true", "false", "", "yes"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                KodoConfig.from_env({**ENV, "KODO_INSECURE_TLS": value})
        image = artifact()
        for value, verify in (("0", True), ("1", False)):
            response = json.dumps({"key": image.latest_key, "hash": etag_stream(io.BytesIO(image.png_bytes))}).encode()
            http = FakeHTTP([(200, {}, image.png_bytes), (200, {}, response)])
            store = KodoStorage(KodoConfig.from_env({**ENV, "KODO_INSECURE_TLS": value}), transport=http)
            self.assertEqual(store.read_image(image.latest_key).sha256, image.sha256)
            self.assertEqual(http.calls[0][2]["verify_tls"], verify)
            store.put_image(image.latest_key, image, False)
            self.assertTrue(http.calls[1][2].get("verify_tls", True))

    def test_read_retries_transient_failure_but_never_changes_key(self):
        image = artifact()
        store, http = self.storage([(503, {}, b""), (429, {}, b""), (200, {}, image.png_bytes)])
        loaded = store.read_image(image.latest_key)
        self.assertEqual(loaded.sha256, image.sha256)
        self.assertEqual(len(http.calls), 3)
        self.assertTrue(all(call[1].startswith("https://images.example/" + image.latest_key + "?e=") for call in http.calls))

    def test_upload_token_exact_key_and_insert_semantics(self):
        image = artifact()
        for insert_only, key in ((True, image.history_key), (False, image.latest_key)):
            response = json.dumps({"key": key, "hash": etag_stream(io.BytesIO(image.png_bytes))}).encode()
            store, http = self.storage([(200, {}, response)])
            store.put_image(key, image, insert_only)
            fields = http.calls[0][2]["fields"]
            token_part = fields["token"].split(":")[-1]
            policy = json.loads(base64.urlsafe_b64decode(token_part + "=" * (-len(token_part) % 4)))
            self.assertEqual(policy["scope"], "calendar-test:" + key)
            self.assertEqual(policy.get("insertOnly", 0), int(insert_only))
            self.assertEqual(policy["fsizeLimit"], 2097152)
            self.assertEqual(policy["mimeLimit"], "image/png")
            self.assertEqual(http.calls[0][2]["body"], image.png_bytes)

    def test_upload_error_or_bad_hash_does_not_report_success(self):
        image = artifact()
        for response in ((200, {}, b'{"key":"wrong","hash":"wrong"}'), (401, {}, b"private-url"),
                         (503, {}, b"private-url")):
            store, http = self.storage([response])
            with self.assertRaises(StorageError) as caught:
                store.put_image(image.latest_key, image, False)
            self.assertNotIn("private-url", str(caught.exception))
            self.assertEqual(len(http.calls), 1)  # publisher must reconcile before retrying writes

    def test_deadline_stops_requests_and_reserves_recovery(self):
        clock = [0.0]
        deadline = Deadline(100, clock=lambda: clock[0])
        store, http = self.storage([])
        store.deadline = deadline
        clock[0] = 11
        with self.assertRaises(StorageError):
            store.read_image(artifact().latest_key)
        self.assertFalse(http.calls)
        deadline.recovering = True
        self.assertEqual(deadline.timeout(30), 30)

    def test_recovery_probe_preserves_time_for_restore_and_verification(self):
        previous, candidate = artifact(-1), artifact(0, "run-2")
        clock, recovery_calls = [0.0], []
        deadline = Deadline(clock=lambda: clock[0])
        objects = {previous.latest_key: previous.png_bytes, candidate.history_key: candidate.png_bytes}
        class Transport:
            latest_reads = 0
            restored = False
            def request(self, method, url, *, timeout, body=b"", fields=None, **kwargs):
                if deadline.recovering:
                    recovery_calls.append((method, timeout))
                if method == "GET":
                    key = urlsplit(url).path.lstrip("/")
                    if key == candidate.latest_key:
                        self.latest_reads += 1
                        if self.latest_reads == 2:
                            clock[0] = 390  # Last minute of the normal budget.
                        if deadline.recovering:
                            clock[0] += timeout
                            if not self.restored:
                                raise StorageError("request_timeout", retryable=True)
                    return 200, {}, objects[key]
                key = fields["key"]
                objects[key] = body
                clock[0] += timeout
                if body == candidate.png_bytes:
                    raise StorageError("request_timeout", retryable=True, uncertain=True)
                self.restored = True
                response = {"key": key, "hash": etag_stream(io.BytesIO(body))}
                return 200, {}, json.dumps(response).encode()
        store = KodoStorage(KodoConfig.from_env(ENV), transport=Transport(), deadline=deadline,
                            sleep=lambda delay: clock.__setitem__(0, clock[0] + delay))
        result = publish_artifact(candidate, store, now=NOW, budget=deadline)
        self.assertEqual(result.status, "failed_restored")
        self.assertEqual(objects[candidate.latest_key], previous.png_bytes)
        self.assertEqual(recovery_calls, [("GET", 5), ("POST", 55), ("GET", 30)])
        self.assertLessEqual(clock[0], deadline.end)

    def test_transport_timeout_and_errors_are_sanitized(self):
        for failure in (subprocess.TimeoutExpired("secret-url", 1), OSError("secret-url")):
            with patch("storage.kodo.subprocess.run", side_effect=failure):
                with self.assertRaises(StorageError) as caught:
                    HTTPTransport().request("GET", "https://example?token=secret", timeout=0.1)
                self.assertNotIn("secret", str(caught.exception))

    def test_worker_parameters_are_not_in_process_arguments(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps({"status": 404, "headers": {}, "body": ""}).encode(), b"")
        with patch("storage.kodo.subprocess.run", return_value=completed) as run:
            HTTPTransport().request("GET", "https://example?token=secret", timeout=2)
        self.assertNotIn("secret", repr(run.call_args.args))
        self.assertIn(b"secret", run.call_args.kwargs["input"])
        self.assertEqual(run.call_args.kwargs["timeout"], 2)

    def test_transport_passes_verification_flag_to_child_process(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps({"status": 404, "headers": {}, "body": ""}).encode(), b"")
        with patch("storage.kodo.subprocess.run", return_value=completed) as run:
            HTTPTransport().request("GET", "https://images.example", timeout=2)
            self.assertIs(json.loads(run.call_args.kwargs["input"])["verify_tls"], True)
            HTTPTransport().request("GET", "https://images.example", timeout=2, verify_tls=False)
            self.assertIs(json.loads(run.call_args.kwargs["input"])["verify_tls"], False)

    def test_key_outside_screen_is_rejected_without_request(self):
        store, http = self.storage([])
        with self.assertRaises(ValueError):
            store.read_image("family-calendar/other/latest.png")
        self.assertFalse(http.calls)


class HTTPWorkerTests(unittest.TestCase):
    def test_worker_defaults_to_verification_and_only_get_can_opt_out(self):
        for method, flag, expected in (("GET", None, True), ("GET", True, True),
                                      ("GET", False, False), ("POST", False, True)):
            with self.subTest(method=method, flag=flag), patch("storage.http_worker.requests.Session") as session_class:
                session = session_class.return_value.__enter__.return_value
                session.request.return_value.__enter__.return_value.status_code = 404
                payload = {"method": method, "url": "https://images.example", "max_bytes": 1024,
                           "body": "", "fields": {}}
                if flag is not None:
                    payload["verify_tls"] = flag
                self.assertEqual(perform(payload)["status"], 404)
                self.assertIs(session.request.call_args.kwargs["verify"], expected)
                self.assertIs(session.trust_env, False)

    @classmethod
    def setUpClass(cls):
        cls.cut_requests = 0
        cls.download_image = artifact()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                if self.path == "/cut-once":
                    cls.cut_requests += 1
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(cls.download_image.png_bytes)))
                    self.end_headers()
                    self.wfile.write(cls.download_image.png_bytes[:40] if cls.cut_requests == 1 else cls.download_image.png_bytes)
                    self.close_connection = True
                    return
                if self.path == "/slow":
                    time.sleep(1)
                status = 614 if self.path == "/exists" else (302 if self.path == "/redirect" else 200)
                self.send_response(status)
                self.end_headers()
                try:
                    self.wfile.write(b"a" * 1024)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_actual_worker_response_limit_and_no_redirects(self):
        transport = HTTPTransport()
        self.assertEqual(transport.request("GET", self.origin, timeout=3)[2], b"a" * 1024)
        self.assertEqual(transport.request("GET", self.origin + "/redirect", timeout=3)[0], 302)
        self.assertEqual(transport.request("GET", self.origin + "/exists", timeout=3)[0], 614)
        with self.assertRaises(StorageError):
            transport.request("GET", self.origin, timeout=3, max_bytes=100)

    def test_hard_timeout_terminates_worker(self):
        start = time.monotonic()
        with self.assertRaises(StorageError) as caught:
            HTTPTransport().request("GET", self.origin + "/slow", timeout=0.4)
        self.assertEqual(caught.exception.code, "request_timeout")
        self.assertLess(time.monotonic() - start, 1.5)

    def test_interrupted_response_retries_then_downloads_complete_image(self):
        store = KodoStorage(KodoConfig.from_env(ENV), sleep=lambda _: None)
        with patch.object(store, "download_url", return_value=self.origin + "/cut-once"):
            loaded = store.read_image(self.download_image.latest_key)
        self.assertEqual(loaded.sha256, self.download_image.sha256)
        self.assertEqual(self.cut_requests, 2)
