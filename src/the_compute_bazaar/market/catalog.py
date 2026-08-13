"""DataFusion catalog for the rebuilt market lake."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pyarrow as pa
from datafusion import SQLOptions, SessionConfig, SessionContext

from ..contracts import MARKET_LAKE_CONTRACT, require_contract
from .pipeline import MarketRunResult


class MarketCatalog:
    def __init__(
        self,
        silver_refs: list[str],
    ) -> None:
        if not silver_refs:
            raise ValueError("At least one Silver GPU-offer object is required")
        self.context = SessionContext(
            SessionConfig().with_parquet_pruning(True).with_information_schema(True)
        )
        self._register_s3(silver_refs)
        frame = self.context.read_parquet(silver_refs[0])
        for ref in silver_refs[1:]:
            frame = frame.union_by_name(self.context.read_parquet(ref))
        self.context.register_view("_gpu_offers", frame)
        self.context.sql("create schema silver").collect()
        self.context.sql(
            "create view silver.gpu_offers as select * from _gpu_offers"
        ).collect()
        self.options = (
            SQLOptions()
            .with_allow_ddl(False)
            .with_allow_dml(False)
            .with_allow_statements(False)
        )

    @classmethod
    def from_lake(cls, lake_root: str) -> MarketCatalog:
        manifest = read_market_manifest(lake_root)
        refs = [
            str(ref)
            for ref in dict(manifest.get("source_normalized_refs") or {}).values()
            if ref
        ]
        catalog = cls(refs)
        catalog.manifest = manifest
        return catalog

    @classmethod
    def from_runs(cls, *results: MarketRunResult) -> MarketCatalog:
        return cls(
            [result.run.silver_ref for result in results if result.run.silver_ref]
        )

    def rows(self, sql: str) -> list[dict[str, Any]]:
        return self.arrow(sql).to_pylist()

    def arrow(self, sql: str, *, limit: int | None = None) -> pa.Table:
        if not sql.strip():
            raise ValueError("DataFusion SQL must not be empty")
        frame = self.context.sql(sql, options=self.options)
        if limit is not None:
            frame = frame.limit(limit)
        batches = frame.collect()
        return pa.Table.from_batches(batches, schema=frame.schema())

    def query(self, sql: str, *, limit: int = 100) -> dict[str, Any]:
        table, selected_limit, truncated = self.query_arrow(sql, limit=limit)
        return {
            "run": self.run(),
            "limit": selected_limit,
            "row_count": table.num_rows,
            "truncated": truncated,
            "rows": table.to_pylist(),
        }

    def query_arrow(self, sql: str, *, limit: int = 100) -> tuple[pa.Table, int, bool]:
        if limit < 1:
            raise ValueError("DataFusion query limit must be positive")
        table = self.arrow(sql, limit=limit + 1)
        truncated = table.num_rows > limit
        return (table.slice(0, limit) if truncated else table, limit, truncated)

    def tables(self) -> dict[str, Any]:
        rows = self.rows(
            """
select table_schema as layer, table_name, table_type
from information_schema.tables
where table_schema in ('silver', 'gold')
order by table_schema, table_name
"""
        )
        silver_counts = dict(
            getattr(self, "manifest", {}).get("silver_row_counts") or {}
        )
        for row in rows:
            name = str(row["table_name"])
            row["row_count"] = silver_counts.get(name)
        return {"run": self.run(), "tables": rows}

    def describe(self, table_ref: str) -> dict[str, Any]:
        try:
            layer, table = table_ref.split(".", 1)
        except ValueError as exc:
            raise ValueError("Table must be silver.NAME") from exc
        if layer != "silver" or not table.isidentifier():
            raise ValueError("Table must be silver.NAME")
        rows = self.rows(
            f"""
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = '{layer}' and table_name = '{table}'
order by ordinal_position
"""
        )
        if not rows:
            raise KeyError(f"Unknown catalog table: {table_ref}")
        return {"run": self.run(), "table": table_ref, "columns": rows}

    def run(self) -> dict[str, Any]:
        manifest = getattr(self, "manifest", {})
        return {
            "run_id": manifest.get("run_id"),
            "observed_at": manifest.get("observed_at"),
            "provider_scope": manifest.get("provider_scope") or [],
        }

    def _register_s3(self, refs: list[str]) -> None:
        buckets = {urlparse(ref).netloc for ref in refs if ref.startswith("s3://")}
        if not buckets:
            return
        try:
            import boto3
            from datafusion.object_store import AmazonS3
        except ImportError as exc:
            raise RuntimeError("S3 market catalogs require the s3 extra") from exc
        session = boto3.Session()
        credentials = session.get_credentials()
        if credentials is None:
            raise RuntimeError("No AWS credentials available for the market catalog")
        frozen = credentials.get_frozen_credentials()
        for bucket in buckets:
            options = {
                "bucket_name": bucket,
                "region": session.region_name or "us-east-1",
                "access_key_id": frozen.access_key,
                "secret_access_key": frozen.secret_key,
            }
            if frozen.token:
                options["session_token"] = frozen.token
            self.context.register_object_store(
                "s3://", AmazonS3(**options), host=bucket
            )


def market_manifest_ref(lake_root: str) -> str:
    return f"{lake_root.rstrip('/')}/_manifests/market/latest.json"


def read_market_manifest(lake_root: str) -> dict[str, Any]:
    ref = market_manifest_ref(lake_root)
    if "://" in ref:
        raise ValueError("Remote rebuilt market lakes are not supported yet")
    manifest = json.loads(Path(ref).read_text(encoding="utf-8"))
    require_contract(manifest, contract=MARKET_LAKE_CONTRACT)
    if manifest.get("ref_base") == "lake_root":
        root = Path(lake_root).expanduser().resolve()
        manifest["source_normalized_refs"] = {
            name: str((root / str(value)).resolve())
            for name, value in dict(
                manifest.get("source_normalized_refs") or {}
            ).items()
        }
    return manifest
