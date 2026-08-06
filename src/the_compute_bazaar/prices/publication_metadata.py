"""Metadata for immutable market-card publications."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ..publication_contract import PublicationRoute
from .publication_chart_common import (
    GPU_RANGE_PRESENTATION,
    _finite_number,
    _format_cents,
    _format_observed,
    _format_observed_date,
    _format_usd,
    _parse_datetime,
    _prime_publication_series,
    _range_change,
    _series_change,
    _visible_gpu_series,
)


def gpu_publication_metadata(
    *,
    cards: Mapping[str, Mapping[str, Any]],
    selected_family: str,
    range_id: str,
    page_url: str,
    image_url: str,
    live_url: str,
    route: PublicationRoute,
) -> dict[str, Any]:
    series = _visible_gpu_series(cards, range_id)
    rows = series.get(selected_family, [])
    latest = rows[-1] if rows else None
    card = cards[selected_family]
    coverage = card.get("coverage") or {}
    value = _format_usd(latest["value"]) if latest else "pending"
    observed_at = latest["date"].isoformat() if latest else str(card.get("as_of") or "")
    provider_count = int(coverage.get("provider_count") or 0)
    change = _range_change(rows, range_id)
    title_parts = [f"{selected_family} GPU Price Index", f"{value}/GPU-hour"]
    if change["value"] is not None:
        title_parts.append(change["label"])
    title = " | ".join(title_parts)
    description = (
        f"{selected_family} observed GPU benchmark at {value} per GPU-hour, "
        f"{change['label'].lower()}. "
        f"Observed through {_format_observed_date(latest['date'] if latest else None)}"
    )
    if provider_count:
        description += f" across {provider_count} providers"
    description += "."
    display_line = (
        f"{selected_family} / {GPU_RANGE_PRESENTATION[range_id]['label']} / "
        f"{str(change['label']).lower()} / observed "
        f"{_format_observed_date(latest['date'] if latest else None).replace(' at ', ', ')}"
    )
    return {
        "title": title,
        "description": description,
        "page_url": page_url,
        "image_url": image_url,
        "live_url": live_url,
        "data_url": (
            f"{page_url.split('/publications/', 1)[0]}/gpu-benchmark/"
            f"{selected_family.lower()}.json"
        ),
        "image_alt": (
            f"{selected_family} GPU price index at {value} per GPU-hour, "
            f"{change['label'].lower()}"
        ),
        "family_id": selected_family,
        "range": range_id,
        "range_label": GPU_RANGE_PRESENTATION[range_id]["label"],
        "value": value,
        "change_pct": change["value"],
        "change_label": change["label"],
        "change_direction": change["direction"],
        "observed_at": observed_at,
        "observed_label": _format_observed(
            latest["date"] if latest else _parse_datetime(card.get("as_of"))
        ),
        "footer_label": display_line,
        "display_line": display_line,
        "revision": route.revision,
        "publication_id": route.publication_id,
        "route": route.as_dict(),
    }


def prime_offer_publication_metadata(
    *,
    card: Mapping[str, Any],
    family: str,
    observed_at: datetime | None,
) -> dict[str, Any]:
    rows = _prime_publication_series(card)
    latest = rows[-1] if rows else None
    value = _format_usd(latest["price"]) if latest else "pending"
    offers = int(latest["offers"]) if latest else 0
    change = _series_change(rows)
    observed_label = _format_observed_date(observed_at)
    display_line = (
        f"{family} / {value} per GPU-hour / {offers} "
        f"{'offer' if offers == 1 else 'offers'} / observed "
        f"{observed_label.replace(' at ', ', ')}"
    )
    return {
        "title": (
            f"Prime {family} GPU market | {value}/GPU-hour | "
            f"{offers} {'offer' if offers == 1 else 'offers'}"
        ),
        "description": (
            f"Prime {family} observed public market price at {value} per "
            f"GPU-hour with {offers} {'offer' if offers == 1 else 'offers'}. "
            f"{change['label']}. Observed {observed_label}."
        ),
        "image_alt": (
            f"Prime {family} market price at {value} per GPU-hour with "
            f"{offers} {'offer' if offers == 1 else 'offers'}"
        ),
        "subject_label": f"Prime {family} GPU market",
        "view_label": "Price and offers",
        "value": value,
        "observed_at": observed_at.isoformat() if observed_at else "",
        "observed_label": _format_observed(observed_at),
        "footer_label": display_line,
        "display_line": display_line,
        "change_pct": change["value"],
        "change_label": change["label"],
        "change_direction": change["direction"],
    }


def sandbox_workload_publication_metadata(
    *,
    card: Mapping[str, Any],
    observed_at: datetime | None,
) -> dict[str, Any]:
    headline = card.get("headline") or {}
    value = _format_cents(_finite_number(headline.get("median_estimated_cost_usd")))
    observed_label = _format_observed_date(observed_at)
    display_line = (
        f"StarSling / {value} median cost per job / "
        f"observed {observed_label.replace(' at ', ', ')}"
    )
    return {
        "title": f"Measured workload cost | {value} median per job",
        "description": (
            "Median estimated processor-and-memory cost for the latest compatible "
            f"StarSling HPC Sandbox Benchmark run. Observed {observed_label}."
        ),
        "image_alt": (
            "Latest StarSling HPC Sandbox Benchmark run with median estimated "
            f"job cost of {value}"
        ),
        "subject_label": "Measured workload cost",
        "view_label": "Latest measured run",
        "value": value,
        "observed_at": observed_at.isoformat() if observed_at else "",
        "observed_label": _format_observed(observed_at),
        "footer_label": display_line,
        "display_line": display_line,
        "change_pct": None,
        "change_label": None,
        "change_direction": "unknown",
    }
