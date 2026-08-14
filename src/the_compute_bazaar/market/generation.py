"""Publish one market run as a queryable local lake generation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..contracts import MARKET_LAKE_CONTRACT
from .contracts import stable_id
from .lake import MarketLake
from .pipeline import MarketRunResult


def publish_generation(
    lake: MarketLake,
    *results: MarketRunResult,
) -> dict[str, Any]:
    if not results:
        raise ValueError("A market generation needs at least one source run")
    runs = sorted((result.run for result in results), key=lambda run: run.source)
    if any(run.status != "complete" or not run.silver_ref for run in runs):
        raise RuntimeError("Only complete source runs can be published")
    sources = [run.source for run in runs]
    if len(set(sources)) != len(sources):
        raise ValueError("A market generation accepts one run per source")
    if "://" in lake.root:
        raise ValueError("Portable generation indexes currently require a local lake")

    root = Path(lake.root).expanduser().resolve()
    observed_at = max(run.observed_at for run in runs)
    generation_id = (
        f"market-{observed_at:%Y%m%dT%H%M%S}-"
        f"{stable_id(*(f'{run.source}:{run.source_run_id}' for run in runs), length=10)}"
    )
    day = observed_at.date()
    immutable_manifest_ref = lake.market_manifest_ref(
        day=day,
        generation_id=generation_id,
    )
    manifest = {
        "contract": MARKET_LAKE_CONTRACT,
        "table": "market_snapshot",
        "catalog_kind": "market",
        "market_generation_id": generation_id,
        "observed_at": observed_at,
        "observed_date": day.isoformat(),
        "ref_base": "lake_root",
        "source_scope": sources,
        "source_runs": {run.source: run.source_run_id for run in runs},
        "source_manifest_refs": {
            run.source: _relative(root, run.manifest_ref) for run in runs
        },
        "source_normalized_refs": {
            run.source: _relative(root, run.silver_ref) for run in runs
        },
        "silver_row_counts": {"gpu_offers": sum(run.silver_row_count for run in runs)},
        "manifest_ref": _relative(root, immutable_manifest_ref),
    }
    lake.write_json(immutable_manifest_ref, manifest)
    lake.write_json(lake.latest_market_manifest_ref(), manifest)

    portable = {
        "contract": MARKET_LAKE_CONTRACT,
        "market_generation_id": generation_id,
        "observed_at": observed_at,
        "source_scope": sources,
        "source_runs": manifest["source_runs"],
        "history_mode": "snapshot",
        "private_evidence_removed": False,
    }
    portable_ref = str(root / "portable.json")
    lake.write_json(portable_ref, portable)

    files = _inventory(
        root,
        refs=tuple(
            ref
            for run in runs
            for ref in (run.raw_ref, run.silver_ref, run.manifest_ref)
        )
        + (
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
        "market_generation_id": generation_id,
        "observed_at": observed_at,
        "sources": sources,
        "silver_rows": sum(run.silver_row_count for run in runs),
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
