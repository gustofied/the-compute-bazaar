"""Local Fleet inventory, inspection, and live telemetry workspace."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from ..fleet import (
    FleetMachine,
    FleetMonitor,
    FleetService,
    WorkloadService,
)


class FleetWorkspace:
    def __init__(
        self,
        *,
        asset_root: Path,
        service: FleetService | None = None,
        monitor: FleetMonitor | None = None,
        workloads: WorkloadService | None = None,
    ) -> None:
        self.asset_root = asset_root
        self.service = service or FleetService.local()
        if workloads is not None:
            self.workloads = workloads
        elif self.service.ledger is not None:
            self.workloads = WorkloadService(
                registry=self.service.registry,
                ledger=self.service.ledger,
            )
        else:
            from ..operations import OperationalLedger

            ledger = OperationalLedger(
                self.service.registry.root / "operations.sqlite3",
                registry=self.service.registry,
            )
            self.workloads = WorkloadService(
                registry=self.service.registry,
                ledger=ledger,
            )
        interval = _monitor_interval()
        self.monitor = monitor or FleetMonitor(
            self.service,
            interval_seconds=interval,
        )

    def start(self) -> None:
        self.monitor.start()

    def stop(self) -> None:
        self.monitor.stop()

    def destination(self) -> dict[str, Any]:
        return {"available": True, "href": "/fleet"}

    def register(self, app: FastAPI) -> None:
        @app.get("/fleet", include_in_schema=False)
        def fleet() -> FileResponse:
            return FileResponse(self.asset_root / "fleet.html")

        @app.get("/api/fleet/session")
        def session() -> dict[str, Any]:
            return {
                "contract": "compute-bazaar.fleet-session.v1",
                "refresh_seconds": self.monitor.interval_seconds,
                "hosts": [
                    _machine_payload(
                        machine,
                        monitor_state=self.monitor.state(machine.host_id),
                        allocation=_allocation(self.service, machine),
                    )
                    for machine in self.service.hosts()
                ],
            }

        @app.get("/api/fleet/hosts/{host_id}")
        def host(host_id: str) -> dict[str, Any]:
            state = self.monitor.state(host_id)
            if state is None:
                try:
                    self.service.registry.get(host_id)
                except KeyError as exc:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
                raise HTTPException(status_code=503, detail="Waiting for Fleet sample")
            if state.inspection is None or state.health is None:
                raise HTTPException(
                    status_code=503,
                    detail=state.error or "Waiting for Fleet sample",
                )
            inspection = state.inspection
            health = state.health
            allocation = _allocation(self.service, inspection.machine)
            verification = _verification(self.service, inspection.machine.host_id)
            workloads = self.workloads.refresh_host(host_id)
            return {
                "contract": "compute-bazaar.fleet-host.v1",
                "machine": _machine_payload(
                    inspection.machine,
                    monitor_state=state,
                    allocation=allocation,
                ),
                "observed_at": inspection.observed_at,
                "monitor": {
                    "status": state.status,
                    "polled_at": state.polled_at,
                    "error": state.error,
                    "consecutive_failures": state.consecutive_failures,
                },
                "system": {
                    "os_name": inspection.os_name,
                    "kernel": inspection.kernel,
                    "cpu_model": inspection.cpu_model,
                    "cpu_count": inspection.cpu_count,
                    "cpu_utilization_pct": inspection.cpu_utilization_pct,
                    "memory_mb": inspection.memory_mb,
                    "memory_used_mb": inspection.memory_used_mb,
                    "disk_total_gb": inspection.disk_total_gb,
                    "disk_used_gb": inspection.disk_used_gb,
                    "disk_free_gb": inspection.disk_free_gb,
                    "driver_cuda_version": inspection.driver_cuda_version,
                    "cuda_toolkit_version": inspection.cuda_toolkit_version,
                    "docker_version": inspection.docker_version,
                    "gpu_execution_status": inspection.gpu_execution_status,
                    "gpu_execution_detail": inspection.gpu_execution_detail,
                },
                "gpus": [gpu.model_dump(mode="json") for gpu in inspection.gpus],
                "gpu_processes": [
                    process.model_dump(mode="json")
                    for process in inspection.gpu_processes
                ],
                "workloads": [
                    workload.model_dump(mode="json") for workload in workloads
                ],
                "health": health.health,
                "health_checks": [
                    check.model_dump(mode="json") for check in health.checks
                ],
                "readiness": (
                    verification["readiness"] if verification else "not_verified"
                ),
                "checks": _verification_checks(verification),
            }


def _machine_payload(
    machine: FleetMachine,
    *,
    monitor_state: Any | None = None,
    allocation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "host_id": machine.host_id,
        "allocation_id": machine.allocation_id,
        "provider": allocation.get("capacity_provider") if allocation else None,
        "name": machine.name,
        "state": machine.state,
        "gpu_model": machine.gpu_model,
        "gpu_count": machine.gpu_count,
        "price_usd_gpu_hr": (
            allocation.get("selected_price_usd_gpu_hr") if allocation else None
        ),
        "price_usd_instance_hr": (
            allocation.get("selected_price_usd_instance_hr") if allocation else None
        ),
        "created_at": machine.created_at,
        "terminate_at": allocation.get("terminate_at") if allocation else None,
        "ssh_ready": machine.ssh is not None,
    }
    if monitor_state is not None:
        payload["monitor_status"] = monitor_state.status
        payload["monitor_error"] = monitor_state.error
        if monitor_state.inspection is not None:
            payload["last_observed_at"] = monitor_state.inspection.observed_at
            payload["health"] = (
                monitor_state.health.health if monitor_state.health else None
            )
    return payload


def _allocation(
    service: FleetService, machine: FleetMachine
) -> dict[str, Any] | None:
    if not service.ledger:
        return None
    try:
        return service.ledger.allocation_for_machine(machine)
    except KeyError:
        return None


def _verification(service: FleetService, host_id: str) -> dict[str, Any] | None:
    if not service.ledger:
        return None
    return service.ledger.latest_capacity_verification(host_id)


def _verification_checks(verification: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not verification:
        return []
    payload = json.loads(str(verification["checks_json"]))
    return list(payload.get("rows") or [])


def _monitor_interval() -> float:
    value = os.getenv("COMPUTE_BAZAAR_FLEET_INTERVAL_SECONDS", "5")
    try:
        return max(1.0, float(value))
    except ValueError:
        return 5.0
