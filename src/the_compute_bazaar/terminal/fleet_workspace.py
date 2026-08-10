"""Local Fleet inventory, inspection, and live telemetry workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from ..fleet import FleetInspectError, FleetMachine, FleetService


class FleetWorkspace:
    def __init__(
        self, *, asset_root: Path, service: FleetService | None = None
    ) -> None:
        self.asset_root = asset_root
        self.service = service or FleetService()

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
                "refresh_seconds": 5,
                "hosts": [
                    _machine_payload(machine) for machine in self.service.hosts()
                ],
            }

        @app.get("/api/fleet/hosts/{host_id}")
        def host(host_id: str) -> dict[str, Any]:
            try:
                inspection = self.service.inspect(host_id)
                doctor = self.service.doctor_inspection(inspection)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except FleetInspectError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {
                "contract": "compute-bazaar.fleet-host.v1",
                "machine": _machine_payload(inspection.machine),
                "observed_at": inspection.observed_at,
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
                    "cuda_version": inspection.cuda_version,
                    "docker_version": inspection.docker_version,
                },
                "gpus": [gpu.model_dump(mode="json") for gpu in inspection.gpus],
                "readiness": doctor.readiness,
                "checks": [check.model_dump(mode="json") for check in doctor.checks],
            }


def _machine_payload(machine: FleetMachine) -> dict[str, Any]:
    return {
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
