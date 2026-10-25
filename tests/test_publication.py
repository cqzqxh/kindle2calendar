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
            self.objects[previous.object_key()] = previous.png_bytes

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

    def test_roundtrip_and_local_timestamp_key(self):
        image = artifact()
        loaded = validate_artifact(image.png_bytes, expected_screen="demo-screen", now=NOW)
        self.assertEqual(loaded.sha256, image.sha256)
        self.assertEqual(loaded.generated_at, NOW)
        self.assertEqual(loaded.object_key(), "family-calendar/demo-screen/20261025/20261025120000.png")

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

    def test_insert_and_readback_without_negative_cache_probe(self):
        image, store = artifact(), MemoryStorage()
        result = self.publish(image, store)
        self.assertEqual(result.status, "published")
        self.assertEqual(store.writes, [image.object_key()])
        self.assertEqual(store.reads, [image.object_key()])
        self.assertEqual(store.objects[image.object_key()], image.png_bytes)

    def test_retry_is_idempotent_and_collision_never_overwrites(self):
        image, store = artifact(), MemoryStorage(artifact())
        self.assertEqual(self.publish(image, store).status, "already_current")
        other = artifact(value=17)
        self.assertEqual(self.publish(other, store).status, "version_conflict")
        self.assertEqual(store.objects[image.object_key()], image.png_bytes)

    def test_upload_failure_keeps_previous(self):
        previous, image = artifact(-1), artifact()
        store = MemoryStorage(previous)
        def fail(*args):
            raise StorageError("unauthorized")
        store.write_hook = fail
        self.assertEqual(self.publish(image, store).exit_code, 5)
        self.assertEqual(store.objects, {previous.object_key(): previous.png_bytes})
        self.assertEqual(store.reads, [])

    def test_uncertain_write_verified(self):
        image, store = artifact(), MemoryStorage()
        def commit_then_fail(s, key, image, insert_only):
            s.objects[key] = image.png_bytes
            raise StorageError("request_timeout", uncertain=True)
        store.write_hook = commit_then_fail
        self.assertEqual(self.publish(image, store).status, "published")

    def test_readback_failure_never_claims_success(self):
        store = MemoryStorage()
        def fail(*args):
            raise StorageError("network_error")
        store.read_hook = fail
        self.assertEqual(self.publish(artifact(), store).status, "publication_unconfirmed")

    def test_day_directory_uses_configured_timezone(self):
        image = build_artifact(png(), GenerationContext(
            datetime(2026, 10, 25, 16, 1, tzinfo=timezone.utc), "demo-screen", "run-2", 1))
        self.assertEqual(image.object_key(), "family-calendar/demo-screen/20261026/20261026000100.png")
        self.assertEqual(image.object_key("UTC"), "family-calendar/demo-screen/20261025/20261025160100.png")
