"""Guarded provider execution for revalidated launch plans."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..fleet import FleetMachine, FleetRegistry, SshEndpoint
from .launch import LaunchPlan


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class LaunchExecutionError(RuntimeError):
    pass


class RunpodctlError(LaunchExecutionError):
    def __init__(
        self, message: str, *, payload: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.payload = dict(payload or {})


class LaunchReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    machine: FleetMachine
    plan_id: str
    launched_at: datetime
    terminate_at: datetime
    max_hourly_usd: float = Field(gt=0)
    expected_max_cost_usd: float = Field(gt=0)
    command: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        return {
            "contract": "compute-bazaar.launch-receipt.v1",
            "observed_at": self.launched_at,
            "rows": [
                {
                    **self.machine.row(),
                    "expected_max_cost_usd": self.expected_max_cost_usd,
                    "plan_id": self.plan_id,
                }
            ],
            "receipt": self.model_dump(mode="json"),
        }


class RunpodExecutor:
    def __init__(
        self,
        *,
        api_key: str | None,
        registry: FleetRegistry | None = None,
        runner: CommandRunner = subprocess.run,
        binary: str | None = None,
        identity_file: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.registry = registry or FleetRegistry()
        self.runner = runner
        self.binary = binary or shutil.which("runpodctl") or "runpodctl"
        self.identity_file = str(
            Path(
                identity_file
                or os.getenv(
                    "COMPUTE_BAZAAR_RUNPOD_SSH_KEY",
                    "~/.ssh/compute_bazaar_runpod_ed25519",
                )
            ).expanduser()
        )

    def execute(
        self,
        plan: LaunchPlan,
        *,
        runtime_minutes: int,
        max_hourly_usd: float,
        confirm_spend: bool,
        wait_timeout: str = "10m",
    ) -> LaunchReceipt:
        _validate_execution(
            plan,
            runtime_minutes=runtime_minutes,
            max_hourly_usd=max_hourly_usd,
            confirm_spend=confirm_spend,
        )
        if not self.api_key:
            raise LaunchExecutionError("RUNPOD_API_KEY is not configured")
        if not Path(self.identity_file).is_file():
            raise LaunchExecutionError(
                f"RunPod SSH key not found: {self.identity_file}"
            )

        launched_at = datetime.now(UTC)
        terminate_at = launched_at + timedelta(minutes=runtime_minutes)
        command = self._create_command(
            plan,
            terminate_at=terminate_at,
            wait_timeout=wait_timeout,
        )
        warnings: list[str] = []
        try:
            payload = self._run_json(command)
        except RunpodctlError as exc:
            payload = exc.payload
            if not _find_text(payload, "id", "podId", "pod_id"):
                raise
            warnings.append(f"Pod created but the readiness wait ended: {exc}")
        pod_id = _find_text(payload, "id", "podId", "pod_id")
        if not pod_id:
            raise LaunchExecutionError("RunPod created a Pod but returned no Pod ID")

        name = str(plan.request["name"])
        machine = FleetMachine(
            host_id=f"runpod:{pod_id}",
            provider="runpod",
            provider_resource_id=pod_id,
            name=name,
            state=_machine_state(_find_text(payload, "desiredStatus", "status")),
            gpu_model=plan.gpu_model,
            gpu_count=plan.gpu_count,
            price_usd_gpu_hr=plan.price_usd_gpu_hr,
            price_usd_instance_hr=plan.price_usd_instance_hr,
            created_at=launched_at,
            terminate_at=terminate_at,
        )
        self.registry.put(machine)

        try:
            machine = self.resolve_ssh(machine)
        except (KeyError, TypeError, ValueError, LaunchExecutionError) as exc:
            warnings.append(f"Pod created; SSH endpoint is not ready: {exc}")

        return LaunchReceipt(
            machine=machine,
            plan_id=plan.plan_id,
            launched_at=launched_at,
            terminate_at=terminate_at,
            max_hourly_usd=max_hourly_usd,
            expected_max_cost_usd=round(
                plan.price_usd_instance_hr * runtime_minutes / 60,
                4,
            ),
            command=tuple(command),
            warnings=tuple(warnings),
        )

    def resolve_ssh(self, machine: FleetMachine) -> FleetMachine:
        if machine.provider != "runpod":
            raise LaunchExecutionError(
                f"SSH resolution is not implemented for {machine.provider}"
            )
        payload = self._run_json(
            [self.binary, "ssh", "info", machine.provider_resource_id]
        )
        resolved = machine.model_copy(
            update={
                "state": "running",
                "ssh": SshEndpoint(
                    host=str(payload["ip"]),
                    port=int(payload["port"]),
                    user=_ssh_user(str(payload.get("ssh_command") or "")),
                    identity_file=self.identity_file,
                ),
            }
        )
        self.registry.put(resolved)
        return resolved

    def terminate(self, machine: FleetMachine, *, confirm: bool) -> FleetMachine:
        if not confirm:
            raise LaunchExecutionError("Termination requires --confirm")
        if machine.provider != "runpod":
            raise LaunchExecutionError(
                f"Fleet termination is not implemented for {machine.provider}"
            )
        self._run_json([self.binary, "pod", "delete", machine.provider_resource_id])
        terminated = machine.model_copy(update={"state": "terminated", "ssh": None})
        self.registry.put(terminated)
        return terminated

    def _create_command(
        self,
        plan: LaunchPlan,
        *,
        terminate_at: datetime,
        wait_timeout: str,
    ) -> list[str]:
        request = plan.request
        gpu_ids = request.get("gpuTypeIds") or []
        data_centers = request.get("dataCenterIds") or []
        if len(gpu_ids) != 1:
            raise LaunchExecutionError("RunPod launch requires one exact GPU type")
        command = [
            self.binary,
            "pod",
            "create",
            "--name",
            str(request["name"]),
            "--image",
            str(request["imageName"]),
            "--gpu-id",
            str(gpu_ids[0]),
            "--gpu-count",
            str(request["gpuCount"]),
            "--cloud-type",
            str(request["cloudType"]),
            "--container-disk-in-gb",
            str(request["containerDiskInGb"]),
            "--volume-in-gb",
            str(request["volumeInGb"]),
            "--volume-mount-path",
            str(request["volumeMountPath"]),
            "--ports",
            "22/tcp",
            "--ssh",
            "--terminate-after",
            terminate_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        ]
        if data_centers:
            command.extend(["--data-center-ids", ",".join(map(str, data_centers))])
        if str(request["cloudType"]).upper() == "COMMUNITY":
            command.append("--public-ip")
        command.extend(["--wait", "--wait-timeout", wait_timeout])
        return command

    def _run_json(
        self,
        command: Sequence[str],
    ) -> dict[str, Any]:
        environment = dict(os.environ)
        environment["RUNPOD_API_KEY"] = str(self.api_key)
        result = self.runner(
            list(command),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            error_payload = _json_object(result.stderr) or _json_object(result.stdout)
            raise RunpodctlError(
                _command_error(result.stderr or result.stdout),
                payload=error_payload,
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise LaunchExecutionError("runpodctl returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise LaunchExecutionError("runpodctl returned a non-object response")
        if payload.get("error"):
            raise RunpodctlError(str(payload["error"]), payload=payload)
        return payload


def _validate_execution(
    plan: LaunchPlan,
    *,
    runtime_minutes: int,
    max_hourly_usd: float,
    confirm_spend: bool,
) -> None:
    if plan.provider != "runpod":
        raise LaunchExecutionError("Only RunPod execution is implemented")
    if plan.status != "ready_for_confirmation":
        missing = ", ".join(plan.required_inputs)
        raise LaunchExecutionError(f"Launch plan is incomplete: {missing}")
    if not confirm_spend:
        raise LaunchExecutionError("Paid launch requires --confirm-spend")
    if not 5 <= runtime_minutes <= 120:
        raise LaunchExecutionError("runtime_minutes must be between 5 and 120")
    if max_hourly_usd <= 0:
        raise LaunchExecutionError("max_hourly_usd must be greater than zero")
    if plan.price_usd_instance_hr > max_hourly_usd:
        raise LaunchExecutionError(
            f"Current instance price ${plan.price_usd_instance_hr:g}/hr exceeds "
            f"the ${max_hourly_usd:g}/hr ceiling"
        )


def _find_text(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value)
    for value in payload.values():
        if isinstance(value, Mapping):
            found = _find_text(value, *keys)
            if found:
                return found
    return None


def _machine_state(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"running", "ready"}:
        return "running"
    if normalized in {"created", "starting", "provisioning"}:
        return "provisioning"
    if normalized in {"stopped", "exited"}:
        return "stopped"
    if normalized in {"terminated", "deleted"}:
        return "terminated"
    return "unknown"


def _ssh_user(command: str) -> str:
    for token in command.split():
        if "@" in token and not token.startswith("-"):
            return token.rsplit("@", 1)[0]
    return "root"


def _command_error(output: str) -> str:
    text = output.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text or "runpodctl failed"
    if isinstance(payload, dict) and payload.get("error"):
        return str(payload["error"])
    return text or "runpodctl failed"


def _json_object(output: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(output.strip())
    except json.JSONDecodeError:
        return None
    return dict(payload) if isinstance(payload, dict) else None
