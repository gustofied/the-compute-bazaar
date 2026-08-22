"""Fleet inventory and readiness operations."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..prices.normalize import canonical_gpu_model
from .inspect import FleetInspectError, FleetInspector
from .models import (
    DoctorCheck,
    FleetDoctorResult,
    FleetHealthResult,
    FleetInspection,
    FleetMachine,
    GpuDevice,
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

    def attach(
        self,
        ssh_target: str,
        *,
        name: str | None = None,
        expected_gpu_model: str | None = None,
        expected_gpu_count: int | None = None,
    ) -> tuple[FleetInspection, FleetHealthResult]:
        from .models import SshEndpoint

        candidate = FleetMachine(
            host_id=ssh_target,
            name=name or ssh_target,
            state="running",
            expected_gpu_model=expected_gpu_model,
            expected_gpu_count=expected_gpu_count,
            created_at=datetime.now(UTC),
            ssh=SshEndpoint(target=ssh_target),
        )
        inspection = self.inspector.inspect(candidate, verify_gpu_execution=False)
        if not inspection.gpus:
            raise FleetInspectError(f"No NVIDIA GPU detected on {ssh_target}")

        machine = candidate.model_copy(
            update={
                "expected_gpu_model": expected_gpu_model
                or _detected_gpu_model(inspection),
                "expected_gpu_count": expected_gpu_count or len(inspection.gpus),
            }
        )
        inspection = inspection.model_copy(update={"machine": machine})
        health = self.health_inspection(inspection)
        self.registry.put(machine)
        if self.ledger:
            self.ledger.record_telemetry(inspection)
        return inspection, health

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
    expected_count = inspection.machine.expected_gpu_count
    expected_model = inspection.machine.expected_gpu_model
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
        if (current_gen is not None and max_gen is not None and current_gen < max_gen)
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
            status=(
                "fail"
                if not detected
                else "warn"
                if expected_count is not None and detected != expected_count
                else "pass"
            ),
            detail=(
                f"detected {detected}; expected {expected_count}"
                if expected_count is not None
                else f"detected {detected}"
            ),
        ),
        DoctorCheck(
            check="gpu_model",
            status=(
                "fail"
                if not inspection.gpus
                else "warn"
                if expected_model
                and not all(
                    _gpu_model_matches(expected_model, gpu) for gpu in inspection.gpus
                )
                else "pass"
            ),
            detail=(
                f"detected {_detected_gpu_names(inspection)}; expected {expected_model}"
                if expected_model
                else f"detected {_detected_gpu_names(inspection)}"
            ),
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


def _detected_gpu_model(inspection: FleetInspection) -> str | None:
    models = {
        canonical_gpu_model(gpu.name, gpu.memory_total_mb) or gpu.name
        for gpu in inspection.gpus
    }
    return next(iter(models)) if len(models) == 1 else None


def _detected_gpu_names(inspection: FleetInspection) -> str:
    return ", ".join(sorted({gpu.name for gpu in inspection.gpus})) or "none"


def _gpu_model_matches(expected: str, gpu: GpuDevice) -> bool:
    memory = re.search(r"(\d+)\s*GB", expected.upper())
    expected_name = re.sub(r"_X\d+$", "", expected, flags=re.IGNORECASE)
    expected_name = re.sub(r"_\d+GB$", "", expected_name, flags=re.IGNORECASE)
    expected_name = re.sub(
        r"RTXPRO(\d+)B$",
        r"RTX PRO \1",
        expected_name,
        flags=re.IGNORECASE,
    )
    expected_canonical = canonical_gpu_model(
        expected_name,
        int(memory.group(1)) * 1024 if memory else None,
    )
    detected_canonical = canonical_gpu_model(gpu.name, gpu.memory_total_mb)
    if expected_canonical and detected_canonical:
        return expected_canonical == detected_canonical
    expected_key = re.sub(r"[^A-Z0-9]", "", expected.upper())
    detected_key = re.sub(r"[^A-Z0-9]", "", gpu.name.upper())
    return expected_key in detected_key or detected_key in expected_key


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
