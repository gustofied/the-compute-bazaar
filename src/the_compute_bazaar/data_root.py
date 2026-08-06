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


def bundled_sample_lake_root() -> str:
    return str(Path(__file__).with_name("sample_lake"))


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
        bundled_sample_lake_root(),
        "bundled_sample",
        "bundled public snapshot",
    )
