"""Kodo signing and HTTP transport with deadlines and redacted failure categories."""
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote, urlsplit

from qiniu import Auth
from qiniu.utils import etag_stream

from publication import (Deadline, InvalidArtifact, MAX_IMAGE_BYTES, RUN_PATTERN,
                         StorageError, validate_artifact, validate_screen_id)


def _https_origin(value):
    try:
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.path not in ("", "/")
                or parts.query or parts.fragment or parts.port not in (None, 443)
                or any(ord(c) <= 32 or ord(c) >= 127 for c in value)):
            raise ValueError
        return value.rstrip("/")
    except (TypeError, ValueError):
        raise ValueError("invalid_https_origin") from None


@dataclass(frozen=True)
class KodoConfig:
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    bucket: str
    domain: str
    screen_id: str
    upload_host: str = ""

    @classmethod
    def from_env(cls, env=None, *, require_upload=True):
        env = os.environ if env is None else env
        keys = [env.get(name, "").strip() for name in ("QINIU_ACCESS_KEY", "QINIU_SECRET_KEY", "KODO_BUCKET", "SCREEN_ID")]
        if not all(keys) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", keys[2]):
            raise ValueError("missing_or_invalid_kodo_config")
        validate_screen_id(keys[3])
        domain = _https_origin(env.get("KODO_DOMAIN", ""))
        upload_host = env.get("KODO_UPLOAD_HOST", "")
        if upload_host or require_upload:
            upload_host = _https_origin(upload_host)
        return cls(keys[0], keys[1], keys[2], domain, keys[3], upload_host)


class HTTPTransport:
    def request(self, method, url, *, timeout, body=b"", fields=None, max_bytes=MAX_IMAGE_BYTES):
        payload = {"method": method, "url": url, "max_bytes": max_bytes,
                   "body": base64.b64encode(body).decode("ascii"), "fields": fields or {}}
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "storage.http_worker"], input=json.dumps(payload).encode(),
                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise StorageError("request_timeout", retryable=True, uncertain=method == "POST") from None
        except OSError:
            raise StorageError("transport_unavailable") from None
        try:
            if completed.returncode != 0:
                raise ValueError
            response = json.loads(completed.stdout)
            if "error" in response:
                allowed = {"network_error", "tls_error", "response_too_large", "http_worker_error", "invalid_method"}
                code = response["error"] if response["error"] in allowed else "http_worker_error"
                raise StorageError(code, retryable=code == "network_error", uncertain=method == "POST")
            status = response["status"]
            if type(status) is not int or not 100 <= status <= 999:
                raise ValueError
            data = base64.b64decode(response["body"], validate=True)
            if len(data) > max_bytes:
                raise StorageError("response_too_large", uncertain=method == "POST")
            return status, response["headers"], data
        except (KeyError, TypeError, ValueError):
            raise StorageError("invalid_worker_response", uncertain=method == "POST") from None


class KodoStorage:
    def __init__(self, config, *, transport=None, deadline=None, sleep=time.sleep):
        self.config = config
        self.auth = Auth(config.access_key, config.secret_key)
        self.transport = transport or HTTPTransport()
        self.deadline = deadline or Deadline()
        self.sleep = sleep

    def _check_key(self, key):
        prefix = f"family-calendar/{self.config.screen_id}/"
        if not isinstance(key, str) or not key.startswith(prefix):
            raise ValueError("key_outside_screen")
        suffix = key[len(prefix):]
        if suffix != "latest.png" and not re.fullmatch(r"history/\d{4}-\d{2}-\d{2}/" + RUN_PATTERN + r"-[1-9]\d{0,8}\.png", suffix):
            raise ValueError("invalid_object_key")

    def download_url(self, key, *, expires=600):
        self._check_key(key)
        return self.auth.private_download_url(self.config.domain + "/" + quote(key, safe="/"), expires=expires)

    @staticmethod
    def _status_error(status, *, writing=False):
        if status in (401, 403):
            return StorageError("unauthorized")
        if status == 614:
            return StorageError("object_exists")
        return StorageError("http_error", retryable=status == 429 or 500 <= status < 600,
                            uncertain=writing and 500 <= status < 600)

    def _pause(self, attempt, retry_after=""):
        delay = (2, 5)[attempt]
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                try:
                    delay = max(delay, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    pass
        if not 0 <= delay < self.deadline.remaining():
            raise StorageError("deadline_exceeded")
        self.sleep(delay)

    def read_image(self, key):
        url = self.download_url(key)
        for attempt in range(3):
            retry_after = ""
            try:
                status, headers, data = self.transport.request("GET", url, timeout=self.deadline.timeout(30))
                if status == 404:
                    return None
                if status == 200:
                    return validate_artifact(data, expected_screen=self.config.screen_id)
                retry_after = headers.get("retry-after", "")
                raise self._status_error(status)
            except StorageError as error:
                if not error.retryable or attempt == 2:
                    raise
                self._pause(attempt, retry_after)

    def put_image(self, key, image, insert_only):
        self._check_key(key)
        if image.screen_id != self.config.screen_id or not self.config.upload_host:
            raise ValueError("invalid_upload_target")
        policy = {"insertOnly": int(insert_only), "fsizeLimit": MAX_IMAGE_BYTES,
                  "mimeLimit": "image/png", "detectMime": 1}
        token = self.auth.upload_token(self.config.bucket, key, expires=3600, policy=policy)
        status, _, response = self.transport.request(
            "POST", self.config.upload_host, timeout=self.deadline.timeout(60),
            body=image.png_bytes, fields={"token": token, "key": key}, max_bytes=65536)
        if status != 200:
            raise self._status_error(status, writing=True)
        try:
            uploaded = json.loads(response)
            if uploaded["key"] != key or uploaded["hash"] != etag_stream(io.BytesIO(image.png_bytes)):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise StorageError("upload_response_mismatch", uncertain=True) from None
