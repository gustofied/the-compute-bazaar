"""Shared local and S3 readers for public dashboard snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, Response

from .prices.storage import list_refs, read_json


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "dashboard" / "compute-bazaar"
SNAPSHOT_FILES = {
    "manifest": "manifest.json",
    "market-run": "market-run.json",
    "market-history": "market-history.json",
    "latest-index": "latest-index.json",
    "featured-index": "featured-index.json",
    "featured-benchmarks": "featured-benchmarks.json",
    "benchmark-history": "benchmark-history.json",
    "sandbox-cost": "sandbox-cost.json",
    "index-constituents": "index-constituents.json",
    "index-quality": "index-quality.json",
    "index-history": "index-history.json",
    "benchmark-constituents": "benchmark-constituents.json",
    "provider-comparison": "provider-comparison.json",
    "listings-sample": "listings-sample.json",
    "market-state": "market-state.json",
    "prime-frontier-offer-market": "prime-frontier-offer-market.json",
    "prime-frontier-offer-shelf": "prime-frontier-offer-shelf.json",
    "prime-h100-offer-reference": "prime-h100-offer-reference.json",
    "market-overview": "market-overview.json",
    "gpu-benchmark-h100": "gpu-benchmark/h100.json",
    "gpu-benchmark-h200": "gpu-benchmark/h200.json",
    "gpu-benchmark-b200": "gpu-benchmark/b200.json",
    "gpu-benchmark-b300": "gpu-benchmark/b300.json",
    "prime-frontier-h100": "prime-frontier/h100.json",
    "prime-frontier-h200": "prime-frontier/h200.json",
    "prime-frontier-b200": "prime-frontier/b200.json",
    "prime-frontier-b300": "prime-frontier/b300.json",
    "capacity-market-state": "capacity/market-state.json",
    "sandbox-workload": "sandbox/workload.json",
}


def _resolve_snapshot_source(source: str | None, s3_prefix: str | None) -> str:
    configured = (source or os.getenv("COMPUTE_BAZAAR_DASHBOARD_SOURCE") or "auto").strip().lower()
    if configured == "auto":
        return "s3" if _snapshot_s3_prefix(s3_prefix) else "local"
    if configured not in {"local", "s3"}:
        raise RuntimeError("COMPUTE_BAZAAR_DASHBOARD_SOURCE must be one of: auto, local, s3")
    return configured


def _snapshot_s3_prefix(value: str | None = None) -> str | None:
    configured = (
        value
        or os.getenv("COMPUTE_BAZAAR_DASHBOARD_S3_PREFIX")
        or os.getenv("COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT")
        or ""
    ).strip()
    if configured:
        return configured.rstrip("/") if configured.startswith("s3://") else None
    return _infer_dashboard_s3_prefix_from_lake(os.getenv("COMPUTE_BAZAAR_LAKE_ROOT") or "")


def _infer_dashboard_s3_prefix_from_lake(lake_root: str) -> str | None:
    if not lake_root.startswith("s3://"):
        return None
    parsed = urlparse(lake_root.rstrip("/"))
    if not parsed.netloc:
        return None
    path_parts = [part for part in parsed.path.strip("/").split("/") if part]
    if not path_parts or path_parts[-1] != "lake":
        return None
    dashboard_parts = [*path_parts[:-1], "dashboard", "compute-bazaar"]
    return f"s3://{parsed.netloc}/{'/'.join(dashboard_parts)}"


def _available_snapshots(
    snapshot_dir: Path,
    *,
    source: str = "local",
    s3_prefix: str | None = None,
) -> list[str]:
    if source == "s3":
        if not s3_prefix:
            return []
        try:
            prefix = s3_prefix.rstrip("/") + "/"
            filenames = {
                ref[len(prefix) :]
                for ref in list_refs(s3_prefix, suffix=".json")
                if ref.startswith(prefix)
            }
        except Exception:
            return []
        return [name for name, filename in SNAPSHOT_FILES.items() if filename in filenames]

    return [
        name
        for name, filename in SNAPSHOT_FILES.items()
        if (snapshot_dir / filename).is_file()
    ]


def _read_snapshot(
    snapshot_dir: Path,
    name: str,
    *,
    source: str = "local",
    s3_prefix: str | None = None,
) -> Any:
    filename = SNAPSHOT_FILES.get(name)
    if filename is None:
        raise HTTPException(status_code=404, detail=f"Unknown snapshot: {name}")

    if source == "s3":
        if not s3_prefix:
            raise HTTPException(
                status_code=500,
                detail="S3 dashboard source is configured without an S3 prefix",
            )
        uri = f"{s3_prefix.rstrip('/')}/{filename}"
        try:
            return read_json(uri)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Snapshot not found in S3: {name}") from exc

    path = snapshot_dir / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Snapshot not found: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_snapshot(
    snapshot_dir: Path,
    name: str,
    *,
    source: str = "local",
    s3_prefix: str | None = None,
) -> Any:
    try:
        return _read_snapshot(snapshot_dir, name, source=source, s3_prefix=s3_prefix)
    except HTTPException:
        return None


def _snapshot_name_for_filename(filename: str) -> str:
    if (
        "\\" in filename
        or filename.startswith("/")
        or any(part in {"", ".", ".."} for part in filename.split("/"))
    ):
        raise HTTPException(status_code=404, detail="Snapshot not found")
    for name, candidate in SNAPSHOT_FILES.items():
        if filename == candidate:
            return name
    raise HTTPException(status_code=404, detail=f"Unknown snapshot file: {filename}")


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _load_local_env(path: Path) -> None:
    """Load simple KEY=VALUE lines from .env without overriding shell env."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
