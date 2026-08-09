"""Process lifecycle for the local Compute Bazaar Terminal."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from errno import EADDRINUSE
from pathlib import Path
from socket import AF_INET, SOCK_STREAM, socket
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


DEFAULT_EVALUATION_ROOT = Path("compute-bazaar-bench/jobs/reports")
STATE_ROOT = (
    Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    / "compute-bazaar"
    / "terminal"
)


class TerminalLifecycleError(RuntimeError):
    """Raised when the local Terminal cannot be started or stopped cleanly."""


def launch_terminal(
    *,
    lake_root: str,
    port: int,
    initial_view: str | None = None,
    initial_query: str | None = None,
    initial_sql: str | None = None,
    initial_limit: int = 500,
    initial_perspective: dict[str, Any] | None = None,
    evaluation_root: Path = DEFAULT_EVALUATION_ROOT,
) -> str:
    """Open the native Terminal, falling back to its browser surface."""
    _terminal_runtime()
    existing = _read_state()
    has_initial_state = any(
        (initial_view, initial_query, initial_sql, initial_perspective)
    )
    if existing and existing.get("mode") == "native":
        native_pid = existing.get("native_pid")
        native_healthy = _process_alive(native_pid) and bool(
            _terminal_health(existing.get("url"))
        )
        if native_healthy and not has_initial_state:
            return "Compute Bazaar Terminal is already open."
        _terminate_process_group(existing.get("pid"))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _process_alive(native_pid):
            time.sleep(0.1)
        if _process_alive(native_pid):
            _terminate_process(native_pid)
        _state_path().unlink(missing_ok=True)
        (STATE_ROOT / "ready.json").unlink(missing_ok=True)

    project_root = Path(__file__).resolve().parents[3]
    terminal_root = project_root / "terminal"
    tauri = terminal_root / "node_modules" / ".bin" / "tauri"
    if not tauri.is_file():
        return _launch_browser_terminal(
            lake_root=lake_root,
            port=port,
            initial_view=initial_view,
            initial_query=initial_query,
            initial_sql=initial_sql,
            initial_limit=initial_limit,
            initial_perspective=initial_perspective,
            evaluation_root=evaluation_root,
        )
    if existing and _terminal_health(existing.get("url")) == existing.get("pid"):
        os.kill(int(existing["pid"]), signal.SIGTERM)
        _state_path().unlink(missing_ok=True)

    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = STATE_ROOT / "terminal.log"
    ready_path = STATE_ROOT / "ready.json"
    ready_path.unlink(missing_ok=True)
    selected_port = _available_port(port)
    environment = os.environ.copy()
    cargo_bin = Path.home() / ".cargo" / "bin"
    environment["PATH"] = os.pathsep.join((str(cargo_bin), environment.get("PATH", "")))
    environment.update(
        {
            "COMPUTE_BAZAAR_PYTHON": sys.executable,
            "COMPUTE_BAZAAR_LAKE_ROOT": lake_root,
            "COMPUTE_BAZAAR_PROJECT_ROOT": str(project_root),
            "COMPUTE_BAZAAR_EVALUATION_ROOT": str(evaluation_root.resolve()),
            "COMPUTE_BAZAAR_TERMINAL_PORT": str(selected_port),
            "COMPUTE_BAZAAR_TERMINAL_READY_FILE": str(ready_path),
            "COMPUTE_BAZAAR_TERMINAL_INITIAL_LIMIT": str(initial_limit),
        }
    )
    if initial_view:
        environment["COMPUTE_BAZAAR_TERMINAL_VIEW"] = initial_view
    if initial_query:
        environment["COMPUTE_BAZAAR_TERMINAL_INITIAL_QUERY"] = initial_query
    if initial_sql:
        environment["COMPUTE_BAZAAR_TERMINAL_INITIAL_SQL"] = initial_sql
    if initial_perspective:
        environment["COMPUTE_BAZAAR_TERMINAL_INITIAL_PERSPECTIVE"] = json.dumps(
            initial_perspective,
            separators=(",", ":"),
        )

    with log_path.open("wb") as output:
        process = subprocess.Popen(
            [str(tauri), "dev"],
            cwd=terminal_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    ready: dict[str, Any] | None = None
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise TerminalLifecycleError(f"Terminal failed to start. See {log_path}")
        ready = _read_json(ready_path)
        if ready and _terminal_health(ready.get("url")):
            break
        time.sleep(0.1)
    else:
        _terminate_process_group(process.pid)
        raise TerminalLifecycleError(f"Terminal did not become ready. See {log_path}")

    assert ready is not None
    _write_state(
        mode="native",
        pid=process.pid,
        native_pid=int(ready["pid"]),
        url=str(ready["url"]),
        log_path=log_path,
    )
    return "Compute Bazaar Terminal opened."


def run_terminal(
    *,
    lake_root: str,
    port: int,
    open_browser: bool,
    initial_view: str | None = None,
    initial_query: str | None = None,
    initial_sql: str | None = None,
    initial_limit: int = 500,
    initial_perspective: dict[str, Any] | None = None,
    evaluation_root: Path = DEFAULT_EVALUATION_ROOT,
    announce: Callable[[str], None] = print,
) -> None:
    """Run the Terminal server in the foreground."""
    uvicorn, create_terminal_app = _terminal_runtime()
    selected_port = _available_port(port)
    url = f"http://127.0.0.1:{selected_port}"
    browser_url = (
        f"{url}/data"
        if any((initial_view, initial_query, initial_sql, initial_perspective))
        else url
    )
    if selected_port != port:
        announce(f"Port {port} is busy; using {selected_port}.")
    announce(f"Terminal: {url}")
    if open_browser:
        from threading import Timer
        from webbrowser import open as open_url

        Timer(0.8, open_url, args=(browser_url,)).start()
    uvicorn.run(
        create_terminal_app(
            lake_root=lake_root,
            evaluation_root=evaluation_root,
            initial_view=initial_view,
            initial_query=initial_query,
            initial_sql=initial_sql,
            initial_limit=initial_limit,
            initial_perspective=initial_perspective,
        ),
        host="127.0.0.1",
        port=selected_port,
    )


def stop_terminal() -> str:
    """Stop a Terminal process started by the CLI."""
    state = _read_state()
    if not state:
        _state_path().unlink(missing_ok=True)
        return "Terminal is not running."
    if state.get("mode") == "native":
        launcher_pid = state.get("pid")
        native_pid = state.get("native_pid")
        if not _process_alive(launcher_pid) and not _process_alive(native_pid):
            _state_path().unlink(missing_ok=True)
            return "Terminal is not running."
        _terminate_process_group(launcher_pid)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _process_alive(native_pid):
            time.sleep(0.1)
        if _process_alive(native_pid):
            _terminate_process(native_pid)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and _process_alive(native_pid):
                time.sleep(0.1)
        if _process_alive(native_pid):
            raise TerminalLifecycleError(
                f"Terminal process {native_pid} did not stop. See {state.get('log')}"
            )
        _state_path().unlink(missing_ok=True)
        (STATE_ROOT / "ready.json").unlink(missing_ok=True)
        return "Terminal stopped."
    if _terminal_health(state.get("url")) != state.get("pid"):
        _state_path().unlink(missing_ok=True)
        return "Terminal is not running."
    pid = int(state["pid"])
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _state_path().unlink(missing_ok=True)
        return "Terminal stopped."
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _terminal_health(state.get("url")) == pid:
        time.sleep(0.1)
    if _terminal_health(state.get("url")) == pid:
        raise TerminalLifecycleError(
            f"Terminal process {pid} did not stop. See {state.get('log')}"
        )
    _state_path().unlink(missing_ok=True)
    return "Terminal stopped."


def _launch_browser_terminal(
    *,
    lake_root: str,
    port: int,
    initial_view: str | None,
    initial_query: str | None,
    initial_sql: str | None,
    initial_limit: int,
    initial_perspective: dict[str, Any] | None,
    evaluation_root: Path,
) -> str:
    existing = _read_state()
    has_initial_state = any(
        (initial_view, initial_query, initial_sql, initial_perspective)
    )
    if existing and _terminal_health(existing.get("url")) == existing.get("pid"):
        if not has_initial_state:
            from webbrowser import open as open_url

            open_url(str(existing["url"]))
            return f"Compute Bazaar Terminal is already open: {existing['url']}"
        os.kill(int(existing["pid"]), signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _terminal_health(
            existing.get("url")
        ) == existing.get("pid"):
            time.sleep(0.1)
    _state_path().unlink(missing_ok=True)

    selected_port = _available_port(port)
    url = f"http://127.0.0.1:{selected_port}"
    browser_url = (
        f"{url}/data"
        if any((initial_view, initial_query, initial_sql, initial_perspective))
        else url
    )
    command = [
        sys.executable,
        "-m",
        "the_compute_bazaar.cli",
        "--lake-root",
        lake_root,
        "terminal",
        "--foreground",
        "--no-open",
        "--port",
        str(selected_port),
        "--evaluation-root",
        str(evaluation_root.resolve()),
        "--initial-limit",
        str(initial_limit),
    ]
    if initial_view:
        command.extend(("--view", initial_view))
    if initial_query:
        command.extend(("--initial-query", initial_query))
    if initial_sql:
        command.extend(("--initial-sql", initial_sql))
    if initial_perspective:
        command.extend(
            (
                "--initial-perspective",
                json.dumps(initial_perspective, separators=(",", ":")),
            )
        )

    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = STATE_ROOT / "terminal.log"
    with log_path.open("wb") as output:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise TerminalLifecycleError(f"Terminal failed to start. See {log_path}")
        if _terminal_health(url) == process.pid:
            break
        time.sleep(0.1)
    else:
        _terminate_process_group(process.pid)
        raise TerminalLifecycleError(f"Terminal did not become ready. See {log_path}")

    _write_state(
        mode="browser",
        pid=process.pid,
        native_pid=process.pid,
        url=url,
        log_path=log_path,
    )
    from webbrowser import open as open_url

    open_url(browser_url)
    return f"Compute Bazaar Terminal opened: {browser_url}"


def _state_path() -> Path:
    return STATE_ROOT / "runtime.json"


def _read_state() -> dict[str, Any] | None:
    return _read_json(_state_path())


def _write_state(
    *,
    mode: str,
    pid: int,
    native_pid: int,
    url: str,
    log_path: Path,
) -> None:
    payload = {
        "mode": mode,
        "pid": pid,
        "native_pid": native_pid,
        "url": url,
        "log": str(log_path),
    }
    temporary = _state_path().with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(_state_path())


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _process_alive(value: Any) -> bool:
    if not isinstance(value, int) or value <= 0:
        return False
    try:
        os.kill(value, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _terminate_process_group(value: Any) -> None:
    if not isinstance(value, int) or value <= 0:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(value, signal.SIGTERM)
        else:
            os.kill(value, signal.SIGTERM)
    except ProcessLookupError:
        return


def _terminate_process(value: Any) -> None:
    if not isinstance(value, int) or value <= 0:
        return
    try:
        os.kill(value, signal.SIGTERM)
    except ProcessLookupError:
        return


def _terminal_health(url: Any) -> int | None:
    if not isinstance(url, str) or not url.startswith("http://127.0.0.1:"):
        return None
    try:
        with urlopen(f"{url}/healthz", timeout=0.3) as response:
            payload = json.load(response)
    except (OSError, URLError, ValueError):
        return None
    if payload.get("contract") != "compute-bazaar.terminal.health.v1":
        return None
    pid = payload.get("pid")
    return pid if isinstance(pid, int) else None


def _terminal_runtime() -> tuple[Any, Any]:
    try:
        import uvicorn

        from . import create_terminal_app
    except ImportError as exc:
        raise TerminalLifecycleError(
            "The terminal requires: uv sync --extra terminal"
        ) from exc
    return uvicorn, create_terminal_app


def _available_port(preferred: int) -> int:
    for candidate in range(preferred, min(preferred + 100, 65_536)):
        with socket(AF_INET, SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError as exc:
                if exc.errno == EADDRINUSE:
                    continue
                raise
        return candidate
    raise TerminalLifecycleError(f"No free local port found from {preferred}")
