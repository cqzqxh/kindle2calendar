"""Publish an existing, validated calendar artifact to Kodo."""
import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import time

from publication import Deadline, MAX_IMAGE_BYTES, publish_artifact, validate_artifact
from storage.kodo import KodoConfig, KodoStorage


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验并发布日历 PNG 到 Kodo")
    parser.add_argument("--image", type=Path, required=True, help="包含发布元数据的 PNG 路径")
    args = parser.parse_args(argv)
    try:
        config = KodoConfig.from_env()
        with args.image.open("rb") as source:
            image = validate_artifact(source.read(MAX_IMAGE_BYTES + 1), expected_screen=config.screen_id)
        remaining = 540.0
        if os.environ.get("CALENDAR_DEADLINE_MONOTONIC"):
            remaining = float(os.environ["CALENDAR_DEADLINE_MONOTONIC"]) - time.monotonic()
            if not math.isfinite(remaining) or remaining <= 0:
                raise ValueError("invalid_deadline")
        deadline = Deadline(min(540, remaining))
        storage = KodoStorage(config, deadline=deadline)
        result = publish_artifact(image, storage, budget=deadline)
        print(json.dumps(asdict(result), ensure_ascii=False))
        return result.exit_code
    except (ValueError, OSError):
        print(json.dumps({"status": "invalid_input_or_config", "exit_code": 2}))
        return 2
    except Exception:
        # SDK/transport exception messages can include credentials and signed URLs.
        print(json.dumps({"status": "publication_unconfirmed", "exit_code": 5}))
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
