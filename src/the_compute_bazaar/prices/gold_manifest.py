"""Store and discover immutable Gold market manifests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .storage import list_refs, read_json


GOLD_MANIFEST_TABLE = "gold_market"
GOLD_MANIFEST_VERSION = "v1"


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
    return _resolve_lake_relative_refs(
        dict(read_json(latest_gold_manifest_ref(lake_root))),
        lake_root=lake_root,
    )


def list_gold_manifests(
    lake_root: str,
    *,
    limit: int = 48,
    canonical_market_runs_only: bool = False,
) -> list[dict[str, Any]]:
    requested_limit = max(1, int(limit))
    refs = [
        ref
        for ref in list_refs(gold_manifest_prefix(lake_root), suffix=".json")
        if "/run_id=" in ref or "/run_id%3D" in ref
    ]
    manifests: list[dict[str, Any]] = []
    for ref in refs:
        try:
            manifest = _resolve_lake_relative_refs(
                dict(read_json(ref)),
                lake_root=lake_root,
            )
        except Exception as exc:
            raise RuntimeError(f"Cannot read Gold history manifest: {ref}") from exc
        if canonical_market_runs_only and not is_canonical_market_run_id(
            manifest.get("run_id")
        ):
            continue
        if manifest.get("table_refs", {}).get("fact_gpu_price_index"):
            manifests.append(manifest)

    manifests.sort(key=lambda row: str(row.get("observed_at") or ""), reverse=True)
    return manifests[:requested_limit]


def gold_manifest_prefix(lake_root: str) -> str:
    return "/".join([lake_root.rstrip("/"), "_manifests", GOLD_MANIFEST_TABLE])


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
    if "://" in value or Path(value).is_absolute():
        return value
    return str(root / value)
