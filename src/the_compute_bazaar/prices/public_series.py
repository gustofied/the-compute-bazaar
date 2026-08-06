"""Public-safe benchmark and market-state series projections."""

from __future__ import annotations

from typing import Any

from .gold_manifest import is_canonical_market_run_id
from .gold_models import BENCHMARK_METHODOLOGY_VERSION
from .storage import read_json


PUBLIC_MARKET_STATE_HISTORY_RESOURCES = {
    "ALL_GPU",
    "ALL_CPU",
    "ALL_MEMORY",
    "ALL_STORAGE",
    "ALL_EPHEMERAL_STORAGE",
    "ALL_PERSISTENT_STORAGE",
}


def public_benchmark_value(row: dict[str, Any]) -> dict[str, Any]:
    return _select(
        row,
        "benchmark_value_id",
        "benchmark_symbol",
        "benchmark_family_id",
        "benchmark_label",
        "gpu_model_prefixes",
        "methodology_version",
        "methodology_query_id",
        "benchmark_basis",
        "benchmark_usd_gpu_hr",
        "observed_average_usd_gpu_hr",
        "provider_floor_median_usd_gpu_hr",
        "provider_floor_mean_usd_gpu_hr",
        "provider_floor_p25_usd_gpu_hr",
        "provider_floor_p75_usd_gpu_hr",
        "floor_usd_gpu_hr",
        "median_usd_gpu_hr",
        "simple_mean_usd_gpu_hr",
        "trimmed_mean_usd_gpu_hr",
        "p25_usd_gpu_hr",
        "p75_usd_gpu_hr",
        "cheapest_offer_usd_instance_hr",
        "offer_count",
        "included_offer_count",
        "provider_count",
        "gpu_model_count",
        "country_count",
        "secure_offer_count",
        "spot_offer_count",
        "latest_observed_at",
        "status",
        "source_run_id",
        "calculated_at",
    )


def public_benchmark_history_value(row: dict[str, Any]) -> dict[str, Any]:
    return _select(
        row,
        "benchmark_symbol",
        "benchmark_family_id",
        "benchmark_label",
        "methodology_version",
        "benchmark_basis",
        "benchmark_usd_gpu_hr",
        "provider_floor_p25_usd_gpu_hr",
        "provider_floor_p75_usd_gpu_hr",
        "included_offer_count",
        "provider_count",
        "latest_observed_at",
        "calculated_at",
        "gold_run_id",
        "gold_observed_at",
        "gold_observed_date",
    )


def has_benchmark_value(row: dict[str, Any]) -> bool:
    value = row.get("benchmark_usd_gpu_hr")
    try:
        return value is not None and float(value) > 0
    except (TypeError, ValueError):
        return False


def merge_benchmark_history(
    existing_rows: Any,
    current_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    candidates = [
        row
        for row in (existing_rows if isinstance(existing_rows, list) else [])
        if isinstance(row, dict)
    ]
    candidates.extend(current_rows)
    for row in candidates:
        if row.get("methodology_version") != BENCHMARK_METHODOLOGY_VERSION:
            continue
        if not has_benchmark_value(row):
            continue
        run_id = str(row.get("gold_run_id") or "")
        if run_id and not is_canonical_market_run_id(run_id):
            continue
        observed_at = str(row.get("gold_observed_at") or "")
        family = str(row.get("benchmark_family_id") or "")
        if observed_at and family:
            merged[(run_id or observed_at, family)] = row
    return sorted(
        merged.values(),
        key=lambda row: (
            str(row.get("gold_observed_at") or ""),
            str(row.get("benchmark_family_id") or ""),
        ),
    )


def read_benchmark_history(ref: str) -> list[dict[str, Any]]:
    payload = _read_optional_json(ref)
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def public_market_state_row(row: dict[str, Any]) -> dict[str, Any]:
    return _select(
        row,
        "observation_id",
        "observed_at",
        "resource_market",
        "resource_type",
        "provider",
        "source_connector",
        "source_role",
        "measurement_kind",
        "measurement_scope",
        "unit",
        "total_units",
        "rented_units",
        "available_units",
        "pending_units",
        "rented_share",
        "available_share",
        "stock_status",
        "count_precision",
        "numerator_definition",
        "denominator_definition",
        "aggregation_eligible",
        "aggregation_exclusion_reason",
        "source_url",
        "methodology_version",
        "notes",
        "calculated_at",
        "gold_run_id",
        "gold_observed_at",
        "gold_observed_date",
    )


def merge_market_state_history(
    existing_rows: Any,
    current_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    candidates = [
        row
        for row in (existing_rows if isinstance(existing_rows, list) else [])
        if isinstance(row, dict)
        and row.get("measurement_kind") == "rental_occupancy"
        and row.get("resource_type") in PUBLIC_MARKET_STATE_HISTORY_RESOURCES
        and row.get("aggregation_eligible") is not False
    ]
    candidates.extend(current_rows)
    for row in candidates:
        observation_id = str(row.get("observation_id") or "")
        observed_at = str(row.get("gold_observed_at") or row.get("observed_at") or "")
        run_id = str(row.get("gold_run_id") or "")
        if observation_id and observed_at:
            merged[(run_id or observed_at, observation_id)] = row
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


def read_market_state_history(ref: str) -> list[dict[str, Any]]:
    payload = _read_optional_json(ref)
    rows = payload.get("history_rows", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def public_benchmark_constituent(row: dict[str, Any]) -> dict[str, Any]:
    return _select(
        row,
        "benchmark_value_id",
        "benchmark_symbol",
        "benchmark_family_id",
        "benchmark_label",
        "methodology_version",
        "methodology_query_id",
        "listing_id",
        "provider",
        "source_connector",
        "source_offer_id",
        "gpu_model",
        "gpu_raw_name",
        "gpu_count",
        "available_gpu_count_lower_bound",
        "vram_gb",
        "price_usd_gpu_hr",
        "price_usd_instance_hr",
        "country",
        "region",
        "is_spot",
        "is_secure",
        "source_availability_status",
        "included",
        "inclusion_reason",
        "exclusion_reason",
        "constituent_rank",
        "provider_rank",
        "is_floor_constituent",
        "observed_at",
        "has_raw_evidence",
        "source_run_id",
        "calculated_at",
    )


def _select(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: row.get(key) for key in keys}


def _read_optional_json(ref: str) -> Any:
    try:
        return read_json(ref)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        error = getattr(exc, "response", {}).get("Error", {})
        if str(error.get("Code") or "") in {"404", "NoSuchKey", "NotFound"}:
            return {}
        raise
