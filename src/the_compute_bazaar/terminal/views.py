"""DataFusion queries paired with useful Perspective layouts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TerminalView:
    view_id: str
    title: str
    description: str
    perspective: dict[str, Any]
    kind: str = "Data"
    query_id: str | None = None
    sql: str | None = None
    tables: tuple[str, ...] = ()
    default_limit: int = 500

    def as_dict(self) -> dict[str, Any]:
        return {
            "view_id": self.view_id,
            "query_id": self.query_id,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "perspective": self.perspective,
            "sql": self.sql,
            "tables": list(self.tables),
            "default_limit": self.default_limit,
        }


TERMINAL_VIEWS = (
    TerminalView(
        view_id="gpu-index-history",
        query_id="gpu_price_index_history",
        title="GPU Price Index",
        description="Daily medians of retained hourly H100, H200, B200, and B300 index values.",
        perspective={
            "plugin": "Y Line",
            "group_by": ["observed_at"],
            "split_by": ["gpu"],
            "columns": ["price_usd_gpu_hr"],
            "settings": False,
        },
    ),
    TerminalView(
        view_id="gpu-index-snapshot",
        query_id="gpu_price_index",
        title="Latest GPU Index",
        description="The latest index value for each frontier GPU family.",
        perspective={
            "plugin": "Y Bar",
            "group_by": ["benchmark_family_id"],
            "columns": ["benchmark_usd_gpu_hr"],
            "settings": False,
        },
    ),
    TerminalView(
        view_id="prime-offer-market",
        query_id="prime_offer_history",
        title="Prime Offer Market",
        description="Prime's lowest visible asks by GPU family through time.",
        perspective={
            "plugin": "Y Line",
            "group_by": ["gold_observed_at"],
            "split_by": ["gpu_family_id"],
            "columns": ["reference_usd_gpu_hr"],
            "settings": False,
        },
    ),
    TerminalView(
        view_id="prime-offer-ladder",
        query_id="prime_offer_levels",
        title="Prime Offer Ladder",
        description="Current Prime configurations grouped by GPU-hour price level.",
        perspective={
            "plugin": "Y Bar",
            "group_by": ["price_level_usd_gpu_hr"],
            "split_by": ["gpu_family_id"],
            "columns": ["configuration_count"],
            "settings": False,
        },
    ),
    TerminalView(
        view_id="akash-occupancy",
        query_id="akash_gpu_occupancy",
        title="Akash GPU Occupancy",
        description="Rented and available share of observed Akash GPU capacity.",
        perspective={
            "plugin": "Y Line",
            "group_by": ["observed_at"],
            "columns": ["rented_pct", "available_pct"],
            "settings": False,
        },
    ),
    TerminalView(
        view_id="provider-floors",
        query_id="provider_comparison",
        title="Provider Floors",
        description="Normalized GPU-hour prices summarized by provider and model.",
        perspective={
            "plugin": "Datagrid",
            "columns": [
                "gpu_model",
                "provider",
                "floor_usd_gpu_hr",
                "simple_mean_usd_gpu_hr",
                "listing_count",
                "latest_observed_at",
            ],
            "sort": [["floor_usd_gpu_hr", "asc"]],
            "settings": False,
        },
    ),
)


def get_terminal_view(view_id: str) -> TerminalView:
    for view in TERMINAL_VIEWS:
        if view.view_id == view_id:
            return view
    raise KeyError(f"Unknown terminal view: {view_id}")
