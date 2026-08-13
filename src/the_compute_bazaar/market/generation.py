"""Publish one market run as a queryable local lake generation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..contracts import MARKET_LAKE_CONTRACT
from .lake import MarketLake
from .pipeline import MarketRunResult


def publish_generation(lake: MarketLake, result: MarketRunResult) -> dict[str, Any]:
    if result.run.status != "complete" or not result.run.silver_ref:
        raise RuntimeError("Only complete market runs can be published")
    if "://" in lake.root:
        raise ValueError("Portable generation indexes currently require a local lake")

    root = Path(lake.root).expanduser().resolve()
    run = result.run
    day = run.observed_at.date()
    immutable_manifest_ref = lake.market_manifest_ref(day=day, run_id=run.run_id)
    manifest = {
        "contract": MARKET_LAKE_CONTRACT,
        "table": "market_snapshot",
        "catalog_kind": "market",
        "run_id": run.run_id,
        "observed_at": run.observed_at,
        "observed_date": day.isoformat(),
        "ref_base": "lake_root",
        "provider_scope": [run.source],
        "source_manifest_refs": {
            run.source: _relative(root, run.manifest_ref),
        },
        "source_normalized_refs": {
            run.source: _relative(root, run.silver_ref),
        },
        "silver_row_counts": {"gpu_offers": run.silver_row_count},
        "manifest_ref": _relative(root, immutable_manifest_ref),
    }
    lake.write_json(immutable_manifest_ref, manifest)
    lake.write_json(lake.latest_market_manifest_ref(), manifest)

    portable = {
        "contract": MARKET_LAKE_CONTRACT,
        "run_id": run.run_id,
        "observed_at": run.observed_at,
        "provider_scope": [run.source],
        "history_mode": "snapshot",
        "private_evidence_removed": False,
    }
    portable_ref = str(root / "portable.json")
    lake.write_json(portable_ref, portable)

    files = _inventory(
        root,
        refs=(
            run.raw_ref,
            run.silver_ref,
            run.manifest_ref,
            immutable_manifest_ref,
            lake.latest_market_manifest_ref(),
            portable_ref,
        ),
    )
    index = {
        **portable,
        "file_count": len(files),
        "files": files,
    }
    lake.write_json(str(root / "index.json"), index)
    return {
        "root": str(root),
        "run_id": run.run_id,
        "observed_at": run.observed_at,
        "providers": [run.source],
        "silver_rows": run.silver_row_count,
        "tables": ["silver.gpu_offers"],
    }


def _inventory(root: Path, *, refs: tuple[str, ...]) -> list[dict[str, Any]]:
    files = []
    for ref in sorted(set(refs)):
        path = Path(ref).expanduser().resolve()
        relative = path.relative_to(root).as_posix()
        with path.open("rb") as handle:
            checksum = hashlib.file_digest(handle, "sha256").hexdigest()
        files.append(
            {"path": relative, "size": path.stat().st_size, "sha256": checksum}
        )
    return files


def _relative(root: Path, ref: str | None) -> str:
    if not ref:
        raise ValueError("Market generation reference is missing")
    return Path(ref).expanduser().resolve().relative_to(root).as_posix()
