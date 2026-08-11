"""One local Terminal shell for Data, Eval, and future Trade workspaces."""

from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .commands import (
    TerminalAction,
    TerminalCommandRequest,
    command_catalog,
    resolve_command,
)
from .data_workspace import DataWorkspace
from .eval_workspace import EvalWorkspace
from .fleet_workspace import FleetWorkspace
from .shell import TerminalShell, TerminalShellError


ASSET_ROOT = Path(__file__).with_name("static")
WORDMARK_PATH = (
    Path(__file__).resolve().parents[3] / "assets" / "compute-bazaar-wordmark.png"
)
STRICT_CSP = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'none'",
        "connect-src 'self' ws://127.0.0.1:* blob:",
        "font-src 'self' data:",
        "frame-ancestors 'none'",
        "img-src 'self' data:",
        "object-src 'none'",
        "script-src 'self' blob: 'wasm-unsafe-eval'",
        "style-src 'self' 'unsafe-inline'",
        "worker-src 'self' blob:",
    )
)
EVAL_CSP = STRICT_CSP.replace(
    "script-src 'self' blob: 'wasm-unsafe-eval'",
    "script-src 'self' blob: 'unsafe-inline' 'wasm-unsafe-eval'",
)
NATIVE_SESSION_COOKIE = "compute_bazaar_terminal_session"


class TerminalOpenRequest(BaseModel):
    action: TerminalAction


class TerminalLaunchMailbox:
    """Retain the latest local CLI handoff for the open Terminal window."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._latest: dict[str, Any] | None = None

    def publish(self, action: TerminalAction) -> dict[str, Any]:
        launch = {
            "launch_id": secrets.token_urlsafe(12),
            "action": action.model_dump(exclude_none=True),
        }
        with self._lock:
            self._latest = launch
        return launch

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._latest) if self._latest else None


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
    fleet_workspace = FleetWorkspace(asset_root=ASSET_ROOT)
    native_token = os.getenv("COMPUTE_BAZAAR_TERMINAL_NATIVE_TOKEN")
    control_token = os.getenv("COMPUTE_BAZAAR_TERMINAL_CONTROL_TOKEN")
    native_session = secrets.token_urlsafe(32) if native_token else None
    project_root = Path(os.getenv("COMPUTE_BAZAAR_PROJECT_ROOT", Path.cwd())).resolve()
    shell = TerminalShell(cwd=project_root) if native_token else None
    launch_mailbox = TerminalLaunchMailbox()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        fleet_workspace.start()
        try:
            yield
        finally:
            fleet_workspace.stop()
            if shell is not None:
                shell.close()

    app = FastAPI(
        title="Compute Bazaar Terminal",
        description="Local entry point for market data and evaluations.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.data_workspace = data_workspace
    app.state.eval_workspace = eval_workspace
    app.state.fleet_workspace = fleet_workspace
    app.state.shell = shell
    app.state.launch_mailbox = launch_mailbox

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            EVAL_CSP if request.url.path.startswith("/eval") else STRICT_CSP
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response

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
            raise HTTPException(
                status_code=404, detail="No evaluation tasks or jobs found"
            )
        return RedirectResponse("/eval/", status_code=307)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/terminal-wordmark.png", include_in_schema=False)
    def terminal_wordmark() -> FileResponse:
        return FileResponse(WORDMARK_PATH)

    @app.get("/api/terminal")
    def terminal(request: Request) -> dict[str, Any]:
        data_status = data_workspace.status()
        return {
            "contract": "compute-bazaar.terminal",
            "run": data_status["run"],
            "table_count": data_status["table_count"],
            "destinations": {
                "data": {
                    "available": data_status["available"],
                    "href": data_status["href"],
                },
                "fleet": fleet_workspace.destination(),
                "eval": eval_workspace.destination(),
                "trade": {"available": False, "href": None},
            },
            "commands": command_catalog(),
            "shell": {
                "available": shell is not None,
                "authorized": _valid_native_session(
                    request.cookies.get(NATIVE_SESSION_COOKIE), native_session
                ),
                "native_only": True,
            },
        }

    @app.post("/api/terminal/session", status_code=204)
    def terminal_session(request: Request) -> Response:
        if not _same_http_origin(request) or not _valid_native_session(
            request.headers.get("x-compute-bazaar-session"), native_token
        ):
            raise HTTPException(
                status_code=403, detail="Native Terminal session required"
            )
        response = Response(status_code=204)
        assert native_session is not None
        response.set_cookie(
            NATIVE_SESSION_COOKIE,
            native_session,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return response

    @app.post(
        "/api/terminal/command",
        response_model=TerminalAction,
        response_model_exclude_none=True,
    )
    def terminal_command(
        payload: TerminalCommandRequest,
        request: Request,
    ) -> TerminalAction:
        return resolve_command(
            payload.command,
            shell_fallback=_valid_native_session(
                request.cookies.get(NATIVE_SESSION_COOKIE),
                native_session,
            ),
        )

    @app.get("/api/terminal/open")
    def pending_open() -> dict[str, Any]:
        return {
            "contract": "compute-bazaar.terminal.open",
            "launch": launch_mailbox.latest(),
        }

    @app.post("/api/terminal/open", status_code=202)
    def open_in_terminal(
        payload: TerminalOpenRequest,
        request: Request,
    ) -> dict[str, Any]:
        if not _valid_native_session(
            request.headers.get("x-compute-bazaar-control"), control_token
        ):
            raise HTTPException(status_code=403, detail="Terminal control rejected")
        if payload.action.kind not in {"query", "view", "sql"}:
            raise HTTPException(status_code=400, detail="Unsupported Terminal launch")
        return {
            "contract": "compute-bazaar.terminal.open",
            "launch": launch_mailbox.publish(payload.action),
        }

    @app.websocket("/api/terminal/shell")
    async def terminal_shell(websocket: WebSocket) -> None:
        if shell is None or not _valid_native_session(
            websocket.cookies.get(NATIVE_SESSION_COOKIE), native_session
        ):
            await websocket.close(code=1008, reason="Native Terminal session required")
            return
        if not _same_origin(websocket):
            await websocket.close(code=1008, reason="Terminal origin rejected")
            return
        await websocket.accept()
        sender = asyncio.create_task(_send_shell_output(websocket, shell))
        receiver = asyncio.create_task(_receive_shell_input(websocket, shell))
        done, pending = await asyncio.wait(
            {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done | pending:
            with suppress(asyncio.CancelledError, RuntimeError, WebSocketDisconnect):
                await task

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        run = data_workspace.status()["run"]
        return {
            "contract": "compute-bazaar.terminal.health",
            "status": "ok",
            "pid": os.getpid(),
            "run_id": run.get("run_id"),
            "eval_available": eval_workspace.available,
            "fleet_hosts": len(fleet_workspace.service.hosts()),
        }

    data_workspace.register(app)
    fleet_workspace.register(app)
    eval_workspace.mount(app)
    return app


def _valid_native_session(candidate: str | None, expected: str | None) -> bool:
    return bool(candidate and expected and secrets.compare_digest(candidate, expected))


def _same_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    return not origin or bool(host and origin == f"http://{host}")


def _same_http_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    return not origin or origin == str(request.base_url).rstrip("/")


async def _receive_shell_input(
    websocket: WebSocket,
    shell: TerminalShell,
) -> None:
    while True:
        message = await websocket.receive_json()
        if not isinstance(message, dict):
            continue
        message_type = message.get("type")
        try:
            if message_type == "run":
                shell.submit(
                    str(message.get("command") or ""),
                    columns=_integer(message.get("columns"), 120),
                    rows=_integer(message.get("rows"), 32),
                )
            elif message_type == "input":
                data = str(message.get("data") or "")
                if len(data) <= 20_000:
                    shell.write(data)
            elif message_type == "resize":
                shell.resize(
                    columns=_integer(message.get("columns"), 120),
                    rows=_integer(message.get("rows"), 32),
                )
            elif message_type == "interrupt":
                shell.interrupt()
            elif message_type == "clear":
                shell.clear()
            elif message_type == "terminate":
                shell.close()
        except TerminalShellError as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})


async def _send_shell_output(
    websocket: WebSocket,
    shell: TerminalShell,
) -> None:
    cursor: int | None = None
    state_version = -1
    while True:
        snapshot = shell.snapshot(cursor=cursor)
        await websocket.send_json(snapshot)
        cursor = int(snapshot["cursor"])
        state_version = int(snapshot["state_version"])
        changed = await asyncio.to_thread(
            shell.wait_for_change,
            cursor=cursor,
            state_version=state_version,
        )
        if changed is None:
            continue


def _integer(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) else fallback
