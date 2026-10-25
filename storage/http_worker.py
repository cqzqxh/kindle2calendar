"""One bounded HTTP operation per process; secrets arrive on stdin, never argv."""
import base64
import json
import logging
import sys

import requests


def perform(payload):
    method = payload["method"]
    if method not in ("GET", "POST"):
        return {"error": "invalid_method", "retryable": False}
    maximum = payload["max_bytes"]
    with requests.Session() as session:
        session.trust_env = False
        options = dict(timeout=(5, 30), allow_redirects=False, stream=True)
        if method == "POST":
            image = base64.b64decode(payload["body"], validate=True)
            options.update(data=payload["fields"], files={"file": ("calendar.png", image, "image/png")})
        with session.request(method, payload["url"], **options) as response:
            chunks, count = [], 0
            # Non-success bodies are not needed and may contain private data.
            if response.status_code == 200:
                for chunk in response.iter_content(65536):
                    count += len(chunk)
                    if count > maximum:
                        return {"error": "response_too_large", "retryable": False}
                    chunks.append(chunk)
            return {"status": response.status_code,
                    "headers": {"retry-after": response.headers.get("Retry-After", "")},
                    "body": base64.b64encode(b"".join(chunks)).decode("ascii")}


def main():
    logging.disable(logging.CRITICAL)
    try:
        payload = json.load(sys.stdin)
        result = perform(payload)
    except requests.exceptions.SSLError:
        result = {"error": "tls_error", "retryable": False}
    except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError):
        result = {"error": "network_error", "retryable": True}
    except Exception:
        result = {"error": "http_worker_error", "retryable": False}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
