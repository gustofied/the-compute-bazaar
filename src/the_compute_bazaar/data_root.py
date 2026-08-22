"""Resolve the market lake used by the CLI and API."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LakeSelection:
    root: str
    kind: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_synced_lake_root() -> str:
    configured = os.getenv("COMPUTE_BAZAAR_DATA_HOME")
    if configured:
        return str(Path(configured).expanduser() / "lake")
    cache_home = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    return str(cache_home / "compute-bazaar" / "lake")


def default_local_pipeline_root() -> str:
    configured = os.getenv("COMPUTE_BAZAAR_LOCAL_HOME")
    if configured:
        return str(Path(configured).expanduser())
    data_home = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return str(data_home / "compute-bazaar" / "local")


def resolve_lake_root(explicit: str | None = None) -> LakeSelection:
    if explicit:
        return LakeSelection(explicit.rstrip("/"), "explicit", "explicit lake")

    configured = os.getenv("COMPUTE_BAZAAR_LAKE_ROOT")
    if configured:
        return LakeSelection(
            configured.rstrip("/"),
            "environment",
            "COMPUTE_BAZAAR_LAKE_ROOT",
        )

    return LakeSelection(
        default_synced_lake_root(),
        "public_cache",
        "public lake cache",
    )
