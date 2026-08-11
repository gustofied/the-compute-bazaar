"""Assemble Silver inputs and retained market-state history for Gold builds."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .datafusion import DataFusionEngine
from .silver_contract import silver_market_state_select, silver_observation_select


GPU_PRICE_INDEX_HISTORY_FIELDS = (
    "benchmark_symbol",
    "benchmark_family_id",
    "benchmark_label",
    "methodology_version",
    "methodology_query_id",
    "benchmark_basis",
    "benchmark_usd_gpu_hr",
    "floor_usd_gpu_hr",
    "provider_floor_p25_usd_gpu_hr",
    "provider_floor_p75_usd_gpu_hr",
    "offer_count",
    "included_offer_count",
    "provider_count",
    "latest_observed_at",
    "calculated_at",
    "gold_run_id",
    "gold_observed_at",
    "gold_observed_date",
)


def silver_source_cte(table_names: list[str]) -> str:
    selects = [silver_observation_select(table_name) for table_name in table_names]
    return f"silver_offer_observations as ({' union all '.join(selects)})"


def source_catalog_values(provider_scope: list[str]) -> str:
    # Importing provider adapters is worker-only work; query clients should not
    # load every HTTP connector just to construct the logical lake catalog.
    from .provider_registry import source_catalog_rows

    rows = source_catalog_rows(provider_scope)
    return "values " + ", ".join(
        "("
        + ", ".join(
            _sql_literal(str(row[column]))
            for column in ("source_connector", "source_kind", "observation_kind")
        )
        + ")"
        for row in rows
    )


def silver_state_cte_fragment(table_names: list[str]) -> str:
    if not table_names:
        return ""
    selects = [silver_market_state_select(table_name) for table_name in table_names]
    return f",\nsilver_compute_market_state as ({' union all '.join(selects)})"


def silver_state_union_fragment(has_market_state: bool) -> str:
    if not has_market_state:
        return ""
    return """
union all
select
  observation_id,
  observed_at,
  resource_market,
  resource_type,
  provider,
  source_connector,
  source_role,
  measurement_kind,
  measurement_scope,
  unit,
  total_units,
  rented_units,
  available_units,
  pending_units,
  rented_share,
  available_share,
  stock_status,
  count_precision,
  numerator_definition,
  denominator_definition,
  aggregation_eligible,
  aggregation_exclusion_reason,
  source_url,
  raw_ref,
  methodology_version,
  notes,
  source_run_id,
  source_manifest_ref,
  source_normalized_ref,
  source_market_state_ref
from silver_compute_market_state
"""


def merge_compute_market_state_history(
    *,
    previous_ref: Any,
    current_rows: list[dict[str, Any]],
    methodology: str,
    retained_source_connectors: set[str],
) -> list[dict[str, Any]]:
    previous_rows: list[dict[str, Any]] = []
    if previous_ref:
        previous_rows = DataFusionEngine(
            {"fact_compute_market_state_history": str(previous_ref)}
        ).query("select * from fact_compute_market_state_history")
    merged: dict[str, dict[str, Any]] = {}
    for row in [*previous_rows, *current_rows]:
        row = dict(row)
        if str(row.get("source_connector") or "") not in retained_source_connectors:
            continue
        row["methodology_version"] = methodology
        row["observed_at"] = _timestamp(row.get("observed_at"))
        observation_id = str(row.get("observation_id") or "")
        if not observation_id:
            raise ValueError("Compute market-state history row has no observation_id")
        merged[observation_id] = row
    return sorted(
        merged.values(),
        key=lambda row: (
            str(row.get("gold_observed_at") or row.get("observed_at") or ""),
            str(row.get("measurement_kind") or ""),
            str(row.get("provider") or ""),
            str(row.get("resource_type") or ""),
            str(row.get("source_connector") or ""),
        ),
    )


def merge_gpu_price_index_history(
    *,
    previous_ref: Any,
    current_rows: list[dict[str, Any]],
    gold_run_id: str,
    gold_observed_at: str,
    gold_observed_date: str,
    methodology: str,
) -> list[dict[str, Any]]:
    previous_rows: list[dict[str, Any]] = []
    if previous_ref:
        previous_rows = DataFusionEngine(
            {"fact_gpu_price_index_history": str(previous_ref)}
        ).query("select * from fact_gpu_price_index_history")
    current_history = [
        gpu_price_index_history_row(
            row,
            gold_run_id=gold_run_id,
            gold_observed_at=gold_observed_at,
            gold_observed_date=gold_observed_date,
        )
        for row in current_rows
    ]
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*previous_rows, *current_history]:
        row = gpu_price_index_history_row(row)
        row["methodology_version"] = methodology
        row["latest_observed_at"] = _timestamp(row.get("latest_observed_at"))
        row["calculated_at"] = _timestamp(row.get("calculated_at"))
        row["gold_observed_at"] = _timestamp(row.get("gold_observed_at"))
        run_id = str(row.get("gold_run_id") or "")
        family = str(row.get("benchmark_family_id") or "")
        if not run_id or not family:
            raise ValueError("GPU Price Index history row has no run or family")
        merged[(run_id, family)] = row
    return sorted(
        merged.values(),
        key=lambda row: (
            str(row.get("gold_observed_at") or ""),
            str(row.get("benchmark_family_id") or ""),
        ),
    )


def gpu_price_index_history_row(
    row: dict[str, Any],
    *,
    gold_run_id: str | None = None,
    gold_observed_at: str | None = None,
    gold_observed_date: str | None = None,
) -> dict[str, Any]:
    """Project one index observation into the stable retained-history contract."""
    values = dict(row)
    if gold_run_id is not None:
        values["gold_run_id"] = gold_run_id
    if gold_observed_at is not None:
        values["gold_observed_at"] = gold_observed_at
    if gold_observed_date is not None:
        values["gold_observed_date"] = gold_observed_date
    return {field: values.get(field) for field in GPU_PRICE_INDEX_HISTORY_FIELDS}


def _timestamp(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
