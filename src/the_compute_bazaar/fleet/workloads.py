"""Durable workload state backed by remote SSH processes."""

from __future__ import annotations

import base64
import os
import secrets
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import FleetMachine
from .registry import FleetRegistry
from .ssh import ssh_command

if TYPE_CHECKING:
    from ..operations import OperationalLedger


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
WorkloadState = Literal[
    "starting", "running", "succeeded", "failed", "stopped", "unknown"
]
FINAL_STATES = {"succeeded", "failed", "stopped"}


class WorkloadError(RuntimeError):
    pass


class WorkloadRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workload_id: str
    host_id: str
    allocation_id: str | None = None
    name: str
    command: tuple[str, ...]
    working_directory: str
    remote_directory: str
    state: WorkloadState
    remote_pid: int | None = Field(default=None, ge=1)
    exit_code: int | None = None
    started_at: datetime
    ended_at: datetime | None = None
    updated_at: datetime
    stdout_ref: str
    stderr_ref: str
    error: str | None = None

    @model_validator(mode="after")
    def validate_run(self) -> WorkloadRun:
        if not self.command:
            raise ValueError("Workload command cannot be empty")
        for value in (self.started_at, self.updated_at, self.ended_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("Workload timestamps must be timezone-aware")
        return self

    def row(self) -> dict[str, object]:
        return {
            "workload_id": self.workload_id,
            "host_id": self.host_id,
            "name": self.name,
            "state": self.state,
            "pid": self.remote_pid,
            "exit_code": self.exit_code,
            "command": shlex.join(self.command),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


class WorkloadService:
    def __init__(
        self,
        *,
        registry: FleetRegistry,
        ledger: OperationalLedger,
        runner: CommandRunner = subprocess.run,
        known_hosts_file: Path | None = None,
    ) -> None:
        self.registry = registry
        self.ledger = ledger
        self.runner = runner
        self.known_hosts_file = known_hosts_file
        self.root = registry.root / "workloads"

    @classmethod
    def local(cls) -> WorkloadService:
        from ..operations import OperationalLedger

        registry = FleetRegistry()
        return cls(registry=registry, ledger=OperationalLedger(registry=registry))

    def start(
        self,
        host_id: str,
        *,
        name: str,
        command: Sequence[str],
        working_directory: str = "/workspace",
    ) -> WorkloadRun:
        if not command:
            raise WorkloadError("Workload command cannot be empty")
        machine = self._running_machine(host_id)
        workload_id = f"workload-{secrets.token_hex(8)}"
        remote_directory = f"/tmp/compute-bazaar/workloads/{workload_id}"
        local_directory = self.root / workload_id
        local_directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        stdout_ref = str(local_directory / "stdout.log")
        stderr_ref = str(local_directory / "stderr.log")
        Path(stdout_ref).touch(mode=0o600)
        Path(stderr_ref).touch(mode=0o600)

        encoded = base64.b64encode(
            _run_script(command, working_directory=working_directory).encode()
        ).decode()
        remote = _launch_script(remote_directory, encoded)
        try:
            result = self._run(machine, remote, timeout=30)
        except Exception:
            shutil.rmtree(local_directory, ignore_errors=True)
            raise
        try:
            remote_pid = int(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError) as exc:
            raise WorkloadError("Remote workload returned no process ID") from exc
        now = datetime.now(UTC)
        workload = WorkloadRun(
            workload_id=workload_id,
            host_id=host_id,
            allocation_id=machine.allocation_id,
            name=name,
            command=tuple(command),
            working_directory=working_directory,
            remote_directory=remote_directory,
            state="running",
            remote_pid=remote_pid,
            started_at=now,
            updated_at=now,
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
        )
        self.ledger.record_workload(workload)
        return workload

    def list(self, host_id: str | None = None) -> list[WorkloadRun]:
        return self.ledger.workloads(host_id)

    def inspect(self, workload_id: str) -> WorkloadRun:
        workload = self.ledger.workload(workload_id)
        if workload.state in FINAL_STATES:
            return workload
        machine = self.registry.get(workload.host_id)
        result = self._run(machine, _status_script(workload), timeout=20)
        status, _, value = result.stdout.strip().partition("\t")
        now = datetime.now(UTC)
        updates: dict[str, Any] = {"updated_at": now, "error": None}
        if status == "running":
            updates["state"] = "running"
        elif status == "exit":
            try:
                exit_code = int(value)
            except ValueError as exc:
                raise WorkloadError("Remote workload returned an invalid exit code") from exc
            updates.update(
                state="succeeded" if exit_code == 0 else "failed",
                exit_code=exit_code,
                ended_at=now,
            )
        else:
            updates.update(state="unknown", error="Remote process state is unavailable")
        refreshed = workload.model_copy(update=updates)
        self.ledger.update_workload(refreshed)
        if refreshed.state in FINAL_STATES:
            try:
                self._sync_logs(machine, refreshed)
            except WorkloadError as exc:
                refreshed = refreshed.model_copy(
                    update={
                        "updated_at": datetime.now(UTC),
                        "error": f"Log sync failed: {exc}",
                    }
                )
                self.ledger.update_workload(refreshed)
        return refreshed

    def logs(self, workload_id: str, *, tail: int = 200) -> dict[str, Any]:
        if not 1 <= tail <= 10_000:
            raise WorkloadError("tail must be between 1 and 10000")
        workload = self.inspect(workload_id)
        if workload.state not in FINAL_STATES:
            self._sync_logs(self.registry.get(workload.host_id), workload)
        stdout = _tail(Path(workload.stdout_ref), tail)
        stderr = _tail(Path(workload.stderr_ref), tail)
        return {
            "contract": "compute-bazaar.fleet-workload-logs.v1",
            "workload": workload.model_dump(mode="json"),
            "stdout": stdout,
            "stderr": stderr,
        }

    def stop(self, workload_id: str, *, confirm: bool) -> WorkloadRun:
        if not confirm:
            raise WorkloadError("Stopping a workload requires --confirm")
        workload = self.ledger.workload(workload_id)
        if workload.state in FINAL_STATES:
            return workload
        if workload.remote_pid is None:
            raise WorkloadError("Workload has no remote process ID")
        machine = self.registry.get(workload.host_id)
        self._run(machine, _stop_script(workload.remote_pid), timeout=25)
        now = datetime.now(UTC)
        stopped = workload.model_copy(
            update={
                "state": "stopped",
                "exit_code": 143,
                "ended_at": now,
                "updated_at": now,
                "error": None,
            }
        )
        self.ledger.update_workload(stopped)
        try:
            self._sync_logs(machine, stopped)
        except WorkloadError as exc:
            stopped = stopped.model_copy(
                update={
                    "updated_at": datetime.now(UTC),
                    "error": f"Log sync failed: {exc}",
                }
            )
            self.ledger.update_workload(stopped)
        return stopped

    def refresh_host(self, host_id: str) -> list[WorkloadRun]:
        refreshed: list[WorkloadRun] = []
        for workload in self.list(host_id):
            if workload.state in FINAL_STATES:
                refreshed.append(workload)
                continue
            try:
                refreshed.append(self.inspect(workload.workload_id))
            except (KeyError, ValueError, WorkloadError):
                refreshed.append(workload)
        return refreshed

    def _running_machine(self, host_id: str) -> FleetMachine:
        machine = self.registry.get(host_id)
        if machine.state != "running":
            raise WorkloadError(f"Fleet host {host_id} is {machine.state}")
        if machine.ssh is None:
            raise WorkloadError(f"Fleet host {host_id} has no SSH endpoint")
        return machine

    def _run(
        self,
        machine: FleetMachine,
        remote_command: str,
        *,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        command = ssh_command(
            machine,
            remote_command=remote_command,
            known_hosts_file=self.known_hosts_file,
        )
        result = self.runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or "SSH workload command failed"
            raise WorkloadError(detail)
        return result

    def _sync_logs(self, machine: FleetMachine, workload: WorkloadRun) -> None:
        result = self._run(machine, _log_script(workload.remote_directory), timeout=20)
        stdout, stderr = _split_logs(result.stdout)
        _atomic_write(Path(workload.stdout_ref), stdout)
        _atomic_write(Path(workload.stderr_ref), stderr)


def _run_script(command: Sequence[str], *, working_directory: str) -> str:
    return "\n".join(
        (
            "#!/bin/sh",
            "status_file=$(dirname \"$0\")/exit_code",
            "finish() { code=$?; printf '%s\\n' \"$code\" > \"$status_file.tmp\"; mv \"$status_file.tmp\" \"$status_file\"; }",
            "trap finish EXIT",
            "trap 'exit 143' HUP INT TERM",
            f"cd {shlex.quote(working_directory)}",
            shlex.join(command),
        )
    )


def _launch_script(remote_directory: str, encoded: str) -> str:
    directory = shlex.quote(remote_directory)
    return "\n".join(
        (
            "umask 077",
            f"mkdir -p {directory}",
            f"printf %s {shlex.quote(encoded)} | base64 -d > {directory}/run.sh",
            f"chmod 700 {directory}/run.sh",
            f"nohup setsid sh {directory}/run.sh > {directory}/stdout.log 2> {directory}/stderr.log < /dev/null &",
            "pid=$!",
            f"printf '%s\\n' \"$pid\" > {directory}/pid",
            "printf '%s\\n' \"$pid\"",
        )
    )


def _status_script(workload: WorkloadRun) -> str:
    directory = shlex.quote(workload.remote_directory)
    pid = int(workload.remote_pid or 0)
    return (
        f"if [ -f {directory}/exit_code ]; then printf 'exit\\t'; cat {directory}/exit_code; "
        f"elif kill -0 {pid} 2>/dev/null; then printf 'running\\t{pid}\\n'; "
        "else printf 'unknown\\t\\n'; fi"
    )


def _stop_script(pid: int) -> str:
    return (
        f"kill -TERM -- -{pid} 2>/dev/null || kill -TERM {pid} 2>/dev/null || true; "
        "i=0; while kill -0 "
        f"{pid} 2>/dev/null && [ $i -lt 20 ]; do sleep 0.25; i=$((i+1)); done; "
        f"kill -KILL -- -{pid} 2>/dev/null || kill -KILL {pid} 2>/dev/null || true"
    )


def _log_script(remote_directory: str) -> str:
    directory = shlex.quote(remote_directory)
    return (
        f"printf 'CBZ_STDOUT_BEGIN\\n'; tail -c 1048576 {directory}/stdout.log 2>/dev/null || true; "
        "printf '\\nCBZ_STDOUT_END\\nCBZ_STDERR_BEGIN\\n'; "
        f"tail -c 1048576 {directory}/stderr.log 2>/dev/null || true; "
        "printf '\\nCBZ_STDERR_END\\n'"
    )


def _split_logs(output: str) -> tuple[str, str]:
    try:
        stdout = output.split("CBZ_STDOUT_BEGIN\n", 1)[1].split(
            "\nCBZ_STDOUT_END", 1
        )[0]
        stderr = output.split("CBZ_STDERR_BEGIN\n", 1)[1].split(
            "\nCBZ_STDERR_END", 1
        )[0]
    except IndexError as exc:
        raise WorkloadError("Remote workload logs were malformed") from exc
    return stdout, stderr


def _tail(path: Path, lines: int) -> str:
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[-lines:])


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
