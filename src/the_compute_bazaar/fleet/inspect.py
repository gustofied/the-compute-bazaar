"""Read-only SSH inspection for Fleet machines."""

from __future__ import annotations

import csv
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from .models import FleetInspection, FleetMachine, GpuDevice, GpuProcess
from .ssh import ssh_command


PROBE = r"""
set -u
field() { printf 'CBZ\t%s\t%s\n' "$1" "$2"; }
field kernel "$(uname -sr 2>/dev/null || true)"
field os_name "$(. /etc/os-release 2>/dev/null && printf '%s' "${PRETTY_NAME:-${NAME:-}}" || true)"
field cpu_model "$(lscpu 2>/dev/null | awk -F: '/Model name/ {sub(/^[ \t]+/, "", $2); print $2; exit}' || true)"
cpu_quota="$(cat /sys/fs/cgroup/cpu.max 2>/dev/null | awk '$1 != "max" && $2 > 0 {printf "%.2f", $1 / $2}' || true)"
if [ -z "$cpu_quota" ]; then
  cpu_quota_us="$(cat /sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us 2>/dev/null || true)"
  cpu_period_us="$(cat /sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us 2>/dev/null || true)"
  if [ "${cpu_quota_us:-0}" -gt 0 ] 2>/dev/null && [ "${cpu_period_us:-0}" -gt 0 ] 2>/dev/null; then
    cpu_quota="$(awk -v q="$cpu_quota_us" -v p="$cpu_period_us" 'BEGIN {printf "%.2f", q / p}')"
  fi
fi
field cpu_count "${cpu_quota:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)}"
cpu_usage_path=""
if [ -r /sys/fs/cgroup/cpu.stat ]; then cpu_usage_path=/sys/fs/cgroup/cpu.stat; fi
if [ -r /sys/fs/cgroup/cpu,cpuacct/cpuacct.usage ]; then cpu_usage_path=/sys/fs/cgroup/cpu,cpuacct/cpuacct.usage; fi
if [ -n "$cpu_usage_path" ] && [ -n "${cpu_quota:-}" ]; then
  if [ "$cpu_usage_path" = /sys/fs/cgroup/cpu.stat ]; then
    cpu_before="$(awk '/usage_usec/ {print $2 * 1000}' "$cpu_usage_path")"
  else
    cpu_before="$(cat "$cpu_usage_path")"
  fi
  sleep 0.2
  if [ "$cpu_usage_path" = /sys/fs/cgroup/cpu.stat ]; then
    cpu_after="$(awk '/usage_usec/ {print $2 * 1000}' "$cpu_usage_path")"
  else
    cpu_after="$(cat "$cpu_usage_path")"
  fi
  field cpu_utilization_pct "$(awk -v a="$cpu_after" -v b="$cpu_before" -v c="$cpu_quota" 'BEGIN {v=(a-b)/(200000000*c)*100; if (v<0) v=0; if (v>100) v=100; printf "%.1f", v}')"
fi
memory_total_bytes="$(cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || true)"
memory_used_bytes="$(cat /sys/fs/cgroup/memory.current 2>/dev/null || cat /sys/fs/cgroup/memory/memory.usage_in_bytes 2>/dev/null || true)"
case "$memory_total_bytes" in ""|max) memory_total_bytes="$(awk '/MemTotal:/ {print $2 * 1024}' /proc/meminfo 2>/dev/null || true)";; esac
case "$memory_used_bytes" in "") memory_used_bytes="$(awk '/MemTotal:/ {t=$2} /MemAvailable:/ {printf "%.0f", (t-$2)*1024}' /proc/meminfo 2>/dev/null || true)";; esac
field memory_mb "$(awk -v b="${memory_total_bytes:-0}" 'BEGIN {printf "%d", b / 1024 / 1024}')"
field memory_used_mb "$(awk -v b="${memory_used_bytes:-0}" 'BEGIN {printf "%d", b / 1024 / 1024}')"
disk_line="$(df -Pk / 2>/dev/null | awk 'NR==2 {printf "%d %d %d", $2/1024/1024, $3/1024/1024, $4/1024/1024}' || true)"
set -- $disk_line
field disk_total_gb "${1:-}"
field disk_used_gb "${2:-}"
field disk_free_gb "${3:-}"
field uptime_seconds "$(awk '{printf "%d", $1}' /proc/uptime 2>/dev/null || true)"
field driver_cuda_version "$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: \([0-9.]*\).*/\1/p' | head -1 || true)"
field cuda_toolkit_version "$(nvcc --version 2>/dev/null | sed -n 's/.*release \([^,]*\).*/\1/p' | tail -1 || true)"
field docker_version "$(docker --version 2>/dev/null || true)"
if [ "${CBZ_VERIFY_GPU_EXECUTION:-0}" = 1 ]; then
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import torch' >/dev/null 2>&1; then
    if python3 -c 'import torch; x=torch.ones(1, device="cuda"); y=(x+x).item(); torch.cuda.synchronize(); assert y == 2' >/dev/null 2>&1; then
      field gpu_execution_status pass
      field gpu_execution_detail "PyTorch CUDA tensor operation completed"
    else
      field gpu_execution_status fail
      field gpu_execution_detail "PyTorch CUDA tensor operation failed"
    fi
  else
    field gpu_execution_status not_tested
    field gpu_execution_detail "PyTorch CUDA runtime not present"
  fi
else
  field gpu_execution_status not_tested
  field gpu_execution_detail "not checked by telemetry probe"
fi
printf 'CBZ_GPU_BEGIN\n'
nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.used,utilization.gpu,power.draw,power.limit,temperature.gpu,temperature.gpu.tlimit,driver_version,pstate,pci.bus_id,pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max --format=csv,noheader,nounits 2>/dev/null || true
printf 'CBZ_GPU_END\n'
printf 'CBZ_GPU_PROCESS_BEGIN\n'
nvidia-smi --query-compute-apps=pid,process_name,gpu_uuid,used_gpu_memory --format=csv,noheader,nounits 2>/dev/null || true
printf 'CBZ_GPU_PROCESS_END\n'
""".strip()


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class FleetInspectError(RuntimeError):
    pass


class FleetInspector:
    def __init__(
        self,
        *,
        runner: CommandRunner = subprocess.run,
        known_hosts_file: Path | None = None,
    ) -> None:
        self.runner = runner
        self.known_hosts_file = known_hosts_file

    def inspect(
        self,
        machine: FleetMachine,
        *,
        verify_gpu_execution: bool = False,
    ) -> FleetInspection:
        if machine.ssh is None:
            raise FleetInspectError(f"Fleet host {machine.host_id} has no SSH endpoint")
        command = ssh_command(
            machine,
            remote_command="sh -s",
            known_hosts_file=self.known_hosts_file,
        )
        result = self.runner(
            command,
            input=(f"CBZ_VERIFY_GPU_EXECUTION={int(verify_gpu_execution)}\n{PROBE}"),
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or "SSH probe failed"
            raise FleetInspectError(detail)
        return _parse_probe(machine, result.stdout, observed_at=datetime.now(UTC))


def _parse_probe(
    machine: FleetMachine,
    output: str,
    *,
    observed_at: datetime,
) -> FleetInspection:
    fields: dict[str, str] = {}
    gpu_lines: list[str] = []
    process_lines: list[str] = []
    in_gpus = False
    in_processes = False
    for line in output.splitlines():
        if line == "CBZ_GPU_BEGIN":
            in_gpus = True
            continue
        if line == "CBZ_GPU_END":
            in_gpus = False
            continue
        if line == "CBZ_GPU_PROCESS_BEGIN":
            in_processes = True
            continue
        if line == "CBZ_GPU_PROCESS_END":
            in_processes = False
            continue
        if in_gpus:
            if line.strip():
                gpu_lines.append(line)
            continue
        if in_processes:
            if line.strip():
                process_lines.append(line)
            continue
        if line.startswith("CBZ\t"):
            _, key, value = line.split("\t", 2)
            fields[key] = value.strip()

    devices: list[GpuDevice] = []
    for row in csv.reader(StringIO("\n".join(gpu_lines)), skipinitialspace=True):
        if len(row) != 17:
            continue
        devices.append(
            GpuDevice(
                index=_integer(row[0]) or 0,
                uuid=row[1].strip() or None,
                name=row[2].strip(),
                memory_total_mb=_integer(row[3]) or 0,
                memory_used_mb=_integer(row[4]) or 0,
                utilization_pct=_float(row[5]),
                power_draw_w=_float(row[6]),
                power_limit_w=_float(row[7]),
                temperature_c=_integer(row[8]),
                temperature_limit_c=_integer(row[9]),
                driver_version=row[10].strip(),
                performance_state=row[11].strip() or None,
                pci_bus_id=row[12].strip() or None,
                pcie_generation_current=_integer(row[13]),
                pcie_generation_max=_integer(row[14]),
                pcie_width_current=_integer(row[15]),
                pcie_width_max=_integer(row[16]),
            )
        )
    indexes = {device.uuid: device.index for device in devices if device.uuid}
    processes: list[GpuProcess] = []
    for row in csv.reader(StringIO("\n".join(process_lines)), skipinitialspace=True):
        if len(row) != 4 or _integer(row[0]) is None:
            continue
        gpu_uuid = row[2].strip() or None
        processes.append(
            GpuProcess(
                pid=_integer(row[0]) or 0,
                process_name=row[1].strip(),
                gpu_uuid=gpu_uuid,
                gpu_index=indexes.get(gpu_uuid),
                memory_used_mb=_integer(row[3]),
            )
        )
    return FleetInspection(
        machine=machine,
        observed_at=observed_at,
        os_name=fields.get("os_name") or None,
        kernel=fields.get("kernel") or None,
        cpu_model=fields.get("cpu_model") or None,
        cpu_count=_float(fields.get("cpu_count")),
        cpu_utilization_pct=_float(fields.get("cpu_utilization_pct")),
        memory_mb=_integer(fields.get("memory_mb")),
        memory_used_mb=_integer(fields.get("memory_used_mb")),
        disk_total_gb=_integer(fields.get("disk_total_gb")),
        disk_used_gb=_integer(fields.get("disk_used_gb")),
        disk_free_gb=_integer(fields.get("disk_free_gb")),
        uptime_seconds=_integer(fields.get("uptime_seconds")),
        driver_cuda_version=fields.get("driver_cuda_version") or None,
        cuda_toolkit_version=fields.get("cuda_toolkit_version") or None,
        docker_version=fields.get("docker_version") or None,
        gpu_execution_status=fields.get("gpu_execution_status") or "not_tested",
        gpu_execution_detail=fields.get("gpu_execution_detail") or None,
        gpus=tuple(devices),
        gpu_processes=tuple(processes),
    )


def _integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value.strip()))
    except (TypeError, ValueError):
        return None


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return None
