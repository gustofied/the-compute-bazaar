"""Persistent ACP agent sessions for the native Terminal."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any


MAX_EVENTS = 400
MAX_PROMPT_LENGTH = 20_000
AGENT_MODEL = "gpt-5.6-terra"
AGENT_REASONING_EFFORT = "medium"
SESSION_NAME = "compute-bazaar-terminal-terra-medium"
ACP_CONFIG = Path("terminal/acp.json")
DEFAULT_ACP_AGENT = Path("terminal/node_modules/.bin/codex-acp")
TERMINAL_CONTEXT = """<compute-bazaar-terminal>
ACP is the only Terminal integration. Work in the Bazaar checkout using normal
repo tools and `compute-bazaar` directly.
- Inspect data with `compute-bazaar tables`, `compute-bazaar describe TABLE`, and
  `compute-bazaar sql \"SQL\"`.
- Open a result in Data with `compute-bazaar query QUERY_ID --terminal` or
  `compute-bazaar sql \"SQL\" --terminal`.
Use `compute-bazaar COMMAND --help` when needed. Do not use MCP or GUI automation
to operate the Terminal.
</compute-bazaar-terminal>"""
READ_TERMINAL_CONTEXT = """<compute-bazaar-terminal>
ACP is the only Terminal integration. This turn has Read access: inspect and
reason about the Bazaar checkout, but do not run shell commands. If the request
requires `compute-bazaar` or another command, ask the user to switch the Agent
to Full access. Do not use MCP or GUI automation to operate the Terminal.
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

    def start(self, prompt: str, *, access: str = "read") -> None:
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
        await self._control("cancel", "-s", SESSION_NAME, check=False)
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=5)
        except TimeoutError:
            if self._process and self._process.returncode is None:
                self._process.terminate()

    def clear(self) -> None:
        self.events = []
        self._tool_events = {}
        self._broadcast({"type": "reset"})

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2)
            except TimeoutError:
                self._process.kill()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self, prompt: str, *, access: str) -> None:
        self._emit({"kind": "message", "role": "user", "text": prompt})
        self._set_state("starting")
        try:
            if not self._ensured:
                await self._control(
                    "sessions",
                    "ensure",
                    "--name",
                    SESSION_NAME,
                )
                self._ensured = True
            self._set_state("working")
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
                SESSION_NAME,
                _terminal_prompt(prompt, access=access),
            ]
            self._process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self.cwd,
                env=_agent_environment(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert self._process.stdout is not None
            assert self._process.stderr is not None
            stderr_task = asyncio.create_task(self._process.stderr.read())
            async for line in self._process.stdout:
                try:
                    payload = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                self._accept(payload)
            error_output = (await stderr_task).decode("utf-8", "replace").strip()
            return_code = await self._process.wait()
            if return_code and error_output:
                raise AgentSessionError(error_output[-2_000:])
            if return_code:
                raise AgentSessionError(f"Agent exited with status {return_code}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._emit({"kind": "error", "text": str(exc)})
            self._set_state("error")
            return
        finally:
            self._process = None
        self._set_state("idle")

    async def _control(self, *arguments: str, check: bool = True) -> None:
        process = await asyncio.create_subprocess_exec(
            *self._command(),
            "--format",
            "quiet",
            *arguments,
            cwd=self.cwd,
            env=_agent_environment(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if check and process.returncode:
            message = stderr.decode("utf-8", "replace").strip()
            raise AgentSessionError(message or "ACP session could not start")

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
        tool_key = str(payload.get("toolCallId") or payload.get("tool_call_id") or title)
        event_id = self._tool_events.get(tool_key)
        current = next(
            (event for event in self.events if event.get("id") == event_id), None
        )
        if current is None:
            emitted = self._emit(
                {"kind": "tool", "title": title, "status": status}
            )
            self._tool_events[tool_key] = int(emitted["id"])
            return
        current.update(title=title, status=status)
        self._broadcast({"type": "replace", "event": dict(current)})

    def _append_assistant(self, text: str) -> None:
        if self.events and self.events[-1].get("kind") == "message" and self.events[
            -1
        ].get("role") == "assistant":
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


def _terminal_prompt(prompt: str, *, access: str) -> str:
    if prompt.startswith("/"):
        return prompt
    context = TERMINAL_CONTEXT if access == "full" else READ_TERMINAL_CONTEXT
    return f"{context}\n\n{prompt}"


def _agent_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in (
        "COMPUTE_BAZAAR_TERMINAL_NATIVE_TOKEN",
        "COMPUTE_BAZAAR_TERMINAL_CONTROL_TOKEN",
    ):
        environment.pop(key, None)
    executable_dir = str(Path(sys.executable).parent)
    environment["PATH"] = os.pathsep.join(
        (executable_dir, environment.get("PATH", ""))
    )
    environment["CODEX_CONFIG"] = json.dumps(
        {
            "model": AGENT_MODEL,
            "model_reasoning_effort": AGENT_REASONING_EFFORT,
        },
        separators=(",", ":"),
    )
    return environment


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
            if candidate is not None and candidate.is_file() and os.access(candidate, os.X_OK)
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
