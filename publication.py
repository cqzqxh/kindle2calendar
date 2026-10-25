"""Validated calendar artifacts and immutable timestamped publication."""
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
import hashlib
import io
import re
import time
import zlib

from PIL import Image, PngImagePlugin, UnidentifiedImageError

MAX_IMAGE_BYTES = 2 * 1024 * 1024
SCREEN_PATTERN = r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?"
RUN_PATTERN = r"[A-Za-z0-9_-]{1,80}"


class InvalidArtifact(ValueError):
    """A fixed, non-sensitive error code suitable for CLI output."""


class StorageError(Exception):
    def __init__(self, code, *, retryable=False, uncertain=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.uncertain = uncertain


class Deadline:
    """One shared deadline for upload, verification and finite retries."""
    def __init__(self, seconds=540, *, clock=time.monotonic):
        self.clock = clock
        self.end = clock() + seconds

    def remaining(self):
        return self.end - self.clock()

    def timeout(self, maximum):
        remaining = self.remaining()
        if remaining <= 0:
            raise StorageError("deadline_exceeded")
        return min(maximum, remaining)


@dataclass(frozen=True)
class GenerationContext:
    now: datetime
    screen_id: str
    run_id: str
    run_attempt: int


@dataclass(frozen=True)
class Artifact:
    png_bytes: bytes
    screen_id: str
    generated_at: datetime
    run_id: str
    run_attempt: int
    sha256: str

    def object_key(self, timezone_name="Asia/Shanghai"):
        local = self.generated_at.astimezone(ZoneInfo(timezone_name))
        return f"family-calendar/{self.screen_id}/{local:%Y%m%d}/{local:%Y%m%d%H%M%S}.png"


@dataclass(frozen=True)
class PublishResult:
    status: str
    object_key: str
    sha256: str
    generated_at: str
    exit_code: int = 0
    error_code: str = ""


def validate_screen_id(value):
    if not isinstance(value, str) or not re.fullmatch(SCREEN_PATTERN, value):
        raise InvalidArtifact("invalid_screen_id")
    return value


def _check_context(context):
    validate_screen_id(context.screen_id)
    if not isinstance(context.run_id, str) or not re.fullmatch(RUN_PATTERN, context.run_id):
        raise InvalidArtifact("invalid_run_id")
    if type(context.run_attempt) is not int or not 1 <= context.run_attempt <= 999999999:
        raise InvalidArtifact("invalid_run_attempt")
    if not isinstance(context.now, datetime) or context.now.utcoffset() is None:
        raise InvalidArtifact("timezone_required")


def _check_png_structure(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise InvalidArtifact("invalid_png_signature")
    offset, saw_header, saw_data, data_finished = 8, False, False, False
    while offset + 12 <= len(data):
        size = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + size
        if end > len(data) or not re.fullmatch(b"[A-Za-z]{4}", kind):
            raise InvalidArtifact("invalid_png_chunk")
        payload = data[offset + 8:offset + 8 + size]
        crc = int.from_bytes(data[end - 4:end], "big")
        if zlib.crc32(kind + payload) != crc:
            raise InvalidArtifact("invalid_png_crc")
        if not saw_header and kind != b"IHDR":
            raise InvalidArtifact("missing_png_header")
        if kind == b"IHDR":
            if saw_header or size != 13 or payload[8:12] != bytes((8, 0, 0, 0)) or payload[12] not in (0, 1):
                raise InvalidArtifact("invalid_png_header")
            saw_header = True
        elif kind == b"IDAT":
            if data_finished:
                raise InvalidArtifact("invalid_png_data_order")
            saw_data = True
        elif kind == b"IEND":
            if size or not saw_data or end != len(data):
                raise InvalidArtifact("invalid_png_end")
            return
        else:
            if kind[0] < 97:  # No PLTE or unknown critical chunk in grayscale PNG.
                raise InvalidArtifact("unexpected_png_chunk")
            if saw_data:
                data_finished = True
        offset = end
    raise InvalidArtifact("incomplete_png")


def _decode(png_bytes):
    if not isinstance(png_bytes, bytes) or not 0 < len(png_bytes) <= MAX_IMAGE_BYTES:
        raise InvalidArtifact("invalid_image_size")
    _check_png_structure(png_bytes)
    try:
        with Image.open(io.BytesIO(png_bytes)) as image:
            if image.format != "PNG" or image.size != (1072, 1448) or image.mode != "L":
                raise InvalidArtifact("invalid_image_format")
            if getattr(image, "n_frames", 1) != 1:
                raise InvalidArtifact("animated_image")
            image.verify()
        with Image.open(io.BytesIO(png_bytes)) as image:
            image.load()
            if not set(image.tobytes()) <= set(range(0, 256, 17)):
                raise InvalidArtifact("invalid_gray_levels")
            return image.copy(), dict(image.info)
    except InvalidArtifact:
        raise
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError):
        raise InvalidArtifact("invalid_png") from None


def build_artifact(png_bytes, context):
    _check_context(context)
    image, _ = _decode(png_bytes)
    metadata = PngImagePlugin.PngInfo()
    values = {
        "calendar_schema": "1", "screen_id": context.screen_id,
        "generated_at": context.now.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "run_id": context.run_id, "run_attempt": str(context.run_attempt),
    }
    for key, value in values.items():
        metadata.add_text(key, value)
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=metadata, optimize=True)
    return validate_artifact(output.getvalue(), expected_screen=context.screen_id, now=context.now)


def validate_artifact(png_bytes, *, expected_screen=None, now=None):
    _, info = _decode(png_bytes)
    try:
        if info["calendar_schema"] != "1":
            raise InvalidArtifact("unsupported_image_schema")
        stamp = info["generated_at"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", stamp):
            raise InvalidArtifact("invalid_generated_at")
        generated_at = datetime.fromisoformat(stamp)
        if not re.fullmatch(r"[1-9]\d{0,8}", info["run_attempt"]):
            raise InvalidArtifact("invalid_run_attempt")
        context = GenerationContext(generated_at, info["screen_id"], info["run_id"], int(info["run_attempt"]))
        _check_context(context)
        if expected_screen is not None and context.screen_id != expected_screen:
            raise InvalidArtifact("screen_mismatch")
        if generated_at > (now or datetime.now(timezone.utc)) + timedelta(minutes=5):
            raise InvalidArtifact("future_image")
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, InvalidArtifact):
            raise
        raise InvalidArtifact("invalid_image_metadata") from None
    return Artifact(png_bytes, context.screen_id, generated_at, context.run_id,
                    context.run_attempt, hashlib.sha256(png_bytes).hexdigest())


def publish_artifact(candidate, storage, *, now=None, sleep=time.sleep, budget=None,
                     timezone_name="Asia/Shanghai"):
    """Insert one immutable image. Never probe a missing key through CDN before upload."""
    candidate = validate_artifact(candidate.png_bytes, expected_screen=candidate.screen_id, now=now)
    key = candidate.object_key(timezone_name)
    budget = budget or getattr(storage, "deadline", None) or Deadline()

    def result(status, code=0, error=""):
        return PublishResult(status, key, candidate.sha256, candidate.generated_at.isoformat(), code, error)

    for attempt in range(3):
        write_error = None
        try:
            budget.timeout(1)
            storage.put_image(key, candidate, insert_only=True)
        except StorageError as error:
            write_error = error
        if write_error is None or write_error.uncertain or write_error.code == "object_exists":
            try:
                stored = storage.read_image(key)
                if stored is not None:
                    if stored.sha256 != candidate.sha256:
                        return result("version_conflict", 3, "timestamp_collision")
                    return result("already_current" if write_error and write_error.code == "object_exists"
                                  else "published")
            except (StorageError, InvalidArtifact):
                return result("publication_unconfirmed", 5, "readback_failed")
            return result("publication_unconfirmed", 5, "readback_missing")
        if not write_error.retryable or attempt == 2:
            return result("upload_failed", 5, write_error.code)
        delay = (2, 5)[attempt]
        if budget.remaining() <= delay:
            return result("upload_failed", 5, "deadline_exceeded")
        sleep(delay)
    return result("upload_failed", 5)
