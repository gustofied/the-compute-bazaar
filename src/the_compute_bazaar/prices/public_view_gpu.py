"""Build public GPU benchmark cards."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .public_view_common import card, number, observation_window


GPU_FAMILIES = ("H100", "H200", "B200", "B300")


def gpu_benchmark_view(
    *,
    manifest: Mapping[str, Any],
    family_id: str,
    current: Mapping[str, Any] | None,
    history: list[Mapping[str, Any]],
    constituents: list[Mapping[str, Any]],
    methodology: str,
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
    family_constituents = [
        dict(row)
        for row in constituents
        if str(row.get("benchmark_family_id") or "").upper() == family
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
    value = number(latest.get("benchmark_usd_gpu_hr"))
    return card(
        manifest=dict(manifest),
        card_type="gpu_benchmark",
        card_id=f"gpu-benchmark:{family.lower()}",
        as_of=observed_at,
        status="live" if value is not None else "unavailable",
        unit="USD per GPU-hour",
        methodology={
            "id": methodology,
            "basis": latest.get("benchmark_basis"),
            "query_id": latest.get("methodology_query_id"),
        },
        headline={
            "label": f"{family} observed benchmark",
            "value": value,
            "lower": number(latest.get("provider_floor_p25_usd_gpu_hr")),
            "upper": number(latest.get("provider_floor_p75_usd_gpu_hr")),
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
            {"label": provider, "role": "included provider floor"}
            for provider in providers
        ],
        drilldown_ref=f"gpu-benchmark/{family.lower()}.json",
        data={
            "family_id": family,
            "current": latest or None,
            "constituents": family_constituents,
        },
        observation_window=observation_window(family_history),
    )


def _benchmark_series_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "observed_at": row.get("gold_observed_at")
        or row.get("calculated_at")
        or row.get("latest_observed_at"),
        "value": number(row.get("benchmark_usd_gpu_hr")),
        "lower": number(row.get("provider_floor_p25_usd_gpu_hr")),
        "upper": number(row.get("provider_floor_p75_usd_gpu_hr")),
        "provider_count": int(row.get("provider_count") or 0),
        "offer_count": int(row.get("included_offer_count") or 0),
        "run_id": row.get("gold_run_id"),
    }
