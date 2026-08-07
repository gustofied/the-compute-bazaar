"""Build public Prime offer-market cards."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .public_view_common import card, number, observation_window


def prime_frontier_view(
    *,
    manifest: Mapping[str, Any],
    product: Mapping[str, Any],
    methodology: str,
    source: Mapping[str, Any],
    measurement_notes: list[str],
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
    value = number(current_row.get("reference_usd_gpu_hr"))
    source_rows = [
        dict(row) for row in product.get("sources", []) if isinstance(row, Mapping)
    ]
    return card(
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
            "id": methodology,
            "scope": current_row.get("reference_scope"),
            "notes": list(measurement_notes),
        },
        headline={
            "label": f"Prime {family} offer reference",
            "value": value,
            "market_benchmark": number(current_row.get("market_benchmark_usd_gpu_hr")),
            "best": number(current_row.get("best_usd_gpu_hr")),
        },
        series=history,
        band={
            "kind": "upstream_provider_floor_interquartile_range",
            "lower_field": "lower",
            "upper_field": "upper",
        },
        coverage={
            "upstream_provider_count": int(current_row.get("provider_count") or 0),
            "configuration_count": int(current_row.get("configuration_count") or 0),
            "observation_count": len(history),
        },
        sources=[dict(source), *source_rows],
        drilldown_ref=f"prime-frontier/{family.lower()}.json",
        data={key: item for key, item in dict(product).items() if key != "history"},
        observation_window=observation_window(history),
    )


def _prime_series_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(row),
        "observed_at": row.get("gold_observed_at")
        or row.get("latest_source_observed_at"),
        "value": number(row.get("reference_usd_gpu_hr")),
        "lower": number(row.get("provider_floor_p25_usd_gpu_hr")),
        "upper": number(row.get("provider_floor_p75_usd_gpu_hr")),
    }
