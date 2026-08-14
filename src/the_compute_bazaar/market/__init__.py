"""Compute-market evidence, normalization, and query layer."""

from .catalog import MarketCatalog
from .contracts import GpuOffer, MarketRun, RejectedOffer
from .generation import publish_generation
from .lake import MarketLake, default_market_lake_root
from .launch import SesterceLauncher, SesterceLaunchPlan
from .pipeline import MarketPipeline, MarketRunResult
from .registry import MarketSourceRegistry, default_registry
from .sources.sesterce import SesterceSource

__all__ = [
    "GpuOffer",
    "MarketCatalog",
    "MarketLake",
    "MarketPipeline",
    "MarketRun",
    "MarketRunResult",
    "MarketSourceRegistry",
    "RejectedOffer",
    "SesterceSource",
    "SesterceLauncher",
    "SesterceLaunchPlan",
    "default_market_lake_root",
    "default_registry",
    "publish_generation",
]
