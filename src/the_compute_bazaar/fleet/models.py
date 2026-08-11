"""Typed records for machines operated by Compute Bazaar Fleet."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MachineState = Literal[
    "provisioning",
    "running",
    "stopped",
    "terminated",
    "unknown",
]


class SshEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    host: str
    port: int = Field(ge=1, le=65535)
    user: str = "root"
    identity_file: str


class FleetMachine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    host_id: str
    provider: str
    provider_resource_id: str
    name: str
    state: MachineState
    gpu_model: str
    gpu_count: int = Field(ge=1)
    price_usd_gpu_hr: float = Field(gt=0)
    price_usd_instance_hr: float = Field(gt=0)
    created_at: datetime
    terminate_at: datetime
    ssh: SshEndpoint | None = None

    @model_validator(mode="after")
    def validate_times(self) -> FleetMachine:
        for field in ("created_at", "terminate_at"):
            value = getattr(self, field)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field} must be timezone-aware")
        if self.terminate_at <= self.created_at:
            raise ValueError("terminate_at must follow created_at")
        return self

    def row(self) -> dict[str, object]:
        return {
            "host_id": self.host_id,
            "provider": self.provider,
            "name": self.name,
            "state": self.state,
            "gpu_model": self.gpu_model,
            "gpu_count": self.gpu_count,
            "price_usd_instance_hr": self.price_usd_instance_hr,
            "ssh_host": self.ssh.host if self.ssh else None,
            "terminate_at": self.terminate_at,
        }


class GpuDevice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0)
    name: str
    memory_total_mb: int = Field(ge=0)
    memory_used_mb: int = Field(default=0, ge=0)
    utilization_pct: float | None = Field(default=None, ge=0, le=100)
    power_draw_w: float | None = Field(default=None, ge=0)
    power_limit_w: float | None = Field(default=None, ge=0)
    driver_version: str
    temperature_c: int | None = None
    temperature_limit_c: int | None = None
    performance_state: str | None = None
    pci_bus_id: str | None = None
    pcie_generation_current: int | None = Field(default=None, ge=0)
    pcie_generation_max: int | None = Field(default=None, ge=0)
    pcie_width_current: int | None = Field(default=None, ge=0)
    pcie_width_max: int | None = Field(default=None, ge=0)


class FleetInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    machine: FleetMachine
    observed_at: datetime
    os_name: str | None = None
    kernel: str | None = None
    cpu_model: str | None = None
    cpu_count: float | None = Field(default=None, ge=0)
    cpu_utilization_pct: float | None = Field(default=None, ge=0, le=100)
    memory_mb: int | None = Field(default=None, ge=0)
    memory_used_mb: int | None = Field(default=None, ge=0)
    disk_total_gb: int | None = Field(default=None, ge=0)
    disk_used_gb: int | None = Field(default=None, ge=0)
    disk_free_gb: int | None = Field(default=None, ge=0)
    uptime_seconds: int | None = Field(default=None, ge=0)
    driver_cuda_version: str | None = None
    cuda_toolkit_version: str | None = None
    docker_version: str | None = None
    gpu_execution_status: Literal["pass", "fail", "not_tested"] = "not_tested"
    gpu_execution_detail: str | None = None
    gpus: tuple[GpuDevice, ...] = ()

    def row(self) -> dict[str, object]:
        return {
            "host_id": self.machine.host_id,
            "provider": self.machine.provider,
            "state": self.machine.state,
            "os": self.os_name,
            "kernel": self.kernel,
            "cpu_count": self.cpu_count,
            "cpu_utilization_pct": self.cpu_utilization_pct,
            "memory_mb": self.memory_mb,
            "memory_used_mb": self.memory_used_mb,
            "disk_total_gb": self.disk_total_gb,
            "disk_used_gb": self.disk_used_gb,
            "disk_free_gb": self.disk_free_gb,
            "gpu_count": len(self.gpus),
            "gpu_names": ", ".join(device.name for device in self.gpus),
            "driver": self.gpus[0].driver_version if self.gpus else None,
            "driver_cuda_version": self.driver_cuda_version,
            "cuda_toolkit_version": self.cuda_toolkit_version,
            "observed_at": self.observed_at,
        }


class DoctorCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check: str
    status: Literal["pass", "warn", "fail"]
    detail: str


class FleetDoctorResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    host_id: str
    observed_at: datetime
    readiness: Literal["ready", "degraded", "not_ready"]
    checks: tuple[DoctorCheck, ...]

    def payload(self) -> dict[str, object]:
        return {
            "contract": "compute-bazaar.fleet-doctor.v1",
            "observed_at": self.observed_at,
            "host_id": self.host_id,
            "readiness": self.readiness,
            "rows": [check.model_dump(mode="json") for check in self.checks],
        }
