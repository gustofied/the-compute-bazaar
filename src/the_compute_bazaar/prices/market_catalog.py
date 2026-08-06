"""Logical Silver and Gold tables over the latest manifested market run."""

from __future__ import annotations

import re
from typing import Any

from .datafusion import DataFusionEngine
from .gold_manifest import read_latest_gold_manifest
from .query_catalog import bounded_query_limit, validate_catalog_sql, with_scratch_limit


TABLE_REF_PATTERN = re.compile(r"^(silver|gold)\.([A-Za-z_][A-Za-z0-9_]*)$")


class MarketDataCatalog:
    """Present manifested Parquet objects as stable DataFusion tables."""

    def __init__(self, *, lake_root: str) -> None:
        self.manifest = read_latest_gold_manifest(lake_root.rstrip("/"))
        self.engine = DataFusionEngine()
        self._register_silver()
        self._register_gold()

    def tables(self) -> dict[str, Any]:
        rows = self.engine.query(
            """
select table_schema as layer, table_name, table_type
from information_schema.tables
where table_schema in ('silver', 'gold')
order by table_schema, table_name
"""
        )
        row_counts = dict(self.manifest.get("row_counts") or {})
        for row in rows:
            row["row_count"] = (
                row_counts.get(str(row["table_name"]))
                if row["layer"] == "gold"
                else None
            )
        return {"run": self._run(), "tables": rows}

    def describe(self, table_ref: str) -> dict[str, Any]:
        layer, table_name = _parse_table_ref(table_ref)
        rows = self.engine.query(
            f"""
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = '{layer}' and table_name = '{table_name}'
order by ordinal_position
"""
        )
        if not rows:
            raise KeyError(f"Unknown catalog table: {table_ref}")
        return {"run": self._run(), "table": table_ref, "columns": rows}

    def query(self, sql: str, *, limit: int = 100) -> dict[str, Any]:
        selected_limit = bounded_query_limit(limit)
        statement = validate_catalog_sql(sql)
        rows = self.engine.query(with_scratch_limit(statement, selected_limit))
        return {
            "run": self._run(),
            "limit": selected_limit,
            "row_count": len(rows),
            "rows": rows,
        }

    def _register_silver(self) -> None:
        offer_refs = sorted(
            str(ref)
            for ref in dict(self.manifest.get("source_normalized_refs") or {}).values()
            if ref
        )
        state_refs = sorted(
            str(ref)
            for ref in dict(
                self.manifest.get("source_market_state_refs") or {}
            ).values()
            if ref
        )
        tables = {
            **{
                f"_silver_gpu_offers_{index}": ref
                for index, ref in enumerate(offer_refs)
            },
            **{
                f"_silver_compute_market_state_{index}": ref
                for index, ref in enumerate(state_refs)
            },
        }
        if not offer_refs:
            raise RuntimeError("Latest Gold manifest has no Silver offer references")
        self.engine.register_tables(tables)
        self.engine.create_schema("silver")
        self.engine.create_view(
            "silver",
            "gpu_offers",
            _union_all("_silver_gpu_offers", len(offer_refs)),
        )
        if state_refs:
            self.engine.create_view(
                "silver",
                "compute_market_state",
                _union_all("_silver_compute_market_state", len(state_refs)),
            )
        self.engine.deregister_tables(tables)

    def _register_gold(self) -> None:
        table_refs = {
            str(name): str(ref)
            for name, ref in dict(self.manifest.get("table_refs") or {}).items()
            if ref
        }
        if not table_refs:
            raise RuntimeError("Latest Gold manifest has no Gold table references")
        physical_tables = {
            f"_gold_{table_name}": ref for table_name, ref in table_refs.items()
        }
        self.engine.register_tables(physical_tables)
        self.engine.create_schema("gold")
        for table_name in sorted(table_refs):
            self.engine.create_view(
                "gold",
                table_name,
                f"select * from _gold_{table_name}",
            )
        self.engine.deregister_tables(physical_tables)

    def _run(self) -> dict[str, Any]:
        return {
            "run_id": self.manifest.get("run_id"),
            "observed_at": self.manifest.get("observed_at"),
            "provider_scope": self.manifest.get("provider_scope"),
        }


def _union_all(prefix: str, count: int) -> str:
    return " union all ".join(
        f"select * from {prefix}_{index}" for index in range(count)
    )


def _parse_table_ref(table_ref: str) -> tuple[str, str]:
    match = TABLE_REF_PATTERN.fullmatch(table_ref.strip())
    if not match:
        raise ValueError("Table must be named as silver.<table> or gold.<table>")
    return match.group(1), match.group(2)
