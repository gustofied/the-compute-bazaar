"""Assemble Silver inputs and retained market-state history for Gold builds."""

from __future__ import annotations

from typing import Any

from .datafusion import query_parquet
from .provider_registry import source_catalog_rows


def silver_source_cte(table_names: list[str]) -> str:
    columns = """
      provider,
      source_offer_id,
      observed_at,
      gpu_raw_name,
      gpu_model,
      coalesce(source_connector, provider) as source_connector,
      gpu_count,
      available_gpu_count,
      vram_gb,
      price_usd_hr,
      currency,
      country,
      region,
      is_spot,
      is_secure,
      availability_status,
      gpu_socket,
      stock_status,
      price_is_variable,
      minimum_executable_price_usd_hr,
      required_resource_price_usd_hr,
      price_basis,
      raw_ref
    """
    selects = [f"select {columns} from {table_name}" for table_name in table_names]
    return f"silver_gpu_offers as ({' union all '.join(selects)})"


def source_catalog_values(provider_scope: list[str]) -> str:
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
    selects = [f"select * from {table_name}" for table_name in table_names]
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
) -> list[dict[str, Any]]:
    previous_rows: list[dict[str, Any]] = []
    if previous_ref:
        previous_rows = query_parquet(
            parquet_uri=str(previous_ref),
            table_name="fact_compute_market_state_history",
            sql="select * from fact_compute_market_state_history",
        )
    merged: dict[str, dict[str, Any]] = {}
    for row in [*previous_rows, *current_rows]:
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


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
