"""Guarded provider execution for revalidated launch plans."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from .fleet import FleetMachine, FleetRegistry, SshEndpoint
from .provisioning import Allocation, LaunchPlan, ProvisioningRequest

if TYPE_CHECKING:
    from .operations import OperationalLedger


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
    request_id: str
    attempt_id: str
    allocation_id: str
    launched_at: datetime
    terminate_at: datetime
    max_hourly_usd: float = Field(gt=0)
    expected_max_cost_usd: float = Field(gt=0)
    command: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        return {
            "contract": "compute-bazaar.launch-receipt.v2",
            "observed_at": self.launched_at,
            "rows": [
                {
                    **self.machine.row(),
                    "expected_max_cost_usd": self.expected_max_cost_usd,
                    "plan_id": self.plan_id,
                    "request_id": self.request_id,
                    "attempt_id": self.attempt_id,
                    "allocation_id": self.allocation_id,
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
        ledger: OperationalLedger | None = None,
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
        self.ledger = ledger

    def execute(
        self,
        plan: LaunchPlan,
        *,
        runtime_minutes: int,
        max_hourly_usd: float,
        confirm_spend: bool,
        wait_timeout: str = "10m",
        preflight_max_age_seconds: int = 60,
    ) -> LaunchReceipt:
        _validate_execution(
            plan,
            runtime_minutes=runtime_minutes,
            max_hourly_usd=max_hourly_usd,
            confirm_spend=confirm_spend,
            preflight_max_age_seconds=preflight_max_age_seconds,
        )
        if not self.api_key:
            raise LaunchExecutionError("RUNPOD_API_KEY is not configured")
        if not Path(self.identity_file).is_file():
            raise LaunchExecutionError(
                f"RunPod SSH key not found: {self.identity_file}"
            )
        if self.ledger is None:
            raise LaunchExecutionError(
                "Paid launch requires the private operational ledger"
            )

        launched_at = datetime.now(UTC)
        terminate_at = launched_at + timedelta(minutes=runtime_minutes)
        command = self._create_command(
            plan,
            terminate_at=terminate_at,
            wait_timeout=wait_timeout,
        )
        request = ProvisioningRequest.from_plan(
            plan,
            runtime_minutes=runtime_minutes,
            max_hourly_usd=max_hourly_usd,
            created_at=launched_at,
        )
        try:
            attempt = self.ledger.begin_provisioning(request)
        except RuntimeError as exc:
            raise LaunchExecutionError(str(exc)) from exc
        warnings: list[str] = []
        try:
            payload = self._run_json(command)
        except RunpodctlError as exc:
            payload = exc.payload
            pod_id = _find_text(payload, "id", "podId", "pod_id")
            if not pod_id:
                self.ledger.complete_provisioning_attempt(
                    attempt.attempt_id,
                    state="uncertain",
                    error=str(exc),
                )
                raise
            warnings.append(f"Pod created but the readiness wait ended: {exc}")
        except (LaunchExecutionError, OSError) as exc:
            self.ledger.complete_provisioning_attempt(
                attempt.attempt_id,
                state="uncertain",
                error=str(exc),
            )
            raise LaunchExecutionError(str(exc)) from exc
        pod_id = _find_text(payload, "id", "podId", "pod_id")
        if not pod_id:
            message = "RunPod returned no Pod ID; creation state is uncertain"
            self.ledger.complete_provisioning_attempt(
                attempt.attempt_id,
                state="uncertain",
                error=message,
            )
            raise LaunchExecutionError(message)

        self.ledger.complete_provisioning_attempt(
            attempt.attempt_id,
            state="succeeded",
            provider_resource_id=pod_id,
        )
        allocation_id = "allocation-" + hashlib.sha256(
            f"{request.request_id}\x1f{pod_id}".encode()
        ).hexdigest()[:16]
        allocation = Allocation(
            allocation_id=allocation_id,
            request_id=request.request_id,
            successful_attempt_id=attempt.attempt_id,
            acquisition_connector=plan.source_connector,
            capacity_provider=plan.capacity_provider,
            provider_resource_id=pod_id,
            state=_machine_state(_find_text(payload, "desiredStatus", "status")),
            created_at=launched_at,
            terminate_at=terminate_at,
            updated_at=launched_at,
        )
        self.ledger.record_allocation(allocation)

        name = str(plan.request["name"])
        machine = FleetMachine(
            host_id=f"runpod:{pod_id}",
            allocation_id=allocation_id,
            name=name,
            state=allocation.state,
            gpu_model=plan.gpu_model,
            gpu_count=plan.gpu_count,
            created_at=launched_at,
        )
        self.registry.put(machine)
        receipt = LaunchReceipt(
            machine=machine,
            plan_id=plan.plan_id,
            request_id=request.request_id,
            attempt_id=attempt.attempt_id,
            allocation_id=allocation_id,
            launched_at=launched_at,
            terminate_at=terminate_at,
            max_hourly_usd=max_hourly_usd,
            expected_max_cost_usd=round(
                plan.price_usd_instance_hr * runtime_minutes / 60,
                4,
            ),
            command=tuple(command),
        )
        try:
            machine = self.resolve_ssh(machine)
        except (KeyError, TypeError, ValueError, LaunchExecutionError) as exc:
            warnings.append(f"Pod created; SSH endpoint is not ready: {exc}")

        receipt = receipt.model_copy(
            update={"machine": machine, "warnings": tuple(warnings)}
        )
        return receipt

    def resolve_ssh(
        self,
        machine: FleetMachine,
        *,
        record: bool = True,
    ) -> FleetMachine:
        if self.ledger is None:
            raise LaunchExecutionError("Fleet operation requires the private ledger")
        try:
            allocation = self.ledger.allocation_for_machine(machine)
        except KeyError as exc:
            raise LaunchExecutionError(str(exc)) from exc
        connector = str(allocation["acquisition_connector"])
        if connector != "runpod":
            raise LaunchExecutionError(
                f"SSH resolution is not implemented for {connector}"
            )
        provider_resource_id = str(allocation["provider_resource_id"])
        payload = self._run_json(
            [self.binary, "ssh", "info", provider_resource_id]
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
        if record:
            self.ledger.record_machine_state(resolved)
        return resolved

    def terminate(self, machine: FleetMachine, *, confirm: bool) -> FleetMachine:
        if not confirm:
            raise LaunchExecutionError("Termination requires --confirm")
        if self.ledger is None:
            raise LaunchExecutionError("Fleet operation requires the private ledger")
        try:
            allocation = self.ledger.allocation_for_machine(machine)
        except KeyError as exc:
            raise LaunchExecutionError(str(exc)) from exc
        connector = str(allocation["acquisition_connector"])
        if connector != "runpod":
            raise LaunchExecutionError(
                f"Fleet termination is not implemented for {connector}"
            )
        self._run_json(
            [self.binary, "pod", "delete", str(allocation["provider_resource_id"])]
        )
        terminated = machine.model_copy(update={"state": "terminated", "ssh": None})
        self.registry.put(terminated)
        self.ledger.record_machine_state(terminated)
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
    preflight_max_age_seconds: int = 60,
) -> None:
    if plan.source_connector != "runpod":
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
    age = datetime.now(UTC) - plan.observed_at.astimezone(UTC)
    if age > timedelta(seconds=preflight_max_age_seconds):
        raise LaunchExecutionError(
            f"Preflight is {int(age.total_seconds())} seconds old; plan it again"
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
