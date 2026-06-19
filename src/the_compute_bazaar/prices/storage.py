"""Storage helpers for local files and S3 object paths."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .schemas import GpuOffer, to_jsonable


def write_json(uri: str, value: Any) -> str:
    data = json.dumps(to_jsonable(value), indent=2, sort_keys=True).encode("utf-8")
    return write_bytes(uri, data, content_type="application/json")


def read_json(uri: str) -> Any:
    return json.loads(read_bytes(uri).decode("utf-8"))


def list_refs(uri_prefix: str, *, suffix: str = "") -> list[str]:
    """List local or S3 refs under a prefix."""
    if uri_prefix.startswith("s3://"):
        parsed = urlparse(uri_prefix.rstrip("/") + "/")
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("Listing s3:// paths requires boto3") from exc

        client = boto3.client("s3")
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
    refs = [str(path) for path in root.rglob(f"*{suffix}" if suffix else "*") if path.is_file()]
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
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("Writing s3:// paths requires the 'platform' extra: uv sync --extra platform") from exc

        kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        boto3.client("s3").put_object(**kwargs)
        return uri

    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def read_bytes(uri: str) -> bytes:
    if uri.startswith("s3://"):
        parsed = urlparse(uri)
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("Reading s3:// paths requires the 'platform' extra: uv sync --extra platform") from exc

        response = boto3.client("s3").get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
        return response["Body"].read()

    return Path(uri).read_bytes()


def write_offers_parquet(uri: str, offers: Iterable[GpuOffer]) -> str:
    return write_parquet_rows(uri, [offer.to_dict() for offer in offers])


def write_parquet_rows(uri: str, rows: Iterable[Mapping[str, Any]]) -> str:
    materialized = [_normalize_parquet_value(dict(row)) for row in rows]
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Writing Parquet requires the 'platform' extra: uv sync --extra platform") from exc

    table = pa.Table.from_pylist(materialized)
    if uri.startswith("s3://"):
        try:
            import pyarrow.fs as pafs
        except ImportError as exc:
            raise RuntimeError("Writing Parquet to S3 requires pyarrow filesystem support") from exc

        parsed = urlparse(uri)
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        filesystem = pafs.S3FileSystem(region=region) if region else pafs.S3FileSystem()
        with filesystem.open_output_stream(f"{parsed.netloc}/{parsed.path.lstrip('/')}") as sink:
            pq.write_table(table, sink)
        return uri

    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return str(path)


def date_partition(root: str, *, provider: str, observed_date: str, run_id: str, filename: str) -> str:
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
        return {str(key): _normalize_parquet_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_normalize_parquet_value(child) for child in value]
    return value
