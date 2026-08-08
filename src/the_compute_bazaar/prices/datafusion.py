"""DataFusion execution boundary for compute-market Parquet tables."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlparse

from .storage import resolve_read_uri


TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DataFusionEngine:
    """Own one DataFusion session and its registered market tables."""

    def __init__(self, tables: Mapping[str, str] | None = None) -> None:
        try:
            import pyarrow as pa
            from datafusion import SessionConfig, SessionContext
        except ImportError as exc:
            raise RuntimeError(
                "DataFusion queries require the project dependencies: uv sync"
            ) from exc

        config = (
            SessionConfig().with_parquet_pruning(True).with_information_schema(True)
        )
        self._arrow = pa
        self._context = SessionContext(config)
        self._registered_buckets: set[str] = set()
        self._table_refs: dict[str, str] = {}
        if tables:
            self.register_tables(tables)

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._table_refs))

    def register_tables(self, tables: Mapping[str, str]) -> None:
        resolved = {
            _validated_table_name(name): resolve_read_uri(uri)
            for name, uri in tables.items()
        }
        duplicate_names = sorted(set(resolved) & set(self._table_refs))
        if duplicate_names:
            raise ValueError(
                f"DataFusion tables already registered: {', '.join(duplicate_names)}"
            )
        self._register_object_stores(resolved.values())
        for table_name, parquet_uri in resolved.items():
            self._context.register_parquet(table_name, parquet_uri)
            self._table_refs[table_name] = parquet_uri

    def deregister_tables(self, table_names: Iterable[str]) -> None:
        for table_name in table_names:
            name = _validated_table_name(table_name)
            self._context.deregister_table(name)
            self._table_refs.pop(name, None)

    def query(self, sql: str) -> list[dict[str, Any]]:
        return self.query_arrow(sql).to_pylist()

    def query_arrow(self, sql: str) -> Any:
        """Execute SQL and retain its Arrow schema, including for empty results."""
        if not sql.strip():
            raise ValueError("DataFusion SQL must not be empty")
        frame = self._context.sql(sql)
        batches = frame.collect()
        return self._arrow.Table.from_batches(batches, schema=frame.schema())

    def create_schema(self, schema_name: str) -> None:
        schema = _validated_table_name(schema_name)
        self._context.sql(f"create schema if not exists {schema}").collect()

    def create_view(self, schema_name: str, table_name: str, sql: str) -> None:
        schema = _validated_table_name(schema_name)
        table = _validated_table_name(table_name)
        if not sql.strip():
            raise ValueError("DataFusion view SQL must not be empty")
        self._context.sql(f"create view {schema}.{table} as {sql}").collect()

    def _register_object_stores(self, uris: Iterable[str]) -> None:
        s3_buckets = {
            urlparse(uri).netloc
            for uri in uris
            if uri.startswith("s3://")
            and urlparse(uri).netloc not in self._registered_buckets
        }
        if not s3_buckets:
            return

        try:
            import boto3
            from datafusion.object_store import AmazonS3
        except ImportError as exc:
            raise RuntimeError(
                "Querying s3:// paths requires boto3 and DataFusion S3 support"
            ) from exc

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
            self._context.register_object_store(
                "s3://", AmazonS3(**kwargs), host=bucket
            )
            self._registered_buckets.add(bucket)


def _validated_table_name(table_name: str) -> str:
    if not TABLE_NAME_PATTERN.fullmatch(table_name):
        raise ValueError(f"Invalid DataFusion table name: {table_name!r}")
    return table_name
