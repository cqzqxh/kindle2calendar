"""Write a private download URL to a new owner-only file, never stdout."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from storage.kodo import KodoConfig, KodoStorage


def main(argv=None):
    parser = argparse.ArgumentParser(description="签发指定时间戳图片的私有下载链接，保存到权限 0600 的新文件")
    parser.add_argument("--key", required=True, help="完整时间戳图片对象 key")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expires-seconds", type=int, default=300, help="有效秒数，1–300，默认 300；实际期限需验证")
    args = parser.parse_args(argv)
    created = False
    try:
        if not 1 <= args.expires_seconds <= 300:
            raise ValueError("invalid_expiry")
        config = KodoConfig.from_env(require_upload=False)
        storage = KodoStorage(config)
        url = storage.download_url(args.key, expires=args.expires_seconds)
        expires_at = int(parse_qs(urlsplit(url).query)["e"][0])
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(url + "\n")
        print(json.dumps({"output": str(args.output.resolve()), "expires_at": expires_at}))
        return 0
    except (ValueError, OSError, KeyError):
        if created:
            try:
                args.output.unlink()
            except OSError:
                pass
        print(json.dumps({"status": "signature_file_not_created", "exit_code": 2}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
