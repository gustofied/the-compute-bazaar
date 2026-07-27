"""Compact, versioned publication views derived from public Gold products."""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from typing import Any


CARD_SCHEMA_VERSION = "compute_bazaar_card_v1"
GPU_FAMILIES = ("H100", "H200", "B200", "B300")


def gpu_benchmark_view(
    *,
    manifest: Mapping[str, Any],
    family_id: str,
    current: Mapping[str, Any] | None,
    history: list[Mapping[str, Any]],
    constituents: list[Mapping[str, Any]],
    methodology_version: str,
) -> dict[str, Any]:
    family = family_id.upper()
    family_history = [
        _benchmark_series_row(row)
        for row in history
        if str(row.get("benchmark_family_id") or "").upper() == family
    ]
    family_history.sort(key=lambda row: str(row.get("observed_at") or ""))
    latest = dict(current or {})
    included = [
        row
        for row in constituents
        if str(row.get("benchmark_family_id") or "").upper() == family
        and row.get("included") is True
    ]
    providers = sorted(
        {
            str(row.get("provider"))
            for row in included
            if str(row.get("provider") or "").strip()
        }
    )
    observed_at = (
        latest.get("calculated_at")
        or latest.get("latest_observed_at")
        or manifest.get("observed_at")
    )
    value = _number(latest.get("benchmark_usd_gpu_hr"))
    status = "live" if value is not None else "unavailable"
    return _card(
        card_type="gpu_benchmark",
        card_id=f"gpu-benchmark:{family.lower()}",
        as_of=observed_at,
        status=status,
        unit="USD per GPU-hour",
        methodology={
            "id": methodology_version,
            "basis": latest.get("benchmark_basis"),
            "query_id": latest.get("methodology_query_id"),
        },
        headline={
            "label": f"{family} observed benchmark",
            "value": value,
            "lower": _number(latest.get("provider_floor_p25_usd_gpu_hr")),
            "upper": _number(latest.get("provider_floor_p75_usd_gpu_hr")),
        },
        series=family_history,
        band={
            "kind": "provider_floor_interquartile_range",
            "lower_field": "lower",
            "upper_field": "upper",
        },
        coverage={
            "provider_count": int(latest.get("provider_count") or 0),
            "offer_count": int(latest.get("included_offer_count") or 0),
            "observation_count": len(family_history),
            "providers": providers,
        },
        sources=[
            {
                "label": provider,
                "role": "included provider floor",
            }
            for provider in providers
        ],
        drilldown_ref="benchmark-constituents.json",
        data={
            "family_id": family,
            "current": latest or None,
        },
        observation_window=_observation_window(family_history),
    )


def prime_frontier_view(
    *,
    manifest: Mapping[str, Any],
    product: Mapping[str, Any],
    methodology_version: str,
    source: Mapping[str, Any],
    measurement_notes: list[str],
    execution_data: Mapping[str, Any],
) -> dict[str, Any]:
    family = str(product.get("family_id") or "").upper()
    current = product.get("current")
    current_row = current if isinstance(current, Mapping) else {}
    history = [
        _prime_series_row(row)
        for row in product.get("history", [])
        if isinstance(row, Mapping)
    ]
    history.sort(key=lambda row: str(row.get("observed_at") or ""))
    value = _number(current_row.get("reference_usd_gpu_hr"))
    source_rows = [
        dict(row)
        for row in product.get("sources", [])
        if isinstance(row, Mapping)
    ]
    return _card(
        card_type="prime_frontier_offer_market",
        card_id=f"prime-frontier:{family.lower()}",
        as_of=(
            current_row.get("gold_observed_at")
            or current_row.get("latest_source_observed_at")
            or manifest.get("observed_at")
        ),
        status="live" if value is not None else "unavailable",
        unit="USD per GPU-hour",
        methodology={
            "id": methodology_version,
            "scope": current_row.get("reference_scope"),
            "notes": list(measurement_notes),
            "execution_data": dict(execution_data),
        },
        headline={
            "label": f"Prime {family} offer reference",
            "value": value,
            "market_benchmark": _number(
                current_row.get("market_benchmark_usd_gpu_hr")
            ),
            "best": _number(current_row.get("best_usd_gpu_hr")),
        },
        series=history,
        band={
            "kind": "upstream_provider_floor_interquartile_range",
            "lower_field": "lower",
            "upper_field": "upper",
        },
        coverage={
            "upstream_provider_count": int(current_row.get("provider_count") or 0),
            "configuration_count": int(
                current_row.get("configuration_count") or 0
            ),
            "observation_count": len(history),
        },
        sources=[dict(source), *source_rows],
        drilldown_ref="prime-frontier-offer-market.json",
        data={
            **{
                key: value
                for key, value in dict(product).items()
                if key != "history"
            },
        },
        observation_window=_observation_window(history),
    )


def market_state_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    current_rows = [
        dict(row)
        for row in payload.get("current_rows", [])
        if isinstance(row, Mapping)
    ]
    history_rows = [
        dict(row)
        for row in payload.get("history_rows", [])
        if isinstance(row, Mapping)
    ]
    timestamps = [
        {
            "observed_at": row.get("observed_at")
            or row.get("gold_observed_at")
            or row.get("calculated_at")
        }
        for row in [*current_rows, *history_rows]
    ]
    source_map: dict[str, dict[str, Any]] = {}
    for row in current_rows:
        url = str(row.get("source_url") or "")
        provider = str(row.get("provider") or row.get("source_connector") or "")
        key = url or provider
        if key:
            source_map[key] = {
                "label": provider or url,
                "url": url or None,
                "role": row.get("measurement_kind"),
            }
    return _card(
        card_type="compute_market_state",
        card_id="capacity:market-state",
        as_of=(payload.get("manifest") or {}).get("observed_at"),
        status="live" if current_rows else "unavailable",
        unit="source-defined capacity units",
        methodology={
            "id": payload.get("methodology_version"),
            "measurement_kinds": payload.get("measurement_kinds"),
        },
        headline={
            "label": "Observed market capacity state",
            "value": len(current_rows),
            "value_label": "current measurements",
        },
        series=history_rows,
        band=None,
        coverage={
            "current_measurement_count": len(current_rows),
            "history_observation_count": len(history_rows),
            "providers": sorted(
                {
                    str(row.get("provider"))
                    for row in current_rows
                    if str(row.get("provider") or "").strip()
                }
            ),
        },
        sources=list(source_map.values()),
        drilldown_ref="market-state.json",
        data={
            "measurement_kinds": payload.get("measurement_kinds"),
            "current_rows": current_rows,
            "vm_and_sandbox": payload.get("vm_and_sandbox"),
        },
        observation_window=_observation_window(timestamps),
    )


def sandbox_rate_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") or {}
    hourly = payload.get("hourly_price") or {}
    vm_capacity = payload.get("vm_capacity") or {}
    combined = payload.get("combined") or {}
    utilization = payload.get("utilization") or {}
    rate_series = list(hourly.get("fixed_cohort_rate") or [])
    latest = rate_series[-1] if rate_series else {}
    vm_series = list(vm_capacity.get("observed_market_rate") or [])
    timestamps = [
        {"observed_at": row.get("observed_at") or row.get("observed_date")}
        for row in [*rate_series, *vm_series]
        if isinstance(row, Mapping)
    ]
    return _card(
        card_type="compute_rate_market",
        card_id="sandbox:rates",
        as_of=manifest.get("built_at"),
        status="live" if hourly.get("current_cross_section") else "unavailable",
        unit="USD per hour",
        methodology={
            "sandbox_rate": hourly.get("methodology_version"),
            "vm_rate": vm_capacity.get("methodology_version"),
        },
        headline={
            "label": "Public compute rates",
            "sandbox_median": _number(latest.get("median_usd_per_hour")),
            "vm_median": _number(
                (vm_series[-1] if vm_series else {}).get("median_usd_per_hour")
            ),
        },
        series={
            "sandbox": rate_series,
            "vm": vm_series,
            "combined": list(combined.get("rows") or []),
        },
        band={
            "kind": "cross_section_interquartile_range",
            "lower_field": "p25_usd_per_hour",
            "upper_field": "p75_usd_per_hour",
        },
        coverage={
            "sandbox_service_count": len(hourly.get("current_cross_section") or []),
            "vm_provider_count": len(vm_capacity.get("current_cross_section") or []),
        },
        sources=list(payload.get("sources") or []),
        drilldown_ref="sandbox-cost.json",
        data={
            "manifest": dict(manifest),
            "hourly_price": _without(
                hourly,
                "fixed_cohort_rate",
                "fixed_membership_average",
            ),
            "vm_capacity": _without(
                vm_capacity,
                "observed_market_rate",
                "fixed_cohort_rate",
            ),
            "combined": _without(combined, "rows"),
            "utilization": dict(utilization),
        },
        observation_window=_observation_window(timestamps),
    )


def sandbox_workload_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") or {}
    workload = payload.get("workload") or {}
    summaries = list(workload.get("service_summary") or [])
    costs = [
        _number(row.get("median_estimated_cost_usd"))
        for row in summaries
        if isinstance(row, Mapping)
    ]
    costs = [value for value in costs if value is not None]
    latest_run = workload.get("latest_run") or {}
    run_history = list(workload.get("run_history") or [])
    timestamps = [
        {"observed_at": row.get("observed_at") or row.get("observed_date")}
        for row in run_history
        if isinstance(row, Mapping)
    ]
    return _card(
        card_type="sandbox_workload",
        card_id="sandbox:workload",
        as_of=latest_run.get("generated_at") or manifest.get("built_at"),
        status="live" if summaries else "unavailable",
        unit="USD estimated processor-and-memory cost",
        methodology={
            "cost_basis": workload.get("cost_basis"),
            "runtime_definition": workload.get("runtime_definition"),
            "claim_scope": workload.get("claim_scope"),
        },
        headline={
            "label": "Same measured software job",
            "median_service_cost": (
                statistics.median(costs) if costs else None
            ),
            "service_count": len(summaries),
        },
        series=run_history,
        band={
            "kind": "observed_job_distribution",
            "lower_field": "p25",
            "upper_field": "p75",
        },
        coverage={
            "source_batch_count": int(workload.get("source_batch_count") or 0),
            "calendar_day_count": int(workload.get("calendar_day_count") or 0),
            "service_count": len(summaries),
            "latest_replicate_count": int(
                workload.get("latest_replicate_count") or 0
            ),
        },
        sources=list(payload.get("sources") or []),
        drilldown_ref="sandbox-cost.json",
        data={
            "manifest": dict(manifest),
            "workload": _without(workload, "run_history"),
        },
        observation_window=_observation_window(timestamps),
    )


def market_overview_view(
    *,
    manifest: Mapping[str, Any],
    benchmark_cards: list[Mapping[str, Any]],
    sandbox_rates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    benchmarks = []
    for card in benchmark_cards:
        headline = card.get("headline") or {}
        data = card.get("data") or {}
        benchmarks.append(
            {
                "family_id": data.get("family_id"),
                "value": headline.get("value"),
                "lower": headline.get("lower"),
                "upper": headline.get("upper"),
                "provider_count": (card.get("coverage") or {}).get(
                    "provider_count"
                ),
                "offer_count": (card.get("coverage") or {}).get("offer_count"),
                "status": card.get("status"),
                "ref": f"gpu-benchmark/{str(data.get('family_id') or '').lower()}.json",
            }
        )
    sandbox_headline = (
        dict(sandbox_rates.get("headline") or {}) if sandbox_rates else None
    )
    public_run = {
        key: manifest.get(key)
        for key in [
            "manifest_version",
            "market_run_id",
            "run_id",
            "status",
            "data_quality_status",
            "observed_at",
            "observed_date",
            "providers",
            "successful_providers",
            "failed_providers",
            "gold_run_id",
            "dashboard_export_id",
            "row_counts",
        ]
        if manifest.get(key) is not None
    }
    return _card(
        card_type="market_overview",
        card_id="market:overview",
        as_of=manifest.get("observed_at"),
        status=str(manifest.get("status") or "unknown"),
        unit="mixed; declared per observation",
        methodology={
            "note": "Overview only; each linked card owns its unit and methodology."
        },
        headline={
            "label": "Compute Bazaar market observation",
            "market_run_id": manifest.get("market_run_id")
            or manifest.get("run_id"),
        },
        series=[],
        band=None,
        coverage={
            "successful_providers": len(manifest.get("successful_providers") or []),
            "failed_providers": len(manifest.get("failed_providers") or []),
            "benchmark_family_count": len(
                [row for row in benchmarks if row.get("value") is not None]
            ),
        },
        sources=[],
        drilldown_ref="market-run.json",
        data={
            "market_run": public_run,
            "benchmarks": benchmarks,
            "sandbox_rates": sandbox_headline,
        },
        observation_window={
            "started_at": manifest.get("observed_at"),
            "ended_at": manifest.get("observed_at"),
        },
    )


def _card(
    *,
    card_type: str,
    card_id: str,
    as_of: Any,
    status: str,
    unit: str,
    methodology: Any,
    headline: Any,
    series: Any,
    band: Any,
    coverage: Any,
    sources: Any,
    drilldown_ref: str,
    data: Any,
    observation_window: Any,
) -> dict[str, Any]:
    return {
        "schema_version": CARD_SCHEMA_VERSION,
        "card_type": card_type,
        "card_id": card_id,
        "as_of": as_of,
        "observation_window": observation_window,
        "status": status,
        "unit": unit,
        "methodology": methodology,
        "headline": headline,
        "series": series,
        "band": band,
        "coverage": coverage,
        "sources": sources,
        "drilldown_ref": drilldown_ref,
        "data": data,
    }


def _benchmark_series_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "observed_at": row.get("gold_observed_at")
        or row.get("calculated_at")
        or row.get("latest_observed_at"),
        "value": _number(row.get("benchmark_usd_gpu_hr")),
        "lower": _number(row.get("provider_floor_p25_usd_gpu_hr")),
        "upper": _number(row.get("provider_floor_p75_usd_gpu_hr")),
        "provider_count": int(row.get("provider_count") or 0),
        "offer_count": int(row.get("included_offer_count") or 0),
        "run_id": row.get("gold_run_id"),
    }


def _prime_series_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(row),
        "observed_at": row.get("gold_observed_at")
        or row.get("latest_source_observed_at"),
        "value": _number(row.get("reference_usd_gpu_hr")),
        "lower": _number(row.get("provider_floor_p25_usd_gpu_hr")),
        "upper": _number(row.get("provider_floor_p75_usd_gpu_hr")),
    }


def _observation_window(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    timestamps = sorted(
        {
            str(row.get("observed_at"))
            for row in rows
            if row.get("observed_at")
        }
    )
    return {
        "started_at": timestamps[0] if timestamps else None,
        "ended_at": timestamps[-1] if timestamps else None,
    }


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _without(source: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    omitted = set(keys)
    return {key: value for key, value in source.items() if key not in omitted}
