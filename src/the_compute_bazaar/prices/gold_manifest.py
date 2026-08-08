"""Store and discover immutable Gold market manifests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..contracts import GOLD_MARKET_CONTRACT, require_contract
from .storage import read_json


GOLD_MANIFEST_TABLE = "gold_market"


def latest_gold_manifest_ref(lake_root: str) -> str:
    return "/".join(
        [lake_root.rstrip("/"), "_manifests", GOLD_MANIFEST_TABLE, "latest.json"]
    )


def gold_manifest_ref(lake_root: str, *, observed_date: str, run_id: str) -> str:
    return "/".join(
        [
            lake_root.rstrip("/"),
            "_manifests",
            GOLD_MANIFEST_TABLE,
            f"date={observed_date}",
            f"run_id={run_id}.json",
        ]
    )


def read_latest_gold_manifest(lake_root: str) -> dict[str, Any]:
    manifest = dict(read_json(latest_gold_manifest_ref(lake_root)))
    require_contract(manifest, contract=GOLD_MARKET_CONTRACT)
    return _resolve_lake_relative_refs(
        manifest,
        lake_root=lake_root,
    )


def is_canonical_market_run_id(run_id: Any) -> bool:
    return bool(
        re.fullmatch(
            r"gold-market-\d{8}T\d{6}-[0-9a-f]{8}",
            str(run_id or ""),
        )
    )


def _resolve_lake_relative_refs(
    manifest: dict[str, Any],
    *,
    lake_root: str,
) -> dict[str, Any]:
    if manifest.get("ref_base") != "lake_root":
        return manifest
    if "://" in lake_root:
        raise ValueError("lake-relative manifests require a local lake root")

    root = Path(lake_root).resolve()
    for field in (
        "source_manifest_refs",
        "source_normalized_refs",
        "source_market_state_refs",
        "table_refs",
    ):
        values = dict(manifest.get(field) or {})
        manifest[field] = {
            name: _resolve_ref(root, ref) for name, ref in values.items() if ref
        }
    manifest_ref = manifest.get("manifest_ref")
    if manifest_ref:
        manifest["manifest_ref"] = _resolve_ref(root, manifest_ref)
    return manifest


def _resolve_ref(root: Path, ref: Any) -> str:
    value = str(ref)
    path = Path(value)
    if "://" in value or path.is_absolute():
        raise ValueError("lake-relative manifests must use relative paths")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Lake reference escapes its root: {value}") from exc
    return str(resolved)
