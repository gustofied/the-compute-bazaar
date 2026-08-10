"""Fleet inventory and readiness operations."""

from __future__ import annotations

from datetime import UTC, datetime

from .inspect import FleetInspector
from .models import DoctorCheck, FleetDoctorResult, FleetInspection, FleetMachine
from .registry import FleetRegistry


class FleetService:
    def __init__(
        self,
        *,
        registry: FleetRegistry | None = None,
        inspector: FleetInspector | None = None,
    ) -> None:
        self.registry = registry or FleetRegistry()
        self.inspector = inspector or FleetInspector()

    def hosts(self) -> list[FleetMachine]:
        return self.registry.list()

    def inspect(self, host_id: str) -> FleetInspection:
        return self.inspector.inspect(self.registry.get(host_id))

    def doctor(self, host_id: str) -> FleetDoctorResult:
        inspection = self.inspect(host_id)
        return self.doctor_inspection(inspection)

    def doctor_inspection(self, inspection: FleetInspection) -> FleetDoctorResult:
        checks = _readiness_checks(inspection)
        required_failed = any(
            check.status == "fail"
            for check in checks
            if check.check in {"ssh", "gpu_count", "driver", "disk"}
        )
        warned = any(check.status == "warn" for check in checks)
        readiness = (
            "not_ready" if required_failed else "degraded" if warned else "ready"
        )
        return FleetDoctorResult(
            host_id=inspection.machine.host_id,
            observed_at=datetime.now(UTC),
            readiness=readiness,
            checks=tuple(checks),
        )


def _readiness_checks(inspection: FleetInspection) -> list[DoctorCheck]:
    expected = inspection.machine.gpu_count
    detected = len(inspection.gpus)
    checks = [
        DoctorCheck(check="ssh", status="pass", detail="read-only probe completed"),
        DoctorCheck(
            check="gpu_count",
            status="pass" if detected >= expected else "fail",
            detail=f"detected {detected}; expected {expected}",
        ),
        DoctorCheck(
            check="driver",
            status="pass"
            if inspection.gpus and inspection.gpus[0].driver_version
            else "fail",
            detail=(
                inspection.gpus[0].driver_version if inspection.gpus else "not detected"
            ),
        ),
        DoctorCheck(
            check="disk",
            status="pass"
            if inspection.disk_free_gb is not None and inspection.disk_free_gb >= 10
            else "fail",
            detail=f"{inspection.disk_free_gb or 0} GB free",
        ),
        DoctorCheck(
            check="gpu_memory",
            status="pass"
            if inspection.gpus and inspection.gpus[0].memory_total_mb > 0
            else "fail",
            detail=(
                f"{inspection.gpus[0].memory_total_mb} MB"
                if inspection.gpus
                else "not detected"
            ),
        ),
        DoctorCheck(
            check="temperature",
            status=(
                "pass"
                if inspection.gpus and (inspection.gpus[0].temperature_c or 0) < 85
                else "warn"
            ),
            detail=(
                f"{inspection.gpus[0].temperature_c} C"
                if inspection.gpus and inspection.gpus[0].temperature_c is not None
                else "not reported"
            ),
        ),
    ]
    return checks
