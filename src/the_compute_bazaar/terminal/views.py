"""DataFusion queries paired with useful viewer layouts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class TerminalView:
    view_id: str
    title: str
    description: str
    viewer: Literal["perspective"]
    viewer_config: dict[str, Any]
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
            "viewer": self.viewer,
            "viewer_config": self.viewer_config,
            "sql": self.sql,
            "tables": list(self.tables),
            "default_limit": self.default_limit,
        }


TERMINAL_VIEWS = (
    TerminalView(
        view_id="weekly-gpu-price-pulse",
        query_id="weekly_gpu_market_pulse",
        title="Weekly GPU price pulse",
        description="Seven days of daily median GPU-hour prices across H100, H200, B200, and B300.",
        viewer="perspective",
        viewer_config={
            "plugin": "Y Line",
            "group_by": ["observed_at"],
            "split_by": ["gpu"],
            "columns": ["price_usd_gpu_hr"],
            "settings": False,
        },
    ),
    TerminalView(
        view_id="weekly-gpu-provider-depth",
        query_id="weekly_gpu_market_pulse",
        title="Weekly marketplace depth",
        description="Observed providers per frontier GPU family through the latest seven days.",
        viewer="perspective",
        viewer_config={
            "plugin": "Y Bar",
            "group_by": ["observed_at"],
            "split_by": ["gpu"],
            "columns": ["provider_count"],
            "settings": False,
        },
    ),
    TerminalView(
        view_id="weekly-gpu-offer-depth",
        query_id="weekly_gpu_market_pulse",
        title="Weekly qualifying offers",
        description="Eligible index offers retained for each GPU family over the latest seven days.",
        viewer="perspective",
        viewer_config={
            "plugin": "Y Bar",
            "group_by": ["observed_at"],
            "split_by": ["gpu"],
            "columns": ["qualifying_offer_count"],
            "settings": False,
        },
    ),
    TerminalView(
        view_id="gpu-index-history",
        query_id="gpu_price_index_history",
        title="GPU Price Index",
        description="Daily medians of retained hourly H100, H200, B200, and B300 index values.",
        viewer="perspective",
        viewer_config={
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
        viewer="perspective",
        viewer_config={
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
        viewer="perspective",
        viewer_config={
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
        viewer="perspective",
        viewer_config={
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
        viewer="perspective",
        viewer_config={
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
        viewer="perspective",
        viewer_config={
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


MARKET_TERMINAL_VIEWS = (
    TerminalView(
        view_id="available-gpu-offers",
        title="Available GPU Offers",
        description="Available configurations retained from the latest provider read.",
        viewer="perspective",
        viewer_config={
            "plugin": "Datagrid",
            "columns": [
                "source",
                "intermediary",
                "operator",
                "gpu_model",
                "gpu_count",
                "region",
                "ask_usd_hr",
                "offer_id",
                "observation_id",
            ],
            "sort": [["ask_usd_hr", "asc"]],
            "settings": False,
        },
        sql="""select
  source,
  intermediary,
  operator_id,
  operator,
  gpu_model,
  gpu_count,
  country_code,
  region,
  ask_usd_hr,
  offer_id,
  observation_id,
  observed_at
from silver.gpu_offers
where available and gpu_model is not null
order by ask_usd_hr, gpu_model, gpu_count""",
        tables=("silver.gpu_offers",),
    ),
)


def terminal_views(manifest: dict[str, Any]) -> tuple[TerminalView, ...]:
    if manifest.get("catalog_kind") == "market":
        return MARKET_TERMINAL_VIEWS
    return TERMINAL_VIEWS


def get_terminal_view(view_id: str) -> TerminalView:
    for view in (*TERMINAL_VIEWS, *MARKET_TERMINAL_VIEWS):
        if view.view_id == view_id:
            return view
    raise KeyError(f"Unknown terminal view: {view_id}")
