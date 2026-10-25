"""Write a private download URL to a new owner-only file, never stdout."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from storage.kodo import KodoConfig, KodoStorage


def main(argv=None):
    parser = argparse.ArgumentParser(description="签发 Kindle 固定图片私有下载链接，保存到权限 0600 的新文件")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expires-days", type=int, default=30, help="有效天数，1–365，默认 30；实际期限需验证")
    args = parser.parse_args(argv)
    created = False
    try:
        if not 1 <= args.expires_days <= 365:
            raise ValueError("invalid_expiry")
        config = KodoConfig.from_env(require_upload=False)
        storage = KodoStorage(config)
        url = storage.download_url(f"family-calendar/{config.screen_id}/latest.png", expires=args.expires_days * 86400)
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
