from __future__ import annotations

import hashlib
import io
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from the_compute_bazaar.prices.archive import (
    create_s3_archive,
    verify_s3_archive,
)
from the_compute_bazaar.prices.storage import list_refs, read_bytes


class FakeS3Client:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.get_calls: list[str] = []

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        prefix = str(kwargs.get("Prefix") or "")
        return {
            "Contents": [
                {
                    "Key": key,
                    "Size": len(value),
                    "ETag": f'"{self.etag(value)}"',
                    "LastModified": datetime(2026, 8, 17, tzinfo=UTC),
                }
                for key, value in sorted(self.objects.items())
                if key.startswith(prefix)
            ],
            "IsTruncated": False,
        }

    def get_object(
        self, *, Bucket: str, Key: str, IfMatch: str | None = None
    ) -> dict[str, object]:
        del Bucket
        value = self.objects[Key]
        etag = self.etag(value)
        if IfMatch and IfMatch.strip('"') != etag:
            raise RuntimeError("precondition failed")
        self.get_calls.append(Key)
        return {"Body": io.BytesIO(value), "ETag": f'"{etag}"'}

    def etag(self, value: bytes) -> str:
        return hashlib.md5(value).hexdigest()  # noqa: S324


class MultipartFakeS3Client(FakeS3Client):
    def etag(self, value: bytes) -> str:
        return f"{super().etag(value)}-2"


class CloudArchiveTest(unittest.TestCase):
    def test_archive_is_verified_replayable_and_incremental(self) -> None:
        client = FakeS3Client(
            {
                "raw/provider=prime/run.json": b'{"offers": [1]}',
                "lake/gold/manifest.json": b'{"status": "ok"}',
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            first = create_s3_archive(
                source_roots=["s3://market-bucket/"],
                archive_root=directory,
                workers=2,
                s3_client=client,
            )
            self.assertEqual(first["downloaded_object_count"], 2)
            self.assertTrue(verify_s3_archive(archive_root=directory)["valid"])

            with patch.dict(
                os.environ,
                {
                    "COMPUTE_BAZAAR_S3_MIRROR_ROOT": str(Path(directory) / "objects"),
                    "COMPUTE_BAZAAR_S3_MIRROR_STRICT": "1",
                },
            ):
                self.assertEqual(
                    read_bytes("s3://market-bucket/raw/provider=prime/run.json"),
                    b'{"offers": [1]}',
                )
                self.assertEqual(
                    list_refs("s3://market-bucket/lake", suffix=".json"),
                    ["s3://market-bucket/lake/gold/manifest.json"],
                )

            client.get_calls.clear()
            second = create_s3_archive(
                source_roots=["s3://market-bucket/"],
                archive_root=directory,
                workers=2,
                s3_client=client,
            )
            self.assertEqual(second["downloaded_object_count"], 0)
            self.assertEqual(second["reused_object_count"], 2)
            self.assertEqual(client.get_calls, [])

    def test_interrupted_archive_does_not_reuse_changed_s3_content(self) -> None:
        client = FakeS3Client({"lake/portable.json": b"old"})
        with tempfile.TemporaryDirectory() as directory:
            create_s3_archive(
                source_roots=["s3://market-bucket/"],
                archive_root=directory,
                s3_client=client,
            )
            (Path(directory) / "latest-manifest.json").unlink()
            client.objects["lake/portable.json"] = b"new"
            client.get_calls.clear()

            result = create_s3_archive(
                source_roots=["s3://market-bucket/"],
                archive_root=directory,
                s3_client=client,
            )

            self.assertEqual(result["downloaded_object_count"], 1)
            self.assertEqual(client.get_calls, ["lake/portable.json"])
            self.assertEqual(
                (
                    Path(directory) / "objects/market-bucket/lake/portable.json"
                ).read_bytes(),
                b"new",
            )

    def test_interrupted_archive_redownloads_unverifiable_multipart_object(
        self,
    ) -> None:
        client = MultipartFakeS3Client({"lake/history.parquet": b"multipart"})
        with tempfile.TemporaryDirectory() as directory:
            create_s3_archive(
                source_roots=["s3://market-bucket/"],
                archive_root=directory,
                s3_client=client,
            )
            (Path(directory) / "latest-manifest.json").unlink()
            client.get_calls.clear()

            result = create_s3_archive(
                source_roots=["s3://market-bucket/"],
                archive_root=directory,
                s3_client=client,
            )

            self.assertEqual(result["downloaded_object_count"], 1)
            self.assertEqual(client.get_calls, ["lake/history.parquet"])


if __name__ == "__main__":
    unittest.main()
