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
            "contract": "compute-bazaar.launch-receipt",
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


class ReconciliationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: str
    request_id: str
    state: str
    observed_at: datetime
    matched_resources: int
    provider_resource_id: str | None = None
    machine: FleetMachine | None = None
    note: str
    warnings: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        return {
            "contract": "compute-bazaar.launch-reconciliation",
            "observed_at": self.observed_at,
            "rows": [self.machine.row()] if self.machine else [],
            "reconciliation": self.model_dump(mode="json"),
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
                    state=("failed" if _create_was_rejected(payload) else "uncertain"),
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

        allocation, machine = self._allocation_and_machine(
            request,
            attempt_id=attempt.attempt_id,
            provider_resource_id=pod_id,
            provider_payload=payload,
        )
        self.ledger.complete_allocation(attempt.attempt_id, allocation)
        self.registry.put(machine)
        receipt = LaunchReceipt(
            machine=machine,
            plan_id=plan.plan_id,
            request_id=request.request_id,
            attempt_id=attempt.attempt_id,
            allocation_id=allocation.allocation_id,
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

    def reconcile(
        self,
        attempt_id: str,
        *,
        confirm_absent: bool = False,
    ) -> ReconciliationReceipt:
        if not self.api_key:
            raise LaunchExecutionError("RUNPOD_API_KEY is not configured")
        if self.ledger is None:
            raise LaunchExecutionError(
                "Reconciliation requires the private operational ledger"
            )
        row = self.ledger.provisioning_attempt(attempt_id)
        allocation = self.ledger.allocation_for_request(row["request_id"])
        recover_succeeded = row["attempt_state"] == "succeeded" and allocation is None
        if row["attempt_state"] != "uncertain" and not recover_succeeded:
            raise LaunchExecutionError(
                f"Provisioning attempt {attempt_id} is already {row['attempt_state']}"
            )
        if row["acquisition_connector"] != "runpod":
            raise LaunchExecutionError(
                f"Reconciliation is not implemented for {row['acquisition_connector']}"
            )
        request = _request_from_row(row)
        name = str(request.provider_request.get("name") or "")
        if not name:
            raise LaunchExecutionError("Provisioning request has no provider name")
        started_at = _parse_time(row["started_at"])
        if recover_succeeded and row["provider_resource_id"]:
            payload = self._run_payload(
                [self.binary, "pod", "get", str(row["provider_resource_id"])],
                timeout=30,
            )
            candidates = _pod_rows(payload)
        else:
            payload = self._run_payload(
                [
                    self.binary,
                    "pod",
                    "list",
                    "--all",
                    "--name",
                    name,
                    "--created-after",
                    started_at.date().isoformat(),
                ],
                timeout=30,
            )
            candidates = [
                pod
                for pod in _pod_rows(payload)
                if _pod_matches(pod, name=name, started_at=started_at)
            ]
        observed_at = datetime.now(UTC)
        if not candidates:
            if confirm_absent:
                note = "No matching RunPod Pod exists; operator confirmed absence"
                self.ledger.reconcile_attempt(
                    attempt_id,
                    state="failed",
                    note=note,
                )
                return ReconciliationReceipt(
                    attempt_id=attempt_id,
                    request_id=request.request_id,
                    state="failed",
                    observed_at=observed_at,
                    matched_resources=0,
                    note=note,
                )
            return ReconciliationReceipt(
                attempt_id=attempt_id,
                request_id=request.request_id,
                state="uncertain",
                observed_at=observed_at,
                matched_resources=0,
                note="No exact provider match; use --confirm-absent only after checking RunPod",
            )
        if len(candidates) != 1:
            return ReconciliationReceipt(
                attempt_id=attempt_id,
                request_id=request.request_id,
                state="uncertain",
                observed_at=observed_at,
                matched_resources=len(candidates),
                note="Multiple exact provider matches; reconcile in RunPod before continuing",
            )

        provider_payload = candidates[0]
        pod_id = _find_text(provider_payload, "id", "podId", "pod_id")
        if not pod_id:
            raise LaunchExecutionError("Matching RunPod Pod returned no ID")
        allocation, machine = self._allocation_and_machine(
            request,
            attempt_id=attempt_id,
            provider_resource_id=pod_id,
            provider_payload=provider_payload,
        )
        self.ledger.complete_allocation(
            attempt_id,
            allocation,
            recover=True,
            note="Recovered from RunPod provider state",
        )
        self.registry.put(machine)
        warnings: list[str] = []
        try:
            machine = self.resolve_ssh(machine)
        except (KeyError, TypeError, ValueError, LaunchExecutionError) as exc:
            warnings.append(f"Pod recovered; SSH endpoint is not ready: {exc}")
        return ReconciliationReceipt(
            attempt_id=attempt_id,
            request_id=request.request_id,
            state="succeeded",
            observed_at=observed_at,
            matched_resources=1,
            provider_resource_id=pod_id,
            machine=machine,
            note="Recovered one exact RunPod Pod",
            warnings=tuple(warnings),
        )

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
        connector = str(allocation["source"])
        if connector != "runpod":
            raise LaunchExecutionError(
                f"SSH resolution is not implemented for {connector}"
            )
        provider_resource_id = str(allocation["source_resource_id"])
        payload = self._run_json([self.binary, "ssh", "info", provider_resource_id])
        resolved = machine.model_copy(
            update={
                "state": "running",
                "ssh": SshEndpoint(
                    target=(
                        f"{_ssh_user(str(payload.get('ssh_command') or ''))}"
                        f"@{payload['ip']}"
                    ),
                    port=int(payload["port"]),
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
        connector = str(allocation["source"])
        if connector != "runpod":
            raise LaunchExecutionError(
                f"Fleet termination is not implemented for {connector}"
            )
        self._run_json(
            [self.binary, "pod", "delete", str(allocation["source_resource_id"])]
        )
        terminated_at = datetime.now(UTC)
        terminated = machine.model_copy(update={"state": "terminated", "ssh": None})
        self.registry.put(terminated)
        self.ledger.record_machine_state(terminated, occurred_at=terminated_at)
        self.ledger.stop_host_workloads(
            machine.host_id,
            reason="Fleet host terminated",
            ended_at=terminated_at,
        )
        return terminated

    def _allocation_and_machine(
        self,
        request: ProvisioningRequest,
        *,
        attempt_id: str,
        provider_resource_id: str,
        provider_payload: Mapping[str, Any],
    ) -> tuple[Allocation, FleetMachine]:
        if self.ledger is None:
            raise LaunchExecutionError("Fleet operation requires the private ledger")
        allocation_id = (
            "allocation-"
            + hashlib.sha256(
                f"{request.request_id}\x1f{provider_resource_id}".encode()
            ).hexdigest()[:16]
        )
        state = _machine_state(
            _find_text(
                provider_payload,
                "runtimeStatus",
                "desiredStatus",
                "status",
            )
        )
        allocation = Allocation(
            allocation_id=allocation_id,
            request_id=request.request_id,
            successful_attempt_id=attempt_id,
            candidate_observation_id=request.candidate_observation_id,
            preflight_observation_id=request.preflight_observation_id,
            source=request.acquisition_connector,
            intermediary=request.acquisition_connector,
            operator=request.capacity_provider,
            offer_id=request.source_offer_id,
            source_resource_id=provider_resource_id,
            state=state,
            price_usd_gpu_hr=request.selected_price_usd_gpu_hr,
            price_usd_instance_hr=request.selected_price_usd_instance_hr,
            created_at=request.created_at,
            terminate_at=request.created_at
            + timedelta(minutes=request.runtime_minutes),
            updated_at=datetime.now(UTC),
        )
        machine = FleetMachine(
            host_id=f"runpod:{provider_resource_id}",
            allocation_id=allocation_id,
            name=str(request.provider_request["name"]),
            state=state,
            expected_gpu_model=request.gpu_model,
            expected_gpu_count=request.gpu_count,
            created_at=request.created_at,
        )
        return allocation, machine

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
        payload = self._run_payload(command)
        if not isinstance(payload, dict):
            raise LaunchExecutionError("runpodctl returned a non-object response")
        if payload.get("error"):
            raise RunpodctlError(str(payload["error"]), payload=payload)
        return payload

    def _run_payload(
        self,
        command: Sequence[str],
        *,
        timeout: int | None = None,
    ) -> Any:
        environment = dict(os.environ)
        environment["RUNPOD_API_KEY"] = str(self.api_key)
        try:
            result = self.runner(
                list(command),
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise LaunchExecutionError("runpodctl timed out") from exc
        if result.returncode != 0:
            error_payload = _json_object(result.stderr) or _json_object(result.stdout)
            raise RunpodctlError(
                _command_error(result.stderr or result.stdout),
                payload=error_payload,
            )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise LaunchExecutionError("runpodctl returned invalid JSON") from exc


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


def _create_was_rejected(payload: Mapping[str, Any]) -> bool:
    message = str(payload.get("error", "")).lower()
    return payload.get("code") == "graphql_error" and (
        "no longer any instances available" in message
        or "no instances available" in message
    )


def _request_from_row(row: Mapping[str, Any]) -> ProvisioningRequest:
    return ProvisioningRequest.model_validate(
        {
            key: row[key]
            for key in ProvisioningRequest.model_fields
            if key not in {"provider_request", "state"}
        }
        | {
            "provider_request": json.loads(str(row["provider_request_json"])),
            "state": row["state"],
        }
    )


def _pod_rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("pods", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
        if isinstance(value, Mapping):
            nested = _pod_rows(value)
            if nested:
                return nested
    return [payload] if _find_text(payload, "id", "podId", "pod_id") else []


def _pod_matches(
    payload: Mapping[str, Any],
    *,
    name: str,
    started_at: datetime,
) -> bool:
    if _find_text(payload, "name") != name:
        return False
    created = _find_text(payload, "createdAt", "created_at", "created")
    if not created:
        return True
    try:
        return _parse_time(created) >= started_at - timedelta(minutes=5)
    except (TypeError, ValueError):
        return False


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
    for line in reversed(output.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return dict(payload)
    return None
