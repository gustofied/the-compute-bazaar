"""Public-safe benchmark series projections."""

from __future__ import annotations

from typing import Any


def public_benchmark_value(row: dict[str, Any]) -> dict[str, Any]:
    return _with_methodology(
        _select(
            row,
            "benchmark_value_id",
            "benchmark_symbol",
            "benchmark_family_id",
            "benchmark_label",
            "gpu_model_prefixes",
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
            "gold_run_id",
            "calculated_at",
        ),
        row,
    )


def public_benchmark_history_value(row: dict[str, Any]) -> dict[str, Any]:
    return _with_methodology(
        _select(
            row,
            "benchmark_symbol",
            "benchmark_family_id",
            "benchmark_label",
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
        ),
        row,
    )


def has_benchmark_value(row: dict[str, Any]) -> bool:
    value = row.get("benchmark_usd_gpu_hr")
    try:
        return value is not None and float(value) > 0
    except (TypeError, ValueError):
        return False


def public_benchmark_constituent(row: dict[str, Any]) -> dict[str, Any]:
    return _with_methodology(
        _select(
            row,
            "benchmark_value_id",
            "benchmark_symbol",
            "benchmark_family_id",
            "benchmark_label",
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
            "gold_run_id",
            "calculated_at",
        ),
        row,
    )


def _select(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: row.get(key) for key in keys}


def _with_methodology(
    projected: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    projected.pop("methodology_version", None)
    projected["methodology"] = source.get("methodology") or source.get(
        "methodology_version"
    )
    return projected
