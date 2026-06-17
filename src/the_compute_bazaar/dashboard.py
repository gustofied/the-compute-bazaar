"""Local FastAPI dashboard for the Compute Bazaar."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = PROJECT_ROOT / "prototypes" / "compute-bazaar"
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "dashboard" / "compute-bazaar"
SNAPSHOT_FILES = {
    "manifest": "manifest.json",
    "latest-index": "latest-index.json",
    "provider-comparison": "provider-comparison.json",
    "listings-sample": "listings-sample.json",
}


def create_app(
    *,
    dashboard_dir: Path = DASHBOARD_DIR,
    snapshot_dir: Path = SNAPSHOT_DIR,
) -> FastAPI:
    app = FastAPI(title="Compute Bazaar Dashboard", version="0.1.0")

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
            "available_snapshots": _available_snapshots(snapshot_dir),
        }

    @app.get("/api/snapshots")
    def snapshots() -> dict[str, Any]:
        manifest = _read_snapshot(snapshot_dir, "manifest")
        return {
            "snapshots": _available_snapshots(snapshot_dir),
            "manifest": manifest,
        }

    @app.get("/api/snapshots/{name}")
    def snapshot(name: str) -> Any:
        return _read_snapshot(snapshot_dir, name)

    return app


def main() -> None:
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


def _available_snapshots(snapshot_dir: Path) -> list[str]:
    return [
        name
        for name, filename in SNAPSHOT_FILES.items()
        if (snapshot_dir / filename).is_file()
    ]


def _read_snapshot(snapshot_dir: Path, name: str) -> Any:
    filename = SNAPSHOT_FILES.get(name)
    if filename is None:
        raise HTTPException(status_code=404, detail=f"Unknown snapshot: {name}")

    path = snapshot_dir / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Snapshot not found: {name}")

    return json.loads(path.read_text(encoding="utf-8"))


app = create_app()


if __name__ == "__main__":
    main()
