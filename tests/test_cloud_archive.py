from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from the_compute_bazaar.prices.archive import create_s3_archive, verify_s3_archive
from the_compute_bazaar.prices.datafusion import query_parquet
from the_compute_bazaar.prices.storage import list_refs, read_bytes


class FakeS3Client:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.get_calls: list[str] = []

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        prefix = str(kwargs.get("Prefix") or "")
        rows = []
        for key, value in sorted(self.objects.items()):
            if key.startswith(prefix):
                rows.append(
                    {
                        "Key": key,
                        "Size": len(value),
                        "ETag": f'"{hashlib.md5(value).hexdigest()}"',  # noqa: S324 - S3 fixture ETag.
                        "LastModified": datetime(2026, 8, 2, tzinfo=timezone.utc),
                        "StorageClass": "STANDARD",
                    }
                )
        return {"Contents": rows, "IsTruncated": False}

    def get_object(
        self, *, Bucket: str, Key: str, IfMatch: str | None = None
    ) -> dict[str, object]:
        del Bucket
        value = self.objects[Key]
        etag = hashlib.md5(value).hexdigest()  # noqa: S324 - S3 fixture ETag.
        if IfMatch and IfMatch.strip('"') != etag:
            raise RuntimeError("precondition failed")
        self.get_calls.append(Key)
        return {"Body": io.BytesIO(value), "ETag": f'"{etag}"'}


class CloudArchiveTests(unittest.TestCase):
    def test_archive_is_checksummed_replayable_and_resumable(self) -> None:
        parquet_buffer = io.BytesIO()
        pq.write_table(pa.Table.from_pylist([{"gpu": "H100", "price": 2.5}]), parquet_buffer)
        client = FakeS3Client(
            {
                "raw/provider=prime/run.json": b'{"offers": [1]}',
                "lake/gold/fact.parquet": parquet_buffer.getvalue(),
                "dashboard/compute-bazaar/manifest.json": b'{"status": "ok"}',
            }
        )

        with tempfile.TemporaryDirectory() as directory:
            result = create_s3_archive(
                source_roots=["s3://market-bucket/"],
                archive_root=directory,
                workers=2,
                s3_client=client,
            )
            self.assertEqual(result["object_count"], 3)
            self.assertEqual(result["downloaded_object_count"], 3)
            self.assertTrue(verify_s3_archive(archive_root=directory)["valid"])

            mirror = str(Path(directory) / "objects")
            with patch.dict(
                os.environ,
                {
                    "COMPUTE_BAZAAR_S3_MIRROR_ROOT": mirror,
                    "COMPUTE_BAZAAR_S3_MIRROR_STRICT": "1",
                },
                clear=False,
            ):
                self.assertEqual(
                    read_bytes("s3://market-bucket/raw/provider=prime/run.json"),
                    b'{"offers": [1]}',
                )
                self.assertEqual(
                    list_refs("s3://market-bucket/dashboard", suffix=".json"),
                    ["s3://market-bucket/dashboard/compute-bazaar/manifest.json"],
                )
                rows = query_parquet(
                    parquet_uri="s3://market-bucket/lake/gold/fact.parquet",
                    table_name="fact",
                    sql="select gpu, price from fact",
                )
                self.assertEqual(rows, [{"gpu": "H100", "price": 2.5}])

            client.get_calls.clear()
            second = create_s3_archive(
                source_roots=["s3://market-bucket/"],
                archive_root=directory,
                workers=2,
                s3_client=client,
            )
            self.assertEqual(second["downloaded_object_count"], 0)
            self.assertEqual(second["reused_object_count"], 3)
            self.assertEqual(client.get_calls, [])

            del client.objects["raw/provider=prime/run.json"]
            third = create_s3_archive(
                source_roots=["s3://market-bucket/"],
                archive_root=directory,
                workers=2,
                s3_client=client,
            )
            self.assertEqual(third["object_count"], 2)
            self.assertFalse(
                (
                    Path(directory)
                    / "objects/market-bucket/raw/provider=prime/run.json"
                ).exists()
            )
            snapshots = sorted((Path(directory) / "snapshots").glob("*.json"))
            self.assertEqual(len(snapshots), 3)

    def test_archive_materializes_overlong_s3_keys(self) -> None:
        long_component = "run_id=" + ("market-" * 45)
        key = f"lake/gold/date=2026-08-02/{long_component}/facts.parquet"
        client = FakeS3Client({key: b"parquet evidence"})
        with tempfile.TemporaryDirectory() as directory:
            create_s3_archive(
                source_roots=["s3://market-bucket/"],
                archive_root=directory,
                s3_client=client,
            )
            mirror = str(Path(directory) / "objects")
            with patch.dict(
                os.environ,
                {
                    "COMPUTE_BAZAAR_S3_MIRROR_ROOT": mirror,
                    "COMPUTE_BAZAAR_S3_MIRROR_STRICT": "1",
                },
                clear=False,
            ):
                self.assertEqual(
                    read_bytes(f"s3://market-bucket/{key}"), b"parquet evidence"
                )
                self.assertEqual(
                    list_refs("s3://market-bucket/lake", suffix=".parquet"),
                    [f"s3://market-bucket/{key}"],
                )

    def test_verify_detects_corruption(self) -> None:
        client = FakeS3Client({"raw/evidence.json": b"evidence"})
        with tempfile.TemporaryDirectory() as directory:
            create_s3_archive(
                source_roots=["s3://market-bucket/"],
                archive_root=directory,
                s3_client=client,
            )
            manifest = json.loads(
                (Path(directory) / "latest-manifest.json").read_text(encoding="utf-8")
            )
            row = manifest["objects"][0]
            path = Path(directory) / "objects" / row["bucket"] / row["key"]
            path.write_bytes(b"corrupt")
            with self.assertRaisesRegex(RuntimeError, "size mismatch"):
                verify_s3_archive(archive_root=directory)


if __name__ == "__main__":
    unittest.main()
