"""Storage helpers for local files and S3 object paths."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from .schemas import GpuOffer, to_jsonable


class LeaseBusyError(RuntimeError):
    """Raised when another process owns a mutable dataset's publication lease."""


@contextmanager
def exclusive_lease(uri: str, *, ttl_seconds: int = 1800) -> Iterator[None]:
    """Serialize a short read/merge/publish transaction locally or in S3."""
    if ttl_seconds < 60:
        raise ValueError("Lease TTL must be at least 60 seconds")
    if uri.startswith("s3://"):
        with _s3_exclusive_lease(uri, ttl_seconds=ttl_seconds):
            yield
        return

    import fcntl

    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LeaseBusyError(f"Publication lease is already held: {uri}") from exc
        acquired = True
        _write_local_lease(descriptor, state="active")
        yield
    finally:
        try:
            if acquired:
                _write_local_lease(descriptor, state="released")
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def write_json(uri: str, value: Any) -> str:
    data = json.dumps(to_jsonable(value), indent=2, sort_keys=True).encode("utf-8")
    return write_bytes(uri, data, content_type="application/json")


def read_json(uri: str) -> Any:
    return json.loads(read_bytes(uri).decode("utf-8"))


def read_optional_json(uri: str) -> dict[str, Any]:
    """Read a JSON object, returning an empty mapping only when it is absent."""
    if not uri.startswith("s3://") and not Path(uri).exists():
        return {}
    try:
        value = read_json(uri)
    except Exception as exc:  # noqa: BLE001 - botocore is an optional dependency.
        response = getattr(exc, "response", {})
        code = response.get("Error", {}).get("Code")
        if isinstance(exc, (FileNotFoundError, OSError)) or code in {
            "NoSuchKey",
            "NoSuchObject",
            "404",
        }:
            return {}
        raise
    return dict(value) if isinstance(value, Mapping) else {}


def list_refs(uri_prefix: str, *, suffix: str = "") -> list[str]:
    """List local or S3 refs under a prefix."""
    if uri_prefix.startswith("s3://"):
        parsed = urlparse(uri_prefix.rstrip("/") + "/")
        client = _s3_client()
        prefix = parsed.path.lstrip("/")
        refs: list[str] = []
        continuation_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": parsed.netloc, "Prefix": prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = client.list_objects_v2(**kwargs)
            for row in response.get("Contents", []):
                key = str(row["Key"])
                ref = f"s3://{parsed.netloc}/{key}"
                if not suffix or ref.endswith(suffix):
                    refs.append(ref)
            if not response.get("IsTruncated"):
                return sorted(refs)
            continuation_token = str(response.get("NextContinuationToken") or "")

    root = Path(uri_prefix)
    if not root.exists():
        return []
    refs = [
        str(path)
        for path in root.rglob(f"*{suffix}" if suffix else "*")
        if path.is_file()
    ]
    return sorted(refs)


def write_jsonl(uri: str, rows: Iterable[Any]) -> str:
    payload = b"\n".join(
        json.dumps(to_jsonable(row), sort_keys=True).encode("utf-8") for row in rows
    )
    if payload:
        payload += b"\n"
    return write_bytes(uri, payload, content_type="application/x-ndjson")


def write_bytes(uri: str, data: bytes, *, content_type: str | None = None) -> str:
    if uri.startswith("s3://"):
        parsed = urlparse(uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        _s3_client().put_object(**kwargs)
        return uri

    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def read_bytes(uri: str) -> bytes:
    if uri.startswith("s3://"):
        parsed = urlparse(uri)
        response = _s3_client().get_object(
            Bucket=parsed.netloc, Key=parsed.path.lstrip("/")
        )
        return response["Body"].read()

    return Path(uri).read_bytes()


@lru_cache(maxsize=1)
def _s3_client() -> Any:
    """Create an S3 client with bounded waits for dashboard/export paths."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("Reading or writing s3:// paths requires boto3") from exc

    connect_timeout = int(os.getenv("COMPUTE_BAZAAR_S3_CONNECT_TIMEOUT", "5"))
    read_timeout = int(os.getenv("COMPUTE_BAZAAR_S3_READ_TIMEOUT", "10"))
    max_attempts = int(os.getenv("COMPUTE_BAZAAR_S3_MAX_ATTEMPTS", "3"))
    config = Config(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        retries={"max_attempts": max_attempts, "mode": "standard"},
    )
    return boto3.client("s3", config=config)


@contextmanager
def _s3_exclusive_lease(uri: str, *, ttl_seconds: int) -> Iterator[None]:
    from botocore.exceptions import ClientError

    parsed = urlparse(uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    client = _s3_client()
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    active_payload = _lease_payload(
        token=token,
        state="active",
        acquired_at=now,
        expires_at=expires_at,
    )

    etag: str
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {
            "NoSuchKey",
            "NoSuchObject",
            "404",
        }:
            raise
        try:
            response = client.put_object(
                Bucket=bucket,
                Key=key,
                Body=active_payload,
                ContentType="application/json",
                IfNoneMatch="*",
            )
        except ClientError as put_exc:
            if (
                put_exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                == 412
            ):
                raise LeaseBusyError(
                    f"Publication lease was acquired concurrently: {uri}"
                ) from put_exc
            raise
        etag = str(response["ETag"])
    else:
        existing_etag = str(response["ETag"])
        existing = json.loads(response["Body"].read().decode("utf-8"))
        existing_expiry = datetime.fromisoformat(str(existing["expires_at"]))
        if existing_expiry > now:
            raise LeaseBusyError(
                f"Publication lease is held until {existing_expiry.isoformat()}: {uri}"
            )
        try:
            response = client.put_object(
                Bucket=bucket,
                Key=key,
                Body=active_payload,
                ContentType="application/json",
                IfMatch=existing_etag,
            )
        except ClientError as put_exc:
            if (
                put_exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                == 412
            ):
                raise LeaseBusyError(
                    f"Publication lease was renewed concurrently: {uri}"
                ) from put_exc
            raise
        etag = str(response["ETag"])

    try:
        yield
    finally:
        released_at = datetime.now(timezone.utc)
        released_payload = _lease_payload(
            token=token,
            state="released",
            acquired_at=now,
            expires_at=released_at,
        )
        try:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=released_payload,
                ContentType="application/json",
                IfMatch=etag,
            )
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise


def _lease_payload(
    *,
    token: str,
    state: str,
    acquired_at: datetime,
    expires_at: datetime,
) -> bytes:
    return json.dumps(
        {
            "token": token,
            "state": state,
            "acquired_at": acquired_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        },
        sort_keys=True,
    ).encode("utf-8")


def _write_local_lease(descriptor: int, *, state: str) -> None:
    now = datetime.now(timezone.utc)
    payload = _lease_payload(
        token=str(os.getpid()),
        state=state,
        acquired_at=now,
        expires_at=now,
    )
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    os.write(descriptor, payload)
    os.fsync(descriptor)


def write_offers_parquet(uri: str, offers: Iterable[GpuOffer]) -> str:
    return write_parquet_rows(uri, [offer.to_dict() for offer in offers])


def write_parquet_rows(uri: str, rows: Iterable[Mapping[str, Any]]) -> str:
    materialized = [_normalize_parquet_value(dict(row)) for row in rows]
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "Writing Parquet requires the 'platform' extra: uv sync --extra platform"
        ) from exc

    table = pa.Table.from_pylist(materialized)
    if uri.startswith("s3://"):
        try:
            import pyarrow.fs as pafs
        except ImportError as exc:
            raise RuntimeError(
                "Writing Parquet to S3 requires pyarrow filesystem support"
            ) from exc

        parsed = urlparse(uri)
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        filesystem = pafs.S3FileSystem(region=region) if region else pafs.S3FileSystem()
        with filesystem.open_output_stream(
            f"{parsed.netloc}/{parsed.path.lstrip('/')}"
        ) as sink:
            pq.write_table(table, sink)
        return uri

    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return str(path)


def read_parquet_rows(uri: str) -> list[dict[str, Any]]:
    """Read a local or S3 Parquet object into plain row dictionaries."""
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "Reading Parquet requires the 'platform' extra: uv sync --extra platform"
        ) from exc

    if uri.startswith("s3://"):
        try:
            import pyarrow.fs as pafs
        except ImportError as exc:
            raise RuntimeError(
                "Reading Parquet from S3 requires pyarrow filesystem support"
            ) from exc

        parsed = urlparse(uri)
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        filesystem = pafs.S3FileSystem(region=region) if region else pafs.S3FileSystem()
        table = pq.read_table(
            f"{parsed.netloc}/{parsed.path.lstrip('/')}",
            filesystem=filesystem,
        )
    else:
        table = pq.read_table(Path(uri))
    return [dict(row) for row in table.to_pylist()]


def date_partition(
    root: str, *, provider: str, observed_date: str, run_id: str, filename: str
) -> str:
    return "/".join(
        [
            root.rstrip("/"),
            f"provider={provider}",
            f"date={observed_date}",
            f"run_id={run_id}",
            filename,
        ]
    )


def table_partition(
    root: str,
    *,
    table: str,
    observed_date: str,
    provider: str | None,
    run_id: str,
    filename: str,
) -> str:
    parts = [
        root.rstrip("/"),
        table,
        f"date={observed_date}",
    ]
    if provider:
        parts.append(f"provider={provider}")
    parts.extend([f"run_id={run_id}", filename])
    return "/".join(parts)


def rows_from_dicts(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _normalize_parquet_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not value:
            return None
        return {
            str(key): _normalize_parquet_value(child) for key, child in value.items()
        }
    if isinstance(value, list):
        return [_normalize_parquet_value(child) for child in value]
    return value
