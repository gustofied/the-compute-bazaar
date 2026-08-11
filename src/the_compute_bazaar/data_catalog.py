"""One DataFusion catalog for market data and Fleet operations."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .operations import OperationalLedger

from .prices.datafusion import DataFusionEngine
from .prices.gold_manifest import read_latest_gold_manifest
from .prices.query_catalog import (
    bounded_query_limit,
    validate_catalog_sql,
)
from .prices.silver_contract import (
    silver_contract,
    silver_market_state_select,
    silver_observation_select,
)


TABLE_REF_PATTERN = re.compile(r"^(silver|gold|fleet)\.([A-Za-z_][A-Za-z0-9_]*)$")


class ComputeBazaarCatalog:
    """Present the market lake and private operations as DataFusion tables."""

    def __init__(
        self,
        *,
        lake_root: str,
        manifest: dict[str, Any] | None = None,
        operations: OperationalLedger | None = None,
    ) -> None:
        self.manifest = manifest or read_latest_gold_manifest(lake_root.rstrip("/"))
        self.engine = DataFusionEngine()
        self.operations = operations
        self._scheduled_offer_sql = ""
        self._gold_tables: set[str] = set()
        self._register_silver()
        self._register_gold()
        if operations:
            self._register_operations()

    def tables(self) -> dict[str, Any]:
        rows = self.engine.query(
            """
select table_schema as layer, table_name, table_type
from information_schema.tables
where table_schema in ('silver', 'gold', 'fleet')
order by table_schema, table_name
"""
        )
        gold_counts = dict(self.manifest.get("row_counts") or {})
        for row in rows:
            layer = str(row["layer"])
            name = str(row["table_name"])
            row["row_count"] = gold_counts.get(name) if layer == "gold" else None
            if layer == "fleet" or (layer == "silver" and name == "current_offers"):
                row["row_count"] = self.engine.query(
                    f"select count(*) as n from {layer}.{name}"
                )[0]["n"]
        return {
            "run": self.run(),
            "tables": rows,
        }

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
        if layer == "silver":
            meanings = {
                column.name: column.meaning
                for column in silver_contract(table_name) or ()
            }
            for row in rows:
                row["meaning"] = meanings.get(str(row["column_name"]))
        return {"run": self.run(), "table": table_ref, "columns": rows}

    def query(self, sql: str, *, limit: int = 100) -> dict[str, Any]:
        table, selected_limit = self.query_arrow(sql, limit=limit)
        rows = table.to_pylist()
        return {
            "run": self.run(),
            "limit": selected_limit,
            "row_count": len(rows),
            "rows": rows,
        }

    def query_arrow(self, sql: str, *, limit: int = 100) -> tuple[Any, int]:
        """Run one bounded read-only statement and return an Arrow table."""
        selected_limit = bounded_query_limit(limit)
        statement = validate_catalog_sql(sql)
        table = self.engine.query_arrow(statement, limit=selected_limit)
        return table, selected_limit

    def run(self) -> dict[str, Any]:
        return {
            "run_id": self.manifest.get("run_id"),
            "observed_at": self.manifest.get("observed_at"),
            "provider_scope": self.manifest.get("provider_scope"),
        }

    def _register_silver(self) -> None:
        normalized_refs = dict(self.manifest.get("source_normalized_refs") or {})
        provider_scope = [
            str(provider) for provider in self.manifest.get("provider_scope") or []
        ]
        if not provider_scope:
            raise RuntimeError("Latest Gold manifest has no provider scope")
        missing = [
            provider for provider in provider_scope if not normalized_refs.get(provider)
        ]
        if missing:
            raise RuntimeError(
                "Latest Gold manifest has incomplete Silver references: "
                + ", ".join(missing)
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
                f"_silver_offer_observations_{index}": ref
                for index, ref in enumerate(
                    str(normalized_refs[provider]) for provider in provider_scope
                )
            },
            **{
                f"_silver_compute_market_state_{index}": ref
                for index, ref in enumerate(state_refs)
            },
        }
        self.engine.register_tables(tables)
        self.engine.create_schema("silver")
        self._scheduled_offer_sql = " union all ".join(
            silver_observation_select(f"_silver_offer_observations_{index}")
            for index in range(len(provider_scope))
        )
        if not self.operations:
            self.engine.create_view(
                "silver", "offer_observations", self._scheduled_offer_sql
            )
        if state_refs:
            self.engine.create_view(
                "silver",
                "compute_market_state",
                _union_all(
                    "_silver_compute_market_state",
                    len(state_refs),
                    select=silver_market_state_select,
                ),
            )

    def _register_gold(self) -> None:
        source_refs = dict(self.manifest.get("table_refs") or {})
        missing = [str(name) for name, ref in source_refs.items() if not ref]
        if missing:
            raise RuntimeError(
                "Latest Gold manifest has empty table references: "
                + ", ".join(sorted(missing))
            )
        table_refs = {str(name): str(ref) for name, ref in source_refs.items()}
        if not table_refs:
            raise RuntimeError("Latest Gold manifest has no Gold table references")
        self.engine.register_tables(
            {f"_gold_{table_name}": ref for table_name, ref in table_refs.items()}
        )
        self.engine.create_schema("gold")
        for table_name in sorted(table_refs):
            self.engine.create_view(
                "gold",
                table_name,
                f"select * from _gold_{table_name}",
            )
        self._gold_tables = set(table_refs)

    def _register_operations(self) -> None:
        assert self.operations is not None
        tables = self.operations.arrow_tables()
        for name, table in tables.items():
            self.engine.register_arrow_table(f"_local_{name}", table)

        self.engine.create_view(
            "silver",
            "offer_observations",
            f"{self._scheduled_offer_sql} union all select * from _local_offer_observations",
        )
        self.engine.create_view("silver", "current_offers", _current_offers_sql())
        self.engine.create_schema("fleet")
        for name in ("machines", "allocations", "observations"):
            self.engine.create_view(
                "fleet",
                name,
                f"select * from _local_fleet_{name}",
            )

        if (
            "fact_gpu_price_index_history" in self._gold_tables
            and "fact_market_to_fleet" not in self._gold_tables
        ):
            self.engine.create_view(
                "gold",
                "fact_market_to_fleet",
                _market_to_fleet_sql(),
            )


def _union_all(
    prefix: str,
    count: int,
    *,
    select: Callable[[str], str] | None = None,
) -> str:
    select_table = select or (lambda table_name: f"select * from {table_name}")
    return " union all ".join(
        select_table(f"{prefix}_{index}") for index in range(count)
    )


def _parse_table_ref(table_ref: str) -> tuple[str, str]:
    match = TABLE_REF_PATTERN.fullmatch(table_ref.strip())
    if not match:
        raise ValueError("Table must be named as silver.*, gold.*, or fleet.*")
    return match.group(1), match.group(2)


def _current_offers_sql() -> str:
    return """
select *
from silver.offer_observations
where observation_purpose in ('interactive', 'preflight')
  and selection_fingerprint is not null
  and observed_at >= current_timestamp() - interval '15 minutes'
qualify row_number() over (
  partition by selection_fingerprint
  order by observed_at desc, observation_id desc
) = 1
"""


def _market_to_fleet_sql() -> str:
    return """
with benchmark_at_launch as (
  select
    allocation.*,
    offer.observation_purpose as selected_observation_purpose,
    offer.observation_resolution as selected_observation_resolution,
    offer.selection_resolution as selected_selection_resolution,
    offer.selection_fingerprint,
    offer.source_connector,
    offer.source_offer_id,
    offer.raw_hash as selected_raw_hash,
    benchmark.benchmark_usd_gpu_hr,
    benchmark.gold_observed_at as benchmark_observed_at,
    row_number() over (
      partition by allocation.host_id
      order by benchmark.gold_observed_at desc
    ) as benchmark_rank
  from fleet.allocations allocation
  join silver.offer_observations offer
    on offer.observation_id = allocation.offer_observation_id
  left join gold.fact_gpu_price_index_history benchmark
    on benchmark.benchmark_family_id = allocation.gpu_family
    and benchmark.gold_observed_at <= allocation.launched_at
),
observation_summary as (
  select
    host_id,
    min(case when readiness = 'ready' then observed_at else null end)
      as first_ready_at,
    max(observed_at) as latest_observed_at,
    count(*) as observation_count
  from fleet.observations
  group by host_id
),
latest_observation as (
  select host_id, readiness, gpu_utilization_pct, gpu_temperature_c
  from (
    select
      *,
      row_number() over (
        partition by host_id order by observed_at desc
      ) as observation_rank
    from fleet.observations
  )
  where observation_rank = 1
)
select
  allocation.host_id,
  allocation.provider,
  allocation.provider_resource_id,
  allocation.offer_observation_id,
  allocation.offer_batch_id,
  allocation.offer_id,
  allocation.plan_id,
  allocation.name,
  allocation.state,
  allocation.gpu_family,
  allocation.gpu_model,
  allocation.gpu_count,
  allocation.cloud_type,
  allocation.location,
  allocation.selected_observation_purpose,
  allocation.selected_observation_resolution,
  allocation.selected_selection_resolution,
  allocation.selection_fingerprint,
  allocation.source_connector,
  allocation.source_offer_id,
  allocation.selected_raw_hash,
  allocation.selected_price_usd_gpu_hr,
  allocation.selected_price_usd_instance_hr,
  allocation.benchmark_usd_gpu_hr,
  case
    when allocation.benchmark_usd_gpu_hr > 0 then
      100 * (
        allocation.selected_price_usd_gpu_hr
        / allocation.benchmark_usd_gpu_hr - 1
      )
    else null
  end as selected_vs_benchmark_pct,
  allocation.offer_observed_at,
  allocation.benchmark_observed_at,
  allocation.launched_at,
  allocation.terminate_at,
  allocation.terminated_at,
  allocation.expected_max_cost_usd,
  allocation.ssh_ready,
  summary.first_ready_at,
  summary.latest_observed_at,
  summary.observation_count,
  latest.readiness as latest_readiness,
  latest.gpu_utilization_pct as latest_gpu_utilization_pct,
  latest.gpu_temperature_c as latest_gpu_temperature_c
from benchmark_at_launch allocation
left join observation_summary summary using (host_id)
left join latest_observation latest using (host_id)
where allocation.benchmark_rank = 1
"""
