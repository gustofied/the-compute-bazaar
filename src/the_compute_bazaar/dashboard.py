"""Local FastAPI dashboard for the Compute Bazaar."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .prices.storage import list_refs, read_json


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = PROJECT_ROOT / "prototypes" / "compute-bazaar"
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "dashboard" / "compute-bazaar"
SNAPSHOT_FILES = {
    "manifest": "manifest.json",
    "market-run": "market-run.json",
    "market-history": "market-history.json",
    "latest-index": "latest-index.json",
    "index-constituents": "index-constituents.json",
    "index-quality": "index-quality.json",
    "index-history": "index-history.json",
    "provider-comparison": "provider-comparison.json",
    "listings-sample": "listings-sample.json",
}


def create_app(
    *,
    dashboard_dir: Path = DASHBOARD_DIR,
    snapshot_dir: Path = SNAPSHOT_DIR,
    snapshot_source: str | None = None,
    snapshot_s3_prefix: str | None = None,
) -> FastAPI:
    app = FastAPI(title="Compute Bazaar Dashboard", version="0.1.0")
    source = _resolve_snapshot_source(snapshot_source, snapshot_s3_prefix)
    s3_prefix = _snapshot_s3_prefix(snapshot_s3_prefix)

    if snapshot_dir.exists():
        app.mount(
            "/data/dashboard/compute-bazaar",
            StaticFiles(directory=snapshot_dir),
            name="dashboard-snapshots",
        )

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse(url="/dashboard/")

    @app.api_route("/dashboard", methods=["GET", "HEAD"], include_in_schema=False)
    def dashboard_redirect() -> RedirectResponse:
        return RedirectResponse(url="/dashboard/")

    @app.api_route("/dashboard/", methods=["GET", "HEAD"], include_in_schema=False)
    def dashboard() -> FileResponse:
        return _file_response(dashboard_dir / "feeling_the_compute.html")

    @app.api_route("/dashboard/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def dashboard_asset(path: str) -> FileResponse:
        return _file_response(_safe_child(dashboard_dir, path))

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "dashboard": str(dashboard_dir),
            "snapshots": str(snapshot_dir),
            "snapshot_source": source,
            "snapshot_s3_prefix": s3_prefix,
            "snapshot_api_base": "/api/dashboard-snapshots",
            "available_snapshots": _available_snapshots(snapshot_dir, source=source, s3_prefix=s3_prefix),
        }

    @app.get("/api/snapshots")
    def snapshots(response: Response) -> dict[str, Any]:
        _no_store(response)
        manifest = _read_snapshot(snapshot_dir, "manifest", source=source, s3_prefix=s3_prefix)
        market_run = _read_optional_snapshot(snapshot_dir, "market-run", source=source, s3_prefix=s3_prefix)
        return {
            "source": source,
            "s3_prefix": s3_prefix,
            "snapshots": _available_snapshots(snapshot_dir, source=source, s3_prefix=s3_prefix),
            "manifest": manifest,
            "market_run": market_run,
        }

    @app.get("/api/snapshots/{name}")
    def snapshot(name: str, response: Response) -> Any:
        _no_store(response)
        return _read_snapshot(snapshot_dir, name, source=source, s3_prefix=s3_prefix)

    @app.get("/api/dashboard-snapshots/{filename}")
    def dashboard_snapshot(filename: str, response: Response) -> Any:
        _no_store(response)
        name = _snapshot_name_for_filename(filename)
        return _read_snapshot(snapshot_dir, name, source=source, s3_prefix=s3_prefix)

    return app


def main() -> None:
    _load_local_env(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(prog="compute-bazaar-dashboard")
    parser.add_argument("--host", default=os.getenv("COMPUTE_BAZAAR_DASHBOARD_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("COMPUTE_BAZAAR_DASHBOARD_PORT", "8765")),
    )
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port)


def _file_response(path: Path) -> FileResponse:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


def _safe_child(root: Path, path: str) -> Path:
    candidate = (root / path).resolve()
    root_resolved = root.resolve()
    if root_resolved != candidate and root_resolved not in candidate.parents:
        raise HTTPException(status_code=404, detail="File not found")
    return candidate


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
    if not configured.startswith("s3://"):
        return None
    return configured.rstrip("/")


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
            filenames = {ref.rsplit("/", 1)[-1] for ref in list_refs(s3_prefix, suffix=".json")}
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
            raise HTTPException(status_code=500, detail="S3 dashboard source is configured without an S3 prefix")
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
    if "/" in filename or "\\" in filename:
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


_load_local_env(PROJECT_ROOT / ".env")
app = create_app()


if __name__ == "__main__":
    main()
