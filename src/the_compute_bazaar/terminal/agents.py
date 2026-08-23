"""Persistent ACP agent sessions for the native Terminal."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

MAX_EVENTS = 400
MAX_PROMPT_LENGTH = 20_000
ACP_STREAM_LIMIT = 4 * 1024 * 1024
CONTROL_TIMEOUT_SECONDS = 10
CANCEL_CONTROL_TIMEOUT_SECONDS = 3
PROMPT_CANCEL_TIMEOUT_SECONDS = 5
AGENT_MODEL = "gpt-5.6-terra"
AGENT_REASONING_EFFORT = "medium"
SESSION_NAME = "compute-bazaar-terminal-terra-medium"
ACP_CONFIG = Path("terminal/acp.json")
DEFAULT_ACP_AGENT = Path("terminal/node_modules/.bin/codex-acp")
CODEX_ACCESS_MODES = {
    "read": "read-only",
    "full": "agent-full-access",
}
TERMINAL_CONTEXT = """<compute-bazaar-terminal>
Work in the Bazaar checkout using normal repo tools and `compute-bazaar`.
- Run Bazaar commands through `.venv/bin/compute-bazaar`; never use a global
  installation from another checkout.
- Read `.agents/skills/use-compute-bazaar/SKILL.md` before operating the desk.
- Inspect data with `compute-bazaar tables`, `compute-bazaar describe TABLE`, and
  `compute-bazaar sql \"SQL\"`.
- Put useful results in Data with `compute-bazaar query QUERY_ID --terminal` or
  `compute-bazaar sql \"SQL\" --terminal`.
- SQL handoffs support `--chart table|line|bar|area`; use `--x`, `--series`, and
  `--y` for quick charts. Use `--perspective '{...}'` to pass a complete
  Perspective view configuration.
- Move the desk with `compute-bazaar open data`, `fleet`, `eval`, or `terminal`.
Never stop or restart the running Terminal to show a result. Use `--terminal` or
`compute-bazaar open` to hand work to the instance that is already open.
Use `compute-bazaar COMMAND --help` when needed. Do not use GUI automation to
operate the Terminal.
</compute-bazaar-terminal>"""
READ_TERMINAL_CONTEXT = """<compute-bazaar-terminal>
This turn has Read access.

Inspect the Bazaar checkout and query its data without changing local or remote
state. Read-only `compute-bazaar` commands are allowed, including `tables`,
`describe`, `sql` with SELECT or WITH, `query`, `price-index`, `availability`, and
`open`. Put useful results in Data with `--terminal`, and move the desk with
`compute-bazaar open data`, `fleet`, `eval`, or `terminal`.
SQL handoffs support `--chart table|line|bar|area`, or a complete Perspective
view configuration through `--perspective '{...}'`.

Run Bazaar commands through `.venv/bin/compute-bazaar`; never use a global
installation from another checkout.

Read `.agents/skills/use-compute-bazaar/SKILL.md` before operating the desk.

Do not edit files, refresh or publish data, provision or terminate compute, run or
stop workloads, or execute any other state-changing command. Ask for Full access
only when the requested operation changes state.
</compute-bazaar-terminal>"""


class AgentSessionError(RuntimeError):
    """Raised when an ACP session cannot accept an operation."""


class AgentTerminal:
    """Own the ACP-backed agent shown in the Terminal rail."""

    def __init__(self, *, cwd: Path, executable: Path | None = None) -> None:
        self.cwd = cwd.resolve()
        self.executable = executable or _find_acpx(self.cwd)
        self.agent_command = _find_acp_agent(self.cwd)
        self._session = (
            AgentSession(
                cwd=self.cwd,
                executable=self.executable,
                agent_command=self.agent_command,
            )
            if self.executable and self.agent_command
            else None
        )

    def status(self) -> dict[str, Any]:
        return {
            "available": self._session is not None,
            "state": self._session.state if self._session else "idle",
        }

    def connect(self) -> "AgentSession":
        if self._session is None:
            raise AgentSessionError("ACP is unavailable; install Terminal dependencies")
        return self._session

    async def close(self) -> None:
        if self._session:
            await self._session.close()


class AgentSession:
    """Stream one named acpx session to any connected Terminal views."""

    def __init__(
        self,
        *,
        cwd: Path,
        executable: Path,
        agent_command: str,
    ) -> None:
        self.cwd = cwd
        self.executable = executable
        self.agent_command = agent_command
        self.session_name = _session_name(cwd)
        self.state = "idle"
        self.events: list[dict[str, Any]] = []
        self._listeners: set[asyncio.Queue[dict[str, Any]]] = set()
        self._sequence = 0
        self._ensured = False
        self._process: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task[None] | None = None
        self._tool_events: dict[str, int] = {}

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._listeners.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._listeners.discard(queue)

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "state": self.state,
            "events": [dict(event) for event in self.events],
        }

    def start(self, prompt: str, *, access: str = "full") -> None:
        prompt = prompt.strip()
        if not prompt:
            raise AgentSessionError("Prompt is empty")
        if len(prompt) > MAX_PROMPT_LENGTH:
            raise AgentSessionError("Prompt is too long")
        if access not in {"read", "full"}:
            raise AgentSessionError("Unknown agent access mode")
        if self._task and not self._task.done():
            raise AgentSessionError("Agent is already working")
        self._task = asyncio.create_task(self._run(prompt, access=access))

    async def cancel(self) -> None:
        if not self._task or self._task.done():
            return
        self._set_state("stopping")
        try:
            await self._control(
                "cancel",
                "-s",
                self.session_name,
                check=False,
                timeout=CANCEL_CONTROL_TIMEOUT_SECONDS,
            )
        except AgentSessionError:
            pass
        try:
            await asyncio.wait_for(
                asyncio.shield(self._task),
                timeout=PROMPT_CANCEL_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            if self._process:
                await _terminate_agent_process(self._process)

    async def reset(self) -> None:
        if self._task and not self._task.done():
            raise AgentSessionError(
                "Stop the current response before starting a new session"
            )
        await self._control("sessions", "new", "--name", self.session_name)
        self._ensured = True
        self.events = []
        self._tool_events = {}
        self._broadcast({"type": "reset"})
        self._set_state("idle")

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
        if self._process:
            await _terminate_agent_process(self._process)

    async def _run(self, prompt: str, *, access: str) -> None:
        self._emit({"kind": "message", "role": "user", "text": prompt})
        self._set_state("starting")
        try:
            if not self._ensured:
                await self._control(
                    "sessions",
                    "ensure",
                    "--name",
                    self.session_name,
                )
                self._ensured = True
            self._set_state("working")
            for attempt in range(2):
                if mode := _agent_mode(self.agent_command, access):
                    await self._control("set-mode", mode, "-s", self.session_name)
                error = await self._prompt_once(prompt, access=access)
                if error is None:
                    break
                if attempt == 0 and _stale_queue_error(error):
                    await self._control("sessions", "new", "--name", self.session_name)
                    self._ensured = True
                    continue
                raise AgentSessionError(error)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._emit({"kind": "error", "text": str(exc)})
            self._set_state("error")
            return
        self._set_state("idle")

    async def _prompt_once(self, prompt: str, *, access: str) -> str | None:
        permission = "--approve-all" if access == "full" else "--approve-reads"
        command = [
            *self._command(),
            permission,
            "--non-interactive-permissions",
            "deny",
            "--format",
            "json",
            "--json-strict",
            "--suppress-reads",
            "prompt",
            "-s",
            self.session_name,
            _terminal_prompt(prompt, access=access),
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=self.cwd,
            env=_agent_environment(self.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=ACP_STREAM_LIMIT,
        )
        self._process = process
        stderr_task: asyncio.Task[bytes] | None = None
        protocol_error = ""
        undecoded_output = ""
        try:
            assert process.stdout is not None
            assert process.stderr is not None
            stderr_task = asyncio.create_task(process.stderr.read())
            while True:
                try:
                    line = await process.stdout.readline()
                except ValueError as exc:
                    raise AgentSessionError(
                        "Agent returned a message too large for the Terminal"
                    ) from exc
                if not line:
                    break
                try:
                    payload = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    text = line.decode("utf-8", "replace").strip()
                    if text:
                        undecoded_output = text
                    continue
                if isinstance(payload.get("error"), dict):
                    protocol_error = _error_text(payload)
                    continue
                self._accept(payload)
            error_output = (await stderr_task).decode("utf-8", "replace").strip()
            return_code = await process.wait()
            if not return_code:
                return None
            return (
                error_output[-2_000:]
                or protocol_error
                or undecoded_output[-2_000:]
                or f"Agent exited with status {return_code}"
            )
        finally:
            await _terminate_agent_process(process)
            if stderr_task is not None:
                if not stderr_task.done():
                    stderr_task.cancel()
                await asyncio.gather(stderr_task, return_exceptions=True)
            if self._process is process:
                self._process = None

    async def _control(
        self,
        *arguments: str,
        check: bool = True,
        timeout: float = CONTROL_TIMEOUT_SECONDS,
    ) -> None:
        process = await asyncio.create_subprocess_exec(
            *self._command(),
            "--format",
            "quiet",
            *arguments,
            cwd=self.cwd,
            env=_agent_environment(self.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except TimeoutError as exc:
                raise AgentSessionError("ACP control request timed out") from exc
            if check and process.returncode:
                message = stderr.decode("utf-8", "replace").strip()
                raise AgentSessionError(message or "ACP session could not start")
        finally:
            await _terminate_agent_process(process)

    def _command(self) -> list[str]:
        return [
            str(self.executable),
            "--agent",
            self.agent_command,
            "--cwd",
            str(self.cwd),
            "--mcp-config",
            str(self.cwd / ACP_CONFIG),
        ]

    def _accept(self, payload: dict[str, Any]) -> None:
        event_type, event = _acp_event(payload)
        if event_type in {
            "agent_message",
            "agent_message_chunk",
            "assistant_message",
            "message",
            "text",
            "text_delta",
        }:
            text = _event_text(event)
            if text:
                self._append_assistant(text)
            return
        if event_type in {"tool_call", "tool_call_update"}:
            self._upsert_tool(event)
            return
        if event_type in {"permission", "permission_request"}:
            self._emit({"kind": "notice", "text": "Permission required"})
            return
        if event_type == "error" or isinstance(payload.get("error"), dict):
            text = _event_text(event) or _error_text(payload)
            self._emit({"kind": "error", "text": text})

    def _upsert_tool(self, payload: dict[str, Any]) -> None:
        title = str(payload.get("title") or payload.get("name") or "Tool")
        status = str(payload.get("status") or "running")
        tool_key = str(
            payload.get("toolCallId") or payload.get("tool_call_id") or title
        )
        event_id = self._tool_events.get(tool_key)
        current = next(
            (event for event in self.events if event.get("id") == event_id), None
        )
        if current is None:
            emitted = self._emit(
                {"kind": "tool", "title": title or "Tool", "status": status}
            )
            self._tool_events[tool_key] = int(emitted["id"])
            return
        current.update(title=title or current.get("title") or "Tool", status=status)
        self._broadcast({"type": "replace", "event": dict(current)})

    def _append_assistant(self, text: str) -> None:
        if (
            self.events
            and self.events[-1].get("kind") == "message"
            and self.events[-1].get("role") == "assistant"
        ):
            self.events[-1]["text"] += text
            self._broadcast(
                {
                    "type": "append",
                    "event_id": self.events[-1]["id"],
                    "text": text,
                }
            )
            return
        self._emit({"kind": "message", "role": "assistant", "text": text})

    def _emit(self, event: dict[str, Any]) -> dict[str, Any]:
        self._sequence += 1
        event = {"id": self._sequence, **event}
        self.events.append(event)
        self.events = self.events[-MAX_EVENTS:]
        self._broadcast({"type": "event", "event": event})
        return event

    def _set_state(self, value: str) -> None:
        self.state = value
        self._broadcast({"type": "state", "state": value})

    def _broadcast(self, message: dict[str, Any]) -> None:
        for queue in tuple(self._listeners):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(self.snapshot())
                continue
            queue.put_nowait(message)


async def _terminate_agent_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()


def _event_text(payload: dict[str, Any]) -> str:
    for key in ("text", "message", "delta"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    return ""


def _acp_event(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if payload.get("method") == "session/update":
        params = payload.get("params")
        if isinstance(params, dict) and isinstance(params.get("update"), dict):
            update = params["update"]
            return str(update.get("sessionUpdate") or "").lower(), update
    return str(payload.get("type") or "").lower(), payload


def _error_text(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return "Agent request failed"


def _stale_queue_error(message: str) -> bool:
    return "queue owner is running but not accepting queue requests" in message.lower()


def _terminal_prompt(prompt: str, *, access: str) -> str:
    if prompt.startswith("/"):
        return prompt
    context = TERMINAL_CONTEXT if access == "full" else READ_TERMINAL_CONTEXT
    return f"{context}\n\n{prompt}"


def _session_name(cwd: Path) -> str:
    config_path = cwd / ACP_CONFIG
    config = config_path.read_bytes() if config_path.is_file() else b""
    skill_path = cwd / ".agents/skills/use-compute-bazaar/SKILL.md"
    skill = skill_path.read_bytes() if skill_path.is_file() else b""
    contract = b"\0".join(
        (
            config,
            skill,
            TERMINAL_CONTEXT.encode(),
            READ_TERMINAL_CONTEXT.encode(),
            AGENT_MODEL.encode(),
            AGENT_REASONING_EFFORT.encode(),
        )
    )
    fingerprint = hashlib.sha256(contract).hexdigest()[:10]
    return f"{SESSION_NAME}-{fingerprint}"


def _agent_environment(cwd: Path | None = None) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COMPUTE_BAZAAR_TERMINAL_")
    }
    executable_dirs = [Path(sys.executable).parent]
    if cwd is not None:
        checkout_bin = cwd / ".venv" / "bin"
        if (checkout_bin / "compute-bazaar").is_file():
            executable_dirs.insert(0, checkout_bin)
            environment["VIRTUAL_ENV"] = str(cwd / ".venv")
    path_entries = [
        *(str(path) for path in executable_dirs),
        *environment.get("PATH", "").split(os.pathsep),
    ]
    environment["PATH"] = os.pathsep.join(dict.fromkeys(filter(None, path_entries)))
    environment["CODEX_CONFIG"] = json.dumps(
        {
            "model": AGENT_MODEL,
            "model_reasoning_effort": AGENT_REASONING_EFFORT,
        },
        separators=(",", ":"),
    )
    environment["INITIAL_AGENT_MODE"] = CODEX_ACCESS_MODES["full"]
    return environment


def _agent_mode(agent_command: str, access: str) -> str | None:
    if "codex-acp" not in agent_command:
        return None
    return CODEX_ACCESS_MODES[access]


def _find_acpx(cwd: Path) -> Path | None:
    configured = os.getenv("COMPUTE_BAZAAR_ACPX")
    candidates = [
        Path(configured).expanduser() if configured else None,
        cwd / "terminal" / "node_modules" / ".bin" / "acpx",
        Path(shutil.which("acpx")) if shutil.which("acpx") else None,
    ]
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if candidate is not None
            and candidate.is_file()
            and os.access(candidate, os.X_OK)
        ),
        None,
    )


def _find_acp_agent(cwd: Path) -> str | None:
    configured = os.getenv("COMPUTE_BAZAAR_ACP_AGENT", "").strip()
    if configured:
        return configured
    adapter = cwd / DEFAULT_ACP_AGENT
    if adapter.is_file() and os.access(adapter, os.X_OK):
        return shlex.join((str(adapter.resolve()),))
    return None
