"""Local Fleet inventory, inspection, and live telemetry workspace."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from ..fleet import FleetMachine, FleetMonitor, FleetService


class FleetWorkspace:
    def __init__(
        self,
        *,
        asset_root: Path,
        service: FleetService | None = None,
        monitor: FleetMonitor | None = None,
    ) -> None:
        self.asset_root = asset_root
        self.service = service or FleetService.local()
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
            if state.inspection is None or state.doctor is None:
                raise HTTPException(
                    status_code=503,
                    detail=state.error or "Waiting for Fleet sample",
                )
            inspection = state.inspection
            doctor = state.doctor
            return {
                "contract": "compute-bazaar.fleet-host.v1",
                "machine": _machine_payload(
                    inspection.machine,
                    monitor_state=state,
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
                "readiness": doctor.readiness,
                "checks": [check.model_dump(mode="json") for check in doctor.checks],
            }


def _machine_payload(
    machine: FleetMachine,
    *,
    monitor_state: Any | None = None,
) -> dict[str, Any]:
    payload = {
        "host_id": machine.host_id,
        "provider": machine.provider,
        "name": machine.name,
        "state": machine.state,
        "gpu_model": machine.gpu_model,
        "gpu_count": machine.gpu_count,
        "price_usd_gpu_hr": machine.price_usd_gpu_hr,
        "price_usd_instance_hr": machine.price_usd_instance_hr,
        "created_at": machine.created_at,
        "terminate_at": machine.terminate_at,
        "ssh_ready": machine.ssh is not None,
    }
    if monitor_state is not None:
        payload["monitor_status"] = monitor_state.status
        payload["monitor_error"] = monitor_state.error
        if monitor_state.inspection is not None:
            payload["last_observed_at"] = monitor_state.inspection.observed_at
            payload["readiness"] = (
                monitor_state.doctor.readiness if monitor_state.doctor else None
            )
    return payload


def _monitor_interval() -> float:
    value = os.getenv("COMPUTE_BAZAAR_FLEET_INTERVAL_SECONDS", "5")
    try:
        return max(1.0, float(value))
    except ValueError:
        return 5.0
