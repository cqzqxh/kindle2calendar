import io
import unittest
import struct
import zlib
from datetime import datetime, timedelta, timezone

from PIL import Image

from publication import (GenerationContext, InvalidArtifact, StorageError,
                         build_artifact, publish_artifact, validate_artifact)


NOW = datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)


def png(value=255, mode="L", size=(1072, 1448)):
    output = io.BytesIO()
    Image.new(mode, size, value).save(output, format="PNG")
    return output.getvalue()


def artifact(minutes=0, run="run-1", value=255):
    return build_artifact(png(value), GenerationContext(
        NOW + timedelta(minutes=minutes), "demo-screen", run, 1))


class MemoryStorage:
    def __init__(self, previous=None):
        self.objects = {}
        self.writes = []
        self.reads = []
        self.write_hook = None
        self.read_hook = None
        if previous:
            self.objects[previous.latest_key] = previous.png_bytes

    def read_image(self, key):
        self.reads.append(key)
        if self.read_hook:
            self.read_hook(self, key)
        data = self.objects.get(key)
        return validate_artifact(data, expected_screen="demo-screen", now=NOW) if data else None

    def put_image(self, key, image, insert_only):
        self.writes.append(key)
        if self.write_hook:
            self.write_hook(self, key, image, insert_only)
        if insert_only and key in self.objects:
            raise StorageError("object_exists")
        self.objects[key] = image.png_bytes


class ArtifactTests(unittest.TestCase):
    def test_rejects_4bit_grayscale_even_when_pillow_reports_l(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        raw = (b"\0" + b"\xff" * 536) * 1448
        image = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1072, 1448, 4, 0, 0, 0, 0))
        image += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
        self.assertEqual(Image.open(io.BytesIO(image)).mode, "L")
        with self.assertRaises(InvalidArtifact):
            build_artifact(image, GenerationContext(NOW, "demo-screen", "run-1", 1))

    def test_rejects_missing_or_corrupt_iend_crc_and_trailing_data(self):
        image = artifact().png_bytes
        for data in (image[:-4], image[:-1] + bytes([image[-1] ^ 1]), image + b"extra"):
            with self.subTest(length=len(data)), self.assertRaises(InvalidArtifact):
                validate_artifact(data, now=NOW)

    def test_roundtrip_and_utc_history(self):
        image = artifact()
        loaded = validate_artifact(image.png_bytes, expected_screen="demo-screen", now=NOW)
        self.assertEqual(loaded.sha256, image.sha256)
        self.assertEqual(loaded.generated_at, NOW)
        self.assertEqual(loaded.history_key, "family-calendar/demo-screen/history/2026-10-25/run-1-1.png")

    def test_rejects_bad_image_content(self):
        for data in (png(128), png(mode="RGB"), png(size=(12, 12)), png()[:-20], b"not png", b"x" * 2097153):
            with self.subTest(length=len(data)), self.assertRaises(InvalidArtifact):
                build_artifact(data, GenerationContext(NOW, "demo-screen", "run-1", 1))

    def test_rejects_missing_metadata_wrong_screen_and_future(self):
        with self.assertRaises(InvalidArtifact):
            validate_artifact(png(), now=NOW)
        with self.assertRaises(InvalidArtifact):
            validate_artifact(artifact().png_bytes, expected_screen="other", now=NOW)
        with self.assertRaises(InvalidArtifact):
            validate_artifact(artifact(6).png_bytes, now=NOW)

    def test_identifiers_attempt_and_naive_time(self):
        for context in (GenerationContext(NOW, "../bad", "a", 1),
                        GenerationContext(NOW, "screen", "../a", 1),
                        GenerationContext(NOW, "screen", "a", 0),
                        GenerationContext(NOW, "screen", "a", True),
                        GenerationContext(NOW.replace(tzinfo=None), "screen", "a", 1)):
            with self.subTest(context=context), self.assertRaises(InvalidArtifact):
                build_artifact(png(), context)


class PublicationTests(unittest.TestCase):
    def publish(self, image, store):
        return publish_artifact(image, store, now=NOW, sleep=lambda _: None)

    def test_first_publish_verifies_history_before_latest(self):
        image, store = artifact(), MemoryStorage()
        result = self.publish(image, store)
        self.assertEqual(result.status, "published")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(store.objects[image.latest_key], image.png_bytes)
        self.assertEqual(store.objects[image.history_key], image.png_bytes)
        self.assertEqual(store.writes, [image.history_key, image.latest_key])

    def test_identical_retry_repairs_missing_history_without_latest_write(self):
        image = artifact()
        store = MemoryStorage(image)
        self.assertEqual(self.publish(image, store).status, "already_current")
        self.assertEqual(store.writes, [image.history_key])
        self.assertEqual(self.publish(image, store).status, "already_current")
        self.assertNotIn(image.latest_key, store.writes)

    def test_old_equal_time_or_same_identity_cannot_replace_latest(self):
        previous = artifact()
        for candidate in (artifact(-1, "run-2"), artifact(0, "run-2", 0), artifact(1, "run-1")):
            store = MemoryStorage(previous)
            result = self.publish(candidate, store)
            self.assertEqual(result.exit_code, 3)
            self.assertFalse(store.writes)
            self.assertEqual(store.objects[previous.latest_key], previous.png_bytes)

    def test_history_failure_does_not_change_latest(self):
        previous, candidate = artifact(-1), artifact(0, "run-2")
        store = MemoryStorage(previous)
        def fail(s, key, image, insert_only):
            raise StorageError("unauthorized")
        store.write_hook = fail
        self.assertNotEqual(self.publish(candidate, store).exit_code, 0)
        self.assertNotIn(candidate.latest_key, store.writes)
        self.assertEqual(store.objects[candidate.latest_key], previous.png_bytes)

    def test_history_conflict_never_overwrites(self):
        image, store = artifact(), MemoryStorage()
        other = artifact(0, "run-2")
        store.objects[image.history_key] = other.png_bytes
        self.assertEqual(self.publish(image, store).exit_code, 3)
        self.assertNotIn(image.latest_key, store.writes)

    def test_uncertain_upload_is_confirmed_by_readback(self):
        image, store = artifact(), MemoryStorage()
        def committed_then_timeout(s, key, candidate, insert_only):
            s.objects[key] = candidate.png_bytes
            raise StorageError("timeout", retryable=True, uncertain=True)
        store.write_hook = committed_then_timeout
        result = self.publish(image, store)
        self.assertEqual(result.status, "published")
        self.assertTrue(result.uncertain_write_confirmed)

    def test_retry_rechecks_latest_after_backoff(self):
        previous, candidate, third = artifact(-2), artifact(0, "run-2"), artifact(1, "run-3")
        store = MemoryStorage(previous)
        failed = False
        def fail_once(s, key, image, insert_only):
            nonlocal failed
            if key == candidate.latest_key and not failed:
                failed = True
                raise StorageError("timeout", retryable=True, uncertain=True)
        def other_publisher(_):
            store.objects[candidate.latest_key] = third.png_bytes
        store.write_hook = fail_once
        result = publish_artifact(candidate, store, now=NOW, sleep=other_publisher)
        self.assertEqual(result.status, "concurrent_change")
        self.assertEqual(store.objects[candidate.latest_key], third.png_bytes)

    def test_initial_read_failure_never_looks_like_empty_bucket(self):
        image, store = artifact(), MemoryStorage()
        def fail(s, key):
            raise StorageError("unauthorized")
        store.read_hook = fail
        self.assertNotEqual(self.publish(image, store).exit_code, 0)
        self.assertFalse(store.writes)

    def test_readback_failure_restores_previous_bytes(self):
        previous, candidate = artifact(-1), artifact(0, "run-2")
        store = MemoryStorage(previous)
        failed = False
        def read_failure(s, key):
            nonlocal failed
            if key == candidate.latest_key and s.objects.get(key) == candidate.png_bytes and not failed:
                failed = True
                raise StorageError("readback_failed")
        store.read_hook = read_failure
        result = self.publish(candidate, store)
        self.assertEqual(result.status, "failed_restored")
        self.assertEqual(result.exit_code, 4)
        self.assertEqual(store.objects[candidate.latest_key], previous.png_bytes)

    def test_first_failure_does_not_claim_rollback(self):
        image, store = artifact(), MemoryStorage()
        def fail(s, key, candidate, insert_only):
            if key == image.latest_key:
                raise StorageError("unauthorized")
        store.write_hook = fail
        result = self.publish(image, store)
        self.assertEqual(result.status, "failed_no_previous")
        self.assertEqual(result.exit_code, 5)

    def test_changed_latest_before_overwrite_aborts(self):
        previous, candidate, third = artifact(-2), artifact(0, "run-2"), artifact(1, "run-3")
        store = MemoryStorage(previous)
        def replace(s, key):
            if key == candidate.latest_key and candidate.history_key in s.objects:
                s.objects[key] = third.png_bytes
        store.read_hook = replace
        self.assertEqual(self.publish(candidate, store).status, "concurrent_change")
        self.assertNotIn(candidate.latest_key, store.writes)

    def test_other_publisher_is_never_rolled_back(self):
        previous, candidate, third = artifact(-2), artifact(0, "run-2"), artifact(1, "run-3")
        store = MemoryStorage(previous)
        def replace(s, key):
            if key == candidate.latest_key and key in s.writes:
                s.objects[key] = third.png_bytes
        store.read_hook = replace
        self.assertEqual(self.publish(candidate, store).status, "concurrent_change")
        self.assertEqual(store.objects[candidate.latest_key], third.png_bytes)
        self.assertEqual(store.writes.count(candidate.latest_key), 1)

    def test_failed_restore_is_unconfirmed(self):
        previous, candidate = artifact(-1), artifact(0, "run-2")
        store = MemoryStorage(previous)
        def fail(s, key):
            if key == candidate.latest_key and key in s.writes:
                raise StorageError("offline")
        def restore_fail(s, key, image, insert_only):
            if key == candidate.latest_key and image.sha256 == previous.sha256:
                raise StorageError("offline")
        store.read_hook, store.write_hook = fail, restore_fail
        result = self.publish(candidate, store)
        self.assertEqual(result.status, "failed_recovery_unverified")
        self.assertEqual(result.exit_code, 5)
