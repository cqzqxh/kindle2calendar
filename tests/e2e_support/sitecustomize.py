"""Test-process-only routing: real HTTP clients, no external service access.

Loaded only when the E2E harness explicitly adds this directory to PYTHONPATH.
Production URLs/config validation stay intact; the final request is sent to the
loopback HTTP fixture. This does not test TLS or real provider compatibility.
"""
import os
import socket
import urllib.request
from urllib.parse import urlsplit

import requests
import niquests


def routed(original):
    def request(self, method, url, **kwargs):
        parsed = urlsplit(str(url))
        if parsed.hostname not in {"dav.e2e.test", "upload.e2e.test", "images.e2e.test",
                                   "rsf.qiniuapi.com", "geocoding-api.open-meteo.com"}:
            raise RuntimeError("E2E blocked unexpected destination")
        self.trust_env = False
        kwargs["proxies"] = {}
        kwargs["headers"] = {**(kwargs.get("headers") or {}), "Host": parsed.netloc}
        target = os.environ["E2E_ORIGIN"] + parsed.path
        if parsed.query:
            target += "?" + parsed.query
        return original(self, method, target, **kwargs)
    return request


requests.Session.request = routed(requests.Session.request)
niquests.Session.request = routed(niquests.Session.request)


def urlopen(request, *args, **kwargs):
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    parsed = urlsplit(url)
    if parsed.hostname != "geocoding-api.open-meteo.com":
        raise RuntimeError("E2E blocked unexpected urllib destination")
    target = os.environ["E2E_ORIGIN"] + parsed.path + "?" + parsed.query
    local = urllib.request.Request(target, headers={"Host": parsed.netloc})
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(local, *args, **kwargs)


urllib.request.urlopen = urlopen
_connect = socket.socket.connect


def connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in ("127.0.0.1", "::1"):
        raise RuntimeError("E2E blocked non-loopback connection")
    return _connect(self, address)


socket.socket.connect = connect
