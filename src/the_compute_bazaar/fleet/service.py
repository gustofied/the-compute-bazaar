"""Fleet inventory and readiness operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .inspect import FleetInspector
from .models import (
    DoctorCheck,
    FleetDoctorResult,
    FleetHealthResult,
    FleetInspection,
    FleetMachine,
)
from .registry import FleetRegistry

if TYPE_CHECKING:
    from ..operations import OperationalLedger


class FleetService:
    def __init__(
        self,
        *,
        registry: FleetRegistry | None = None,
        inspector: FleetInspector | None = None,
        ledger: OperationalLedger | None = None,
    ) -> None:
        self.registry = registry or FleetRegistry()
        self.inspector = inspector or FleetInspector()
        self.ledger = ledger

    @classmethod
    def local(cls) -> FleetService:
        from ..operations import OperationalLedger

        return cls(ledger=OperationalLedger())

    def hosts(self) -> list[FleetMachine]:
        return self.registry.list()

    def inspect(self, host_id: str) -> FleetInspection:
        inspection = self.inspector.inspect(
            self.registry.get(host_id), verify_gpu_execution=False
        )
        if self.ledger:
            self.ledger.record_telemetry(inspection)
        return inspection

    def doctor(self, host_id: str) -> FleetDoctorResult:
        inspection = self.inspector.inspect(
            self.registry.get(host_id), verify_gpu_execution=True
        )
        result = self.doctor_inspection(inspection)
        if self.ledger:
            self.ledger.record_telemetry(inspection)
            self.ledger.record_capacity_verification(inspection, result)
        return result

    def monitor(self, host_id: str) -> tuple[FleetInspection, FleetHealthResult]:
        inspection = self.inspector.inspect(
            self.registry.get(host_id), verify_gpu_execution=False
        )
        result = self.health_inspection(inspection)
        if self.ledger:
            self.ledger.record_telemetry(inspection)
        return inspection, result

    def doctor_inspection(
        self,
        inspection: FleetInspection,
    ) -> FleetDoctorResult:
        checks = [*_health_checks(inspection), _gpu_execution_check(inspection)]
        required_failed = any(check.status == "fail" for check in checks)
        warned = any(check.status == "warn" for check in checks)
        readiness = (
            "not_ready" if required_failed else "degraded" if warned else "ready"
        )
        result = FleetDoctorResult(
            host_id=inspection.machine.host_id,
            observed_at=datetime.now(UTC),
            readiness=readiness,
            checks=tuple(checks),
        )
        return result

    @staticmethod
    def health_inspection(inspection: FleetInspection) -> FleetHealthResult:
        checks = _health_checks(inspection)
        failed = any(check.status == "fail" for check in checks)
        warned = any(check.status == "warn" for check in checks)
        health = "unhealthy" if failed else "degraded" if warned else "healthy"
        return FleetHealthResult(
            host_id=inspection.machine.host_id,
            observed_at=inspection.observed_at,
            health=health,
            checks=tuple(checks),
        )


def _health_checks(inspection: FleetInspection) -> list[DoctorCheck]:
    expected = inspection.machine.gpu_count
    detected = len(inspection.gpus)
    drivers = sorted(
        {gpu.driver_version for gpu in inspection.gpus if gpu.driver_version}
    )
    memory = [gpu.memory_total_mb for gpu in inspection.gpus]
    temperatures = [
        (gpu.index, gpu.temperature_c)
        for gpu in inspection.gpus
        if gpu.temperature_c is not None
    ]
    links = [
        (
            gpu.index,
            gpu.pcie_generation_current,
            gpu.pcie_generation_max,
            gpu.pcie_width_current,
            gpu.pcie_width_max,
        )
        for gpu in inspection.gpus
    ]
    narrowed_links = [
        index
        for index, current_gen, max_gen, current_width, max_width in links
        if (
            current_gen is not None
            and max_gen is not None
            and current_gen < max_gen
        )
        or (
            current_width is not None
            and max_width is not None
            and current_width < max_width
        )
    ]
    checks = [
        DoctorCheck(check="ssh", status="pass", detail="read-only probe completed"),
        DoctorCheck(
            check="gpu_count",
            status="pass" if detected >= expected else "fail",
            detail=f"detected {detected}; expected {expected}",
        ),
        DoctorCheck(
            check="driver",
            status="pass" if detected and len(drivers) == 1 else "fail",
            detail=", ".join(drivers) if drivers else "not detected",
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
            if detected and all(value > 0 for value in memory)
            else "fail",
            detail=(
                ", ".join(
                    f"GPU {gpu.index}: {gpu.memory_total_mb} MB"
                    for gpu in inspection.gpus
                )
                or "not detected"
            ),
        ),
        DoctorCheck(
            check="temperature",
            status=(
                "pass"
                if temperatures and all(value < 85 for _, value in temperatures)
                else "warn"
            ),
            detail=(
                ", ".join(f"GPU {index}: {value} C" for index, value in temperatures)
                or "not reported"
            ),
        ),
        DoctorCheck(
            check="pcie_link",
            status="pass" if links and not narrowed_links else "warn",
            detail=(
                "; ".join(
                    f"GPU {index}: Gen {current_gen or '?'} / {max_gen or '?'}; "
                    f"x{current_width or '?'} / x{max_width or '?'}"
                    for index, current_gen, max_gen, current_width, max_width in links
                )
                or "not reported"
            ),
        ),
    ]
    return checks


def _gpu_execution_check(inspection: FleetInspection) -> DoctorCheck:
    return DoctorCheck(
        check="gpu_execution",
        status=(
            "pass"
            if inspection.gpu_execution_status == "pass"
            else "fail"
            if inspection.gpu_execution_status == "fail"
            else "warn"
        ),
        detail=inspection.gpu_execution_detail or "not tested",
    )
