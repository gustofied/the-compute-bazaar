"""Local AdamSioud site server with Compute Bazaar snapshot proxy."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .dashboard import (
    PROJECT_ROOT,
    SNAPSHOT_DIR,
    _available_snapshots,
    _load_local_env,
    _no_store,
    _read_optional_snapshot,
    _read_snapshot,
    _resolve_snapshot_source,
    _snapshot_name_for_filename,
    _snapshot_s3_prefix,
)


ADAM_SIOUD_DIR = PROJECT_ROOT / "external" / "AdamSioud"


def create_app(
    *,
    site_dir: Path = ADAM_SIOUD_DIR,
    snapshot_dir: Path = SNAPSHOT_DIR,
    snapshot_source: str | None = None,
    snapshot_s3_prefix: str | None = None,
) -> FastAPI:
    source = _resolve_snapshot_source(snapshot_source, snapshot_s3_prefix)
    s3_prefix = _snapshot_s3_prefix(snapshot_s3_prefix)
    app = FastAPI(title="AdamSioud Compute Bazaar Dev", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "site": str(site_dir),
            "snapshot_source": source,
            "snapshot_s3_prefix": s3_prefix,
            "snapshot_api_base": "/api/dashboard-snapshots",
            "available_snapshots": _available_snapshots(snapshot_dir, source=source, s3_prefix=s3_prefix),
            "compute_page": "/exemplars/compute/feeling_the_compute.html",
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

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse(url="/exemplars/compute/feeling_the_compute.html")

    app.mount("/", StaticFiles(directory=site_dir, html=True), name="adamsioud")
    return app


def main() -> None:
    _load_local_env(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(prog="compute-bazaar-adamsioud")
    parser.add_argument("--host", default=os.getenv("COMPUTE_BAZAAR_ADAM_SIOUD_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("COMPUTE_BAZAAR_ADAM_SIOUD_PORT", "8777")),
    )
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port)


app = create_app()


if __name__ == "__main__":
    main()
