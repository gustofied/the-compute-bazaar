"""Build public market-state and run-overview cards."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .public_view_common import card, observation_window


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
    return card(
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
        },
        observation_window=observation_window(timestamps),
    )


def market_overview_view(
    *,
    manifest: Mapping[str, Any],
    benchmark_cards: list[Mapping[str, Any]],
) -> dict[str, Any]:
    benchmarks = []
    for benchmark_card in benchmark_cards:
        headline = benchmark_card.get("headline") or {}
        data = benchmark_card.get("data") or {}
        benchmarks.append(
            {
                "family_id": data.get("family_id"),
                "value": headline.get("value"),
                "lower": headline.get("lower"),
                "upper": headline.get("upper"),
                "provider_count": (benchmark_card.get("coverage") or {}).get(
                    "provider_count"
                ),
                "offer_count": (benchmark_card.get("coverage") or {}).get(
                    "offer_count"
                ),
                "status": benchmark_card.get("status"),
                "ref": (
                    "gpu-benchmark/"
                    f"{str(data.get('family_id') or '').lower()}.json"
                ),
            }
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
    return card(
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
        data={"market_run": public_run, "benchmarks": benchmarks},
        observation_window={
            "started_at": manifest.get("observed_at"),
            "ended_at": manifest.get("observed_at"),
        },
    )
