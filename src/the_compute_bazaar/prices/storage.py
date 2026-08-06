"""Storage helpers for local files and S3 object paths."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .schemas import GpuOffer, to_jsonable


def s3_mirror_path(uri: str, *, require_exists: bool = True) -> Path | None:
    """Resolve an S3 URI through an optional read-only local mirror."""
    mirror_root = os.getenv("COMPUTE_BAZAAR_S3_MIRROR_ROOT")
    if not mirror_root or not uri.startswith("s3://"):
        return None
    parsed = urlparse(uri)
    key = parsed.path.lstrip("/")
    if key:
        from .archive import archive_object_path

        path = archive_object_path(Path(mirror_root).resolve().parent, parsed.netloc, key)
    else:
        path = Path(mirror_root).resolve() / parsed.netloc
    if not require_exists or path.exists():
        return path
    if os.getenv("COMPUTE_BAZAAR_S3_MIRROR_STRICT", "").lower() in {"1", "true", "yes"}:
        raise FileNotFoundError(f"S3 object is absent from the local mirror: {uri}")
    return None


def resolve_read_uri(uri: str) -> str:
    """Return a local mirror path when configured, otherwise the original URI."""
    mirrored = s3_mirror_path(uri)
    return str(mirrored) if mirrored else uri


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
        mirrored_prefix = s3_mirror_path(uri_prefix.rstrip("/"), require_exists=False)
        if mirrored_prefix:
            parsed = urlparse(uri_prefix.rstrip("/") + "/")
            manifest_path = (
                Path(os.environ["COMPUTE_BAZAAR_S3_MIRROR_ROOT"]).resolve().parent
                / "latest-manifest.json"
            )
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                prefix = parsed.path.lstrip("/")
                return sorted(
                    f"s3://{parsed.netloc}/{row['key']}"
                    for row in manifest.get("objects", [])
                    if row.get("bucket") == parsed.netloc
                    and str(row.get("key") or "").startswith(prefix)
                    and (not suffix or str(row.get("key") or "").endswith(suffix))
                )
        if mirrored_prefix and mirrored_prefix.exists():
            refs = []
            for path in mirrored_prefix.rglob(f"*{suffix}" if suffix else "*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(
                    Path(os.environ["COMPUTE_BAZAAR_S3_MIRROR_ROOT"]).resolve()
                    / parsed.netloc
                )
                refs.append(f"s3://{parsed.netloc}/{relative.as_posix()}")
            return sorted(refs)
        if mirrored_prefix and os.getenv("COMPUTE_BAZAAR_S3_MIRROR_STRICT", "").lower() in {"1", "true", "yes"}:
            return []
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


def write_bytes(
    uri: str,
    data: bytes,
    *,
    content_type: str | None = None,
    cache_control: str | None = None,
) -> str:
    if uri.startswith("s3://"):
        parsed = urlparse(uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        if cache_control:
            kwargs["CacheControl"] = cache_control
        _s3_client().put_object(**kwargs)
        return uri

    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def delete_uri(uri: str) -> None:
    """Delete one retired local or S3 publication if it exists."""
    if uri.startswith("s3://"):
        parsed = urlparse(uri)
        _s3_client().delete_object(
            Bucket=parsed.netloc,
            Key=parsed.path.lstrip("/"),
        )
        return
    Path(uri).unlink(missing_ok=True)


def read_bytes(uri: str) -> bytes:
    uri = resolve_read_uri(uri)
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

    uri = resolve_read_uri(uri)
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
