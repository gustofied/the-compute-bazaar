"""Store and discover immutable Gold market manifests."""

from __future__ import annotations

import re
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
    return dict(read_json(latest_gold_manifest_ref(lake_root)))


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
            manifest = dict(read_json(ref))
        except Exception as exc:
            raise RuntimeError(f"Cannot read Gold history manifest: {ref}") from exc
        if canonical_market_runs_only and not is_canonical_market_run_id(
            manifest.get("run_id")
        ):
            continue
        if manifest.get("table_refs", {}).get("fact_benchmark_values"):
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
