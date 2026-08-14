"""DataFusion catalog for market data and Fleet operations."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
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
        self._operation_table_names: set[str] = set()
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
        table, selected_limit, truncated = self.query_arrow(sql, limit=limit)
        rows = table.to_pylist()
        return {
            "run": self.run(),
            "limit": selected_limit,
            "row_count": len(rows),
            "truncated": truncated,
            "rows": rows,
        }

    def query_arrow(self, sql: str, *, limit: int = 100) -> tuple[Any, int, bool]:
        """Run one bounded read-only statement and return an Arrow table."""
        selected_limit = bounded_query_limit(limit)
        statement = validate_catalog_sql(sql)
        table = self.engine.query_arrow(statement, limit=selected_limit + 1)
        truncated = table.num_rows > selected_limit
        if truncated:
            table = table.slice(0, selected_limit)
        return table, selected_limit, truncated

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
            silver_observation_select(
                f"_silver_offer_observations_{index}",
                available_columns=set(
                    self.engine.table_columns(f"_silver_offer_observations_{index}")
                ),
            )
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
        table_refs = {str(name): ref for name, ref in source_refs.items()}
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
            local_name = f"_local_{name}"
            self.engine.register_arrow_table(local_name, table)
            self._operation_table_names.add(local_name)

        self.engine.create_view(
            "silver",
            "offer_observations",
            f"{self._scheduled_offer_sql} union all select * from _local_offer_observations",
        )
        self.engine.create_view("silver", "current_offers", _current_offers_sql())
        self.engine.create_view(
            "silver",
            "provider_read_batches",
            "select * from _local_provider_read_batches",
        )
        self.engine.create_schema("fleet")
        views = {
            "nodes": "fleet_nodes",
            "allocations": "allocations",
            "telemetry": "fleet_telemetry",
            "capacity_verifications": "capacity_verifications",
            "provisioning_requests": "provisioning_requests",
            "provisioning_attempts": "provisioning_attempts",
            "workloads": "workload_runs",
        }
        for view, source in views.items():
            self.engine.create_view("fleet", view, f"select * from _local_{source}")

        if (
            "fact_gpu_price_index_history" in self._gold_tables
            and "fact_market_to_fleet" not in self._gold_tables
        ):
            self.engine.create_view(
                "gold",
                "fact_market_to_fleet",
                _market_to_fleet_sql(),
            )

    def refresh_operations(self) -> None:
        """Replace mutable operational tables without rebuilding the lake catalog."""
        if not self.operations:
            return
        if (
            "fact_gpu_price_index_history" in self._gold_tables
            and "fact_market_to_fleet" not in self._gold_tables
        ):
            self.engine.drop_view("gold", "fact_market_to_fleet")
        for view in (
            "nodes",
            "allocations",
            "telemetry",
            "capacity_verifications",
            "provisioning_requests",
            "provisioning_attempts",
            "workloads",
        ):
            self.engine.drop_view("fleet", view)
        for view in ("current_offers", "provider_read_batches", "offer_observations"):
            self.engine.drop_view("silver", view)
        self.engine.deregister_tables(self._operation_table_names)
        self._operation_table_names.clear()
        self._register_operations()


def open_catalog(*, lake_root: str, operations: OperationalLedger | None = None) -> Any:
    from .market.catalog import market_manifest_ref

    if "://" not in lake_root and Path(market_manifest_ref(lake_root)).is_file():
        from .market.catalog import MarketCatalog

        return MarketCatalog.from_lake(lake_root)
    manifest = read_latest_gold_manifest(lake_root.rstrip("/"))
    return ComputeBazaarCatalog(
        lake_root=lake_root,
        manifest=manifest,
        operations=operations,
    )


def read_catalog_manifest(lake_root: str) -> dict[str, Any]:
    from .market.catalog import market_manifest_ref, read_market_manifest

    if "://" not in lake_root and Path(market_manifest_ref(lake_root)).is_file():
        return read_market_manifest(lake_root)
    return read_latest_gold_manifest(lake_root.rstrip("/"))


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
    request.plan_id,
    request.preflight_batch_id,
    request.market_product_key,
    request.gpu_model,
    request.gpu_count,
    allocation.price_usd_gpu_hr as selected_price_usd_gpu_hr,
    allocation.price_usd_instance_hr as selected_price_usd_instance_hr,
    request.expected_max_cost_usd,
    preflight.observation_purpose as selected_observation_purpose,
    preflight.observation_resolution as selected_observation_resolution,
    preflight.selection_resolution as selected_selection_resolution,
    preflight.selection_fingerprint,
    preflight.raw_hash as selected_raw_hash,
    preflight.observed_at as offer_observed_at,
    candidate.price_usd_gpu_hr as candidate_price_usd_gpu_hr,
    node.host_id,
    node.name,
    node.state as node_state,
    node.ssh_ready,
    benchmark.benchmark_usd_gpu_hr,
    benchmark.gold_observed_at as benchmark_observed_at,
    row_number() over (
      partition by allocation.allocation_id, node.host_id
      order by benchmark.gold_observed_at desc
    ) as benchmark_rank
  from fleet.allocations allocation
  join fleet.provisioning_requests request using (request_id)
  left join silver.offer_observations preflight
    on preflight.observation_id = allocation.preflight_observation_id
  left join silver.offer_observations candidate
    on candidate.observation_id = allocation.candidate_observation_id
  left join fleet.nodes node using (allocation_id)
  left join gold.fact_gpu_price_index_history benchmark
    on benchmark.benchmark_family_id = split_part(request.gpu_model, '_', 1)
    and benchmark.gold_observed_at <= allocation.created_at
),
verification_summary as (
  select
    host_id,
    min(case when readiness = 'ready' then observed_at else null end)
      as first_ready_at,
    max(observed_at) as latest_observed_at,
    count(*) as verification_count
  from fleet.capacity_verifications
  group by host_id
),
latest_verification as (
  select host_id, readiness
  from (
    select
      *,
      row_number() over (
        partition by host_id order by observed_at desc
      ) as verification_rank
    from fleet.capacity_verifications
  )
  where verification_rank = 1
),
latest_telemetry as (
  select host_id, observed_at, gpu_utilization_pct, gpu_temperature_c
  from (
    select
      *,
      row_number() over (
        partition by host_id order by observed_at desc
      ) as telemetry_rank
    from fleet.telemetry
  )
  where telemetry_rank = 1
)
select
  allocation.allocation_id,
  allocation.host_id,
  allocation.request_id,
  allocation.successful_attempt_id,
  allocation.source,
  allocation.intermediary,
  allocation.operator,
  allocation.offer_id,
  allocation.source_resource_id,
  allocation.plan_id,
  allocation.candidate_observation_id,
  allocation.preflight_observation_id,
  allocation.preflight_batch_id,
  allocation.market_product_key,
  allocation.name,
  allocation.state as allocation_state,
  allocation.node_state,
  allocation.gpu_model,
  allocation.gpu_count,
  allocation.selected_observation_purpose,
  allocation.selected_observation_resolution,
  allocation.selected_selection_resolution,
  allocation.selection_fingerprint,
  allocation.selected_raw_hash,
  allocation.candidate_price_usd_gpu_hr,
  allocation.selected_price_usd_gpu_hr,
  allocation.selected_price_usd_instance_hr,
  case
    when allocation.candidate_price_usd_gpu_hr > 0 then
      100 * (
        allocation.selected_price_usd_gpu_hr
        / allocation.candidate_price_usd_gpu_hr - 1
      )
    else null
  end as preflight_price_change_pct,
  allocation.price_usd_gpu_hr,
  allocation.price_usd_instance_hr,
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
  allocation.created_at as allocated_at,
  allocation.terminate_at,
  allocation.terminated_at,
  allocation.expected_max_cost_usd,
  allocation.ssh_ready,
  summary.first_ready_at,
  summary.latest_observed_at,
  summary.verification_count,
  verified.readiness as latest_readiness,
  telemetry.observed_at as latest_telemetry_at,
  telemetry.gpu_utilization_pct as latest_gpu_utilization_pct,
  telemetry.gpu_temperature_c as latest_gpu_temperature_c
from benchmark_at_launch allocation
left join verification_summary summary
  on summary.host_id = allocation.host_id
left join latest_verification verified
  on verified.host_id = allocation.host_id
left join latest_telemetry telemetry
  on telemetry.host_id = allocation.host_id
where allocation.benchmark_rank = 1
"""
