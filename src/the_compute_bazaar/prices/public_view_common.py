"""Shared schema helpers for public market cards."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


CARD_SCHEMA_VERSION = "compute_bazaar_card_v1"


def card(
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


def observation_window(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
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


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def without(source: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    omitted = set(keys)
    return {key: value for key, value in source.items() if key not in omitted}
