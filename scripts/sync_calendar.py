"""One bounded local CalDAV/render/publish cycle, suitable for launchd."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

def sync_once(output, *, interval_minutes=5, timeout=240):
    """Never publish an earlier file when the current source/render step fails."""
    started = time.monotonic()
    env = os.environ.copy()
    for target, alias in (("QINIU_ACCESS_KEY", "QINIU_AK"),
                          ("QINIU_SECRET_KEY", "QINIU_SK"), ("KODO_BUCKET", "QINIU_BUCKET")):
        if not env.get(target):
            env[target] = env.get(alias, "")
    if not env.get("SCREEN_ID"):
        return {"status": "missing_screen_id", "exit_code": 2}
    env["CALENDAR_DEADLINE_MONOTONIC"] = str(started + timeout)
    command = [sys.executable, "preview.py", "--caldav", "--screen-id", env["SCREEN_ID"],
               "--update-interval-minutes", str(interval_minutes), "--output", str(output)]
    try:
        rendered = subprocess.run(command, env=env, capture_output=True, timeout=min(120, timeout / 2))
        if rendered.returncode:
            return {"status": "source_or_render_failed", "exit_code": 2}
        published = subprocess.run([sys.executable, "-m", "scripts.publish_calendar", "--image", str(output)],
                                   env=env, capture_output=True, timeout=max(1, timeout - (time.monotonic() - started)))
        result = json.loads(published.stdout)
        result["exit_code"] = published.returncode
        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
        return result
    except subprocess.TimeoutExpired:
        return {"status": "cycle_timeout", "exit_code": 5}
    except (OSError, ValueError):
        return {"status": "cycle_failed", "exit_code": 5}


def main(argv=None):
    parser = argparse.ArgumentParser(description="读取 CalDAV、生成 PNG 并发布到 Kodo（单次，供本机定时调用）")
    parser.add_argument("--output", type=Path, default=Path("artifacts/local-sync/calendar.png"))
    parser.add_argument("--interval-minutes", type=int, default=5)
    args = parser.parse_args(argv)
    if args.interval_minutes < 1:
        parser.error("interval must be positive")
    os.umask(0o077)
    os.chdir(Path(__file__).resolve().parents[1])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with (args.output.parent / "sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "already_running", "exit_code": 0}))
            return 0
        # Suppress library diagnostics that may contain source content or URLs.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = sync_once(args.output, interval_minutes=args.interval_minutes)
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        state = args.output.parent / "status.json"
        temporary = state.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(state)
        print(json.dumps(result, ensure_ascii=False))
        return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
