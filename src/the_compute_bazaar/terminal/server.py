"""One local Terminal shell for Data, Eval, and future Trade workspaces."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .commands import (
    TerminalAction,
    TerminalCommandRequest,
    command_catalog,
    resolve_command,
)
from .data_workspace import DataWorkspace
from .eval_workspace import EvalWorkspace


ASSET_ROOT = Path(__file__).with_name("static")


def create_terminal_app(
    *,
    lake_root: str,
    evaluation_root: Path | None = None,
    initial_view: str | None = None,
    initial_query: str | None = None,
    initial_sql: str | None = None,
    initial_limit: int = 500,
    initial_perspective: dict[str, Any] | None = None,
) -> FastAPI:
    """Compose the native shell around independently owned workspaces."""
    data_workspace = DataWorkspace(
        lake_root=lake_root,
        asset_root=ASSET_ROOT,
        initial_view=initial_view,
        initial_query=initial_query,
        initial_sql=initial_sql,
        initial_limit=initial_limit,
        initial_perspective=initial_perspective,
    )
    eval_workspace = EvalWorkspace.load(evaluation_root)
    app = FastAPI(
        title="Compute Bazaar Terminal",
        description="Local entry point for market data and evaluations.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.data_workspace = data_workspace
    app.state.eval_workspace = eval_workspace

    app.mount(
        "/terminal-assets",
        StaticFiles(directory=str(ASSET_ROOT)),
        name="terminal-assets",
    )

    @app.get("/", include_in_schema=False)
    def menu() -> FileResponse:
        return FileResponse(ASSET_ROOT / "menu.html")

    @app.get("/eval", include_in_schema=False)
    def evaluations() -> RedirectResponse:
        if not eval_workspace.available:
            raise HTTPException(status_code=404, detail="No evaluation reports found")
        return RedirectResponse("/eval/", status_code=307)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/terminal")
    def terminal() -> dict[str, Any]:
        data_status = data_workspace.status()
        return {
            "contract": "compute-bazaar.terminal.v1",
            "run": data_status["run"],
            "table_count": data_status["table_count"],
            "destinations": {
                "data": {
                    "available": data_status["available"],
                    "href": data_status["href"],
                },
                "eval": eval_workspace.destination(),
                "trade": {"available": False, "href": None},
            },
            "commands": command_catalog(),
        }

    @app.post(
        "/api/terminal/command",
        response_model=TerminalAction,
        response_model_exclude_none=True,
    )
    def terminal_command(request: TerminalCommandRequest) -> TerminalAction:
        return resolve_command(request.command)

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        run = data_workspace.status()["run"]
        return {
            "contract": "compute-bazaar.terminal.health.v1",
            "status": "ok",
            "pid": os.getpid(),
            "run_id": run.get("run_id"),
            "eval_available": eval_workspace.available,
        }

    data_workspace.register(app)
    eval_workspace.mount(app)
    return app
