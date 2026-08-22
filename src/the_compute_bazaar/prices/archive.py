"""Content-addressed local archives of the Compute Bazaar S3 data estate."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

ARCHIVE_SCHEMA = "compute_bazaar_cloud_archive_v1"
CHUNK_SIZE = 1024 * 1024


def default_s3_archive_roots() -> tuple[str, ...]:
    """Return one bucket-wide root inferred from configured operational roots."""
    configured = [
        os.getenv("COMPUTE_BAZAAR_RAW_ROOT"),
        os.getenv("COMPUTE_BAZAAR_LAKE_ROOT"),
        os.getenv("COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT"),
    ]
    parsed = [urlparse(value) for value in configured if value and value.startswith("s3://")]
    buckets = {item.netloc for item in parsed if item.netloc}
    if not buckets:
        raise RuntimeError(
            "No S3 operational root is configured; provide --source-root s3://BUCKET/"
        )
    if len(buckets) != 1:
        raise RuntimeError("Configured operational roots span multiple S3 buckets")
    return (f"s3://{next(iter(buckets))}/",)


def create_s3_archive(
    *,
    source_roots: Sequence[str],
    archive_root: str | Path,
    workers: int = 8,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    """Mirror current S3 objects into immutable blobs plus a replayable key tree."""
    if not source_roots:
        raise ValueError("At least one S3 source root is required")
    if workers < 1:
        raise ValueError("workers must be at least 1")

    root = Path(archive_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    client = s3_client or _new_s3_client()
    sources = _normalize_source_roots(source_roots)
    listed = _list_current_objects(client, sources)
    previous = _read_optional_manifest(root / "latest-manifest.json")
    previous_by_identity = {
        (str(row.get("bucket")), str(row.get("key"))): row
        for row in previous.get("objects", [])
        if isinstance(row, Mapping)
    }

    downloaded = 0
    reused = 0
    object_rows: list[dict[str, Any]] = []
    failures: list[str] = []

    def archive_one(source: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        identity = (source["bucket"], source["key"])
        prior = previous_by_identity.get(identity)
        if prior and _can_reuse(root, source, prior):
            _materialize_current(root, source["bucket"], source["key"], str(prior["sha256"]))
            return {**source, "sha256": str(prior["sha256"])}, False
        materialized_digest = _materialized_digest(root, source)
        if materialized_digest:
            return {**source, "sha256": materialized_digest}, False

        digest = _download_blob(client, root, source)
        _materialize_current(root, source["bucket"], source["key"], digest)
        return {**source, "sha256": digest}, True

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="s3-archive") as pool:
        futures = {pool.submit(archive_one, source): source for source in listed}
        for future in as_completed(futures):
            source = futures[future]
            try:
                row, was_downloaded = future.result()
            except Exception as exc:  # noqa: BLE001 - preserve all failures in one report.
                failures.append(f"s3://{source['bucket']}/{source['key']}: {exc}")
                continue
            object_rows.append(row)
            if was_downloaded:
                downloaded += 1
            else:
                reused += 1

    if failures:
        raise RuntimeError(
            f"Cloud archive failed for {len(failures)} object(s): " + "; ".join(failures[:5])
        )

    object_rows.sort(key=lambda row: (row["bucket"], row["key"]))
    _prune_materialized_objects(
        root,
        previous_rows=previous.get("objects", []),
        current_rows=object_rows,
        source_roots=sources,
    )
    archive_id = datetime.now(timezone.utc).strftime("archive-%Y%m%dT%H%M%S%fZ")
    manifest = {
        "schema": ARCHIVE_SCHEMA,
        "archive_id": archive_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_roots": list(sources),
        "version_scope": "current_objects_only",
        "object_count": len(object_rows),
        "total_bytes": sum(int(row["size"]) for row in object_rows),
        "downloaded_object_count": downloaded,
        "reused_object_count": reused,
        "objects": object_rows,
    }
    _write_json_atomic(root / "latest-manifest.json", manifest)
    _write_json_atomic(root / "snapshots" / f"{archive_id}.json", manifest)
    _write_offline_env(root, sources)
    return {
        key: value
        for key, value in manifest.items()
        if key != "objects"
    } | {
        "archive_root": str(root),
        "manifest_path": str(root / "latest-manifest.json"),
        "offline_env_path": str(root / "offline.env"),
    }


def verify_s3_archive(
    *,
    archive_root: str | Path,
    workers: int = 8,
) -> dict[str, Any]:
    """Verify every materialized archive object against its SHA-256 digest."""
    root = Path(archive_root).expanduser().resolve()
    manifest_path = root / "latest-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != ARCHIVE_SCHEMA:
        raise ValueError(f"Unsupported archive schema in {manifest_path}")

    rows = [dict(row) for row in manifest.get("objects", [])]

    def verify_one(row: dict[str, Any]) -> str | None:
        path = archive_object_path(root, str(row["bucket"]), str(row["key"]))
        if not path.is_file():
            return f"missing: {path}"
        if path.stat().st_size != int(row["size"]):
            return f"size mismatch: {path}"
        digest = _sha256_file(path)
        if digest != row["sha256"]:
            return f"checksum mismatch: {path}"
        return None

    problems: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="archive-verify") as pool:
        for problem in pool.map(verify_one, rows):
            if problem:
                problems.append(problem)

    result = {
        "schema": ARCHIVE_SCHEMA,
        "archive_id": manifest.get("archive_id"),
        "archive_root": str(root),
        "object_count": len(rows),
        "total_bytes": sum(int(row["size"]) for row in rows),
        "valid": not problems,
        "problem_count": len(problems),
        "problems": problems[:100],
    }
    if problems:
        raise RuntimeError(json.dumps(result, indent=2, sort_keys=True))
    return result


def archive_object_path(root: Path, bucket: str, key: str) -> Path:
    """Return the materialized path for a normal S3 object key."""
    parts = PurePosixPath(key).parts
    if not parts or key.endswith("/") or any(part in {"", ".", ".."} for part in parts):
        marker = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return root / "objects" / bucket / ".s3-object-markers" / marker
    if any(len(os.fsencode(part)) > 240 for part in parts):
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return root / "objects" / bucket / ".s3-long-keys" / digest[:2] / digest
    return root / "objects" / bucket / Path(*parts)


def _normalize_source_roots(source_roots: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in source_roots:
        parsed = urlparse(value)
        if parsed.scheme != "s3" or not parsed.netloc:
            raise ValueError(f"Archive source must be an s3:// URI: {value}")
        prefix = parsed.path.lstrip("/")
        normalized.append(f"s3://{parsed.netloc}/{prefix}")
    return tuple(sorted(set(normalized)))


def _list_current_objects(client: Any, source_roots: Sequence[str]) -> list[dict[str, Any]]:
    by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for source_root in source_roots:
        parsed = urlparse(source_root)
        prefix = parsed.path.lstrip("/")
        continuation_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": parsed.netloc, "Prefix": prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = client.list_objects_v2(**kwargs)
            for item in response.get("Contents", []):
                key = str(item["Key"])
                modified = item.get("LastModified")
                row = {
                    "bucket": parsed.netloc,
                    "key": key,
                    "size": int(item.get("Size") or 0),
                    "etag": str(item.get("ETag") or "").strip('"'),
                    "last_modified": (
                        modified.isoformat() if hasattr(modified, "isoformat") else str(modified or "")
                    ),
                    "storage_class": str(item.get("StorageClass") or "STANDARD"),
                }
                by_identity[(parsed.netloc, key)] = row
            if not response.get("IsTruncated"):
                break
            continuation_token = str(response.get("NextContinuationToken") or "")
    return sorted(by_identity.values(), key=lambda row: (row["bucket"], row["key"]))


def _can_reuse(
    root: Path,
    source: Mapping[str, Any],
    prior: Mapping[str, Any],
) -> bool:
    if int(prior.get("size") or -1) != int(source["size"]):
        return False
    if str(prior.get("etag") or "") != str(source.get("etag") or ""):
        return False
    digest = str(prior.get("sha256") or "")
    if len(digest) != 64:
        return False
    blob = _blob_path(root, digest)
    return (
        blob.is_file()
        and blob.stat().st_size == int(source["size"])
        and _matches_single_part_etag(blob, str(source.get("etag") or ""))
    )


def _materialized_digest(root: Path, source: Mapping[str, Any]) -> str | None:
    """Recover an interrupted first archive from its already materialized files."""
    path = archive_object_path(root, str(source["bucket"]), str(source["key"]))
    if not path.is_file() or path.stat().st_size != int(source["size"]):
        return None
    etag = str(source.get("etag") or "")
    if not _is_single_part_etag(etag) or not _matches_single_part_etag(path, etag):
        return None
    digest = _sha256_file(path)
    blob = _blob_path(root, digest)
    if not blob.is_file() or blob.stat().st_size != int(source["size"]):
        return None
    return digest


def _download_blob(client: Any, root: Path, source: Mapping[str, Any]) -> str:
    temp_root = root / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix="object-", dir=temp_root)
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "wb") as destination:
            request = {"Bucket": source["bucket"], "Key": source["key"]}
            if source.get("etag"):
                request["IfMatch"] = f'"{source["etag"]}"'
            response = client.get_object(**request)
            response_etag = str(response.get("ETag") or "").strip('"')
            if response_etag and response_etag != source.get("etag"):
                raise IOError("S3 object changed after it was listed")
            body = response["Body"]
            while chunk := body.read(CHUNK_SIZE):
                destination.write(chunk)
                digest.update(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if Path(temp_name).stat().st_size != int(source["size"]):
            raise IOError("downloaded size does not match S3 listing")
        checksum = digest.hexdigest()
        blob = _blob_path(root, checksum)
        blob.parent.mkdir(parents=True, exist_ok=True)
        if blob.exists():
            Path(temp_name).unlink()
        else:
            os.replace(temp_name, blob)
        return checksum
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _materialize_current(root: Path, bucket: str, key: str, digest: str) -> None:
    blob = _blob_path(root, digest)
    destination = archive_object_path(root, bucket, key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        try:
            if os.path.samefile(destination, blob):
                return
        except OSError:
            pass
        destination.unlink()
    try:
        os.link(blob, destination)
    except OSError:
        shutil.copy2(blob, destination)


def _prune_materialized_objects(
    root: Path,
    *,
    previous_rows: Iterable[Mapping[str, Any]],
    current_rows: Iterable[Mapping[str, Any]],
    source_roots: Sequence[str],
) -> None:
    current = {
        (str(row.get("bucket")), str(row.get("key"))) for row in current_rows
    }
    scopes = [
        (urlparse(source).netloc, urlparse(source).path.lstrip("/"))
        for source in source_roots
    ]
    for row in previous_rows:
        bucket = str(row.get("bucket") or "")
        key = str(row.get("key") or "")
        if (bucket, key) in current:
            continue
        if not any(
            bucket == scope_bucket and key.startswith(scope_prefix)
            for scope_bucket, scope_prefix in scopes
        ):
            continue
        archive_object_path(root, bucket, key).unlink(missing_ok=True)


def _blob_path(root: Path, digest: str) -> Path:
    return root / "blobs" / "sha256" / digest[:2] / digest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _matches_single_part_etag(path: Path, etag: str) -> bool:
    """Verify normal S3 ETags; multipart ETags are not content hashes."""
    normalized = etag.strip('"').lower()
    if not _is_single_part_etag(normalized):
        return True
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest() == normalized


def _is_single_part_etag(etag: str) -> bool:
    normalized = etag.strip('"').lower()
    return len(normalized) == 32 and all(
        value in "0123456789abcdef" for value in normalized
    )


def _read_optional_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if payload.get("schema") == ARCHIVE_SCHEMA else {}


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_offline_env(root: Path, sources: Iterable[str]) -> None:
    buckets = sorted({urlparse(source).netloc for source in sources})
    lines = [
        "# Source this file to replay archived S3 reads without AWS access.",
        f"export COMPUTE_BAZAAR_S3_MIRROR_ROOT={json.dumps(str(root / 'objects'))}",
        "export COMPUTE_BAZAAR_S3_MIRROR_STRICT=1",
    ]
    if len(buckets) == 1:
        bucket = buckets[0]
        lines.extend(
            [
                f"export COMPUTE_BAZAAR_RAW_ROOT=s3://{bucket}/raw",
                f"export COMPUTE_BAZAAR_LAKE_ROOT=s3://{bucket}/lake",
                f"export COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT=s3://{bucket}/dashboard/compute-bazaar",
                "export COMPUTE_BAZAAR_DASHBOARD_SOURCE=s3",
            ]
        )
    (root / "offline.env").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _new_s3_client() -> Any:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("Cloud archiving requires boto3") from exc
    session = boto3.Session(
        profile_name=os.getenv("AWS_PROFILE"),
        region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
    )
    return session.client(
        "s3",
        config=Config(
            connect_timeout=10,
            read_timeout=120,
            retries={"max_attempts": 8, "mode": "adaptive"},
        ),
    )
