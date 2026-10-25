"""Validated calendar artifacts and single-writer publication with verified recovery."""
from dataclasses import dataclass
from contextlib import contextmanager
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
    """Normal operations leave time for recovery; recovery never resets the clock."""
    def __init__(self, seconds=540, *, clock=time.monotonic):
        self.clock = clock
        start = clock()
        self.end = start + seconds
        self.normal_end = min(start + 480, self.end - 90)
        self.recovering = False
        self.phase_end = float("inf")

    def remaining(self):
        return min(self.end if self.recovering else self.normal_end, self.phase_end) - self.clock()

    @contextmanager
    def limit(self, seconds):
        previous = self.phase_end
        self.phase_end = min(previous, self.clock() + max(0, seconds))
        try:
            yield
        finally:
            self.phase_end = previous

    def timeout(self, maximum):
        remaining = self.remaining()
        if remaining <= 0:
            raise StorageError("deadline_exceeded")
        return min(maximum, remaining)

    def require_overwrite_budget(self):
        if self.remaining() < 60:
            raise StorageError("insufficient_recovery_budget")


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

    @property
    def latest_key(self):
        return f"family-calendar/{self.screen_id}/latest.png"

    @property
    def history_key(self):
        return (f"family-calendar/{self.screen_id}/history/{self.generated_at:%Y-%m-%d}/"
                f"{self.run_id}-{self.run_attempt}.png")


@dataclass(frozen=True)
class PublishResult:
    status: str
    history_key: str
    latest_key: str
    sha256: str
    generated_at: str
    exit_code: int = 0
    recovery_status: str = "not_needed"
    error_code: str = ""
    uncertain_write_confirmed: bool = False


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


def _same(left, right):
    return (left is None and right is None) or (
        left is not None and right is not None and left.sha256 == right.sha256)


def _ensure_history(candidate, storage, sleep, budget):
    existing = storage.read_image(candidate.history_key)
    if existing:
        if not _same(existing, candidate):
            raise StorageError("history_conflict")
        return False
    for attempt in range(3):
        budget.timeout(1)
        error = None
        try:
            storage.put_image(candidate.history_key, candidate, insert_only=True)
        except StorageError as caught:
            error = caught
        stored = storage.read_image(candidate.history_key)
        if stored:
            if not _same(stored, candidate):
                raise StorageError("history_conflict")
            return bool(error and error.uncertain)
        if error is None or not error.retryable or attempt == 2:
            raise error or StorageError("history_unverified")
        _backoff(attempt, sleep, budget)


def _backoff(attempt, sleep, budget):
    seconds = (2, 5)[attempt]
    if budget.remaining() <= seconds:
        raise StorageError("deadline_exceeded")
    sleep(seconds)


def publish_artifact(candidate, storage, *, now=None, sleep=time.sleep, budget=None):
    candidate = validate_artifact(candidate.png_bytes, expected_screen=candidate.screen_id, now=now)
    budget = budget or getattr(storage, "deadline", None) or Deadline()
    uncertain_confirmed = False

    def result(status, code=0, recovery="not_needed", error=""):
        return PublishResult(status, candidate.history_key, candidate.latest_key, candidate.sha256,
                             candidate.generated_at.isoformat(), code, recovery, error, uncertain_confirmed)

    try:
        previous = storage.read_image(candidate.latest_key)
    except (StorageError, InvalidArtifact):
        return result("failed_read_previous", 5, "unverified", "previous_unreadable")
    if previous and not _same(previous, candidate):
        if (previous.run_id, previous.run_attempt) == (candidate.run_id, candidate.run_attempt):
            return result("version_conflict", 3)
        if candidate.generated_at <= previous.generated_at:
            return result("stale_rejected" if candidate.generated_at < previous.generated_at else "version_conflict", 3)
    try:
        uncertain_confirmed = _ensure_history(candidate, storage, sleep, budget)
        current = storage.read_image(candidate.latest_key)
        if not _same(current, previous):
            return result("concurrent_change", 5, "not_attempted")
        if _same(previous, candidate):
            return result("already_current")
        budget.require_overwrite_budget()
    except (StorageError, InvalidArtifact) as error:
        if isinstance(error, StorageError) and error.code == "history_conflict":
            return result("version_conflict", 3, error="history_conflict")
        return result("failed_before_overwrite", 4 if previous else 5,
                      "previous_retained" if previous else "no_previous", "history_or_precheck_failed")

    for attempt in range(3):
        if attempt:
            try:
                current = storage.read_image(candidate.latest_key)
                if _same(current, candidate):
                    uncertain_confirmed = True
                    return result("published")
                if not _same(current, previous):
                    return result("concurrent_change", 5, "not_attempted")
            except (StorageError, InvalidArtifact):
                break
        write_error = None
        try:
            budget.require_overwrite_budget()
            storage.put_image(candidate.latest_key, candidate, insert_only=False)
        except StorageError as error:
            write_error = error
        try:
            current = storage.read_image(candidate.latest_key)
            if _same(current, candidate):
                uncertain_confirmed |= bool(write_error and write_error.uncertain)
                return result("published")
            if current is not None and not _same(current, previous):
                return result("concurrent_change", 5, "not_attempted")
            if write_error and write_error.retryable and attempt < 2:
                _backoff(attempt, sleep, budget)
                continue
            if previous and _same(current, previous):
                return result("failed_previous_retained", 4, "previous_retained", "latest_unverified")
        except (StorageError, InvalidArtifact):
            pass
        break
    return _restore(candidate, previous, storage, budget, result)


def _restore(candidate, previous, storage, budget, result):
    budget.recovering = True
    if previous is None:
        return result("failed_no_previous", 5, "no_previous", "latest_unverified")
    try:
        # Probe cannot consume the budget needed to restore and verify old bytes.
        with budget.limit(5):
            current = storage.read_image(candidate.latest_key)
        if _same(current, previous):
            return result("failed_previous_retained", 4, "previous_retained", "latest_unverified")
        if current is not None and not _same(current, candidate):
            return result("concurrent_change", 5, "not_attempted")
    except (StorageError, InvalidArtifact):
        pass  # A verified single publisher may restore while reads are failing.
    try:
        try:
            # Keep a full readback window even when the recovery PUT stalls.
            with budget.limit(budget.remaining() - 30):
                budget.timeout(60)
                storage.put_image(candidate.latest_key, previous, insert_only=False)
        except StorageError:
            pass  # An interrupted upload may nevertheless have committed.
        current = storage.read_image(candidate.latest_key)
        if _same(current, previous):
            return result("failed_restored", 4, "restored", "latest_unverified")
    except (StorageError, InvalidArtifact):
        pass
    return result("failed_recovery_unverified", 5, "unverified", "recovery_unverified")
