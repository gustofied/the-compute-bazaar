"""DataFusion helpers for GPU market benchmarks."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlparse

from .sql_models import read_sql
from .storage import resolve_read_uri


DEFAULT_MARKET_SUMMARY_SQL = read_sql("queries/silver_market_summary.sql")


def query_parquet(
    *,
    parquet_uri: str,
    sql: str,
    table_name: str = "gpu_offers",
) -> list[dict[str, Any]]:
    try:
        import pyarrow as pa
        from datafusion import SessionContext
    except ImportError as exc:
        raise RuntimeError("DataFusion queries require the project dependencies: uv sync") from exc

    ctx = SessionContext()
    parquet_uri = resolve_read_uri(parquet_uri)
    _register_object_stores(ctx, [parquet_uri])
    ctx.register_parquet(table_name, parquet_uri)
    batches = ctx.sql(sql).collect()
    if not batches:
        return []
    return pa.Table.from_batches(batches).to_pylist()


def query_market_summary(
    *, parquet_uri: str, limit: int | None = None
) -> list[dict[str, Any]]:
    sql = DEFAULT_MARKET_SUMMARY_SQL
    if limit is not None:
        sql = f"{sql.rstrip()}\nlimit {int(limit)}"
    return query_parquet(parquet_uri=parquet_uri, table_name="gpu_offers", sql=sql)


def query_tables(*, tables: Mapping[str, str], sql: str) -> list[dict[str, Any]]:
    try:
        import pyarrow as pa
        from datafusion import SessionContext
    except ImportError as exc:
        raise RuntimeError("DataFusion queries require the project dependencies: uv sync") from exc

    ctx = SessionContext()
    resolved_tables = {name: resolve_read_uri(uri) for name, uri in tables.items()}
    _register_object_stores(ctx, resolved_tables.values())
    for table_name, parquet_uri in resolved_tables.items():
        ctx.register_parquet(table_name, parquet_uri)
    batches = ctx.sql(sql).collect()
    if not batches:
        return []
    return pa.Table.from_batches(batches).to_pylist()


def _register_object_stores(ctx: Any, uris: Iterable[str]) -> None:
    s3_buckets = {urlparse(uri).netloc for uri in uris if uri.startswith("s3://")}
    if not s3_buckets:
        return

    try:
        import boto3
        from datafusion.object_store import AmazonS3
    except ImportError as exc:
        raise RuntimeError("Querying s3:// paths requires boto3 and DataFusion S3 support") from exc

    session = boto3.Session(
        profile_name=os.getenv("AWS_PROFILE"),
        region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
    )
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials available for DataFusion S3 query")

    frozen = credentials.get_frozen_credentials()
    region = session.region_name or "us-east-1"
    for bucket in sorted(s3_buckets):
        kwargs: dict[str, Any] = {
            "bucket_name": bucket,
            "region": region,
            "access_key_id": frozen.access_key,
            "secret_access_key": frozen.secret_key,
        }
        if frozen.token:
            kwargs["session_token"] = frozen.token
        ctx.register_object_store("s3://", AmazonS3(**kwargs), host=bucket)
