from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from the_compute_bazaar.fleet import (
    FleetInspector,
    FleetInspection,
    FleetMachine,
    FleetMonitor,
    FleetRegistry,
    FleetService,
    GpuProcess,
    SshEndpoint,
)
from the_compute_bazaar.fleet.models import GpuDevice


def machine(
    identity_file: Path,
    *,
    allocation_id: str | None = "allocation-123",
) -> FleetMachine:
    created_at = datetime(2026, 8, 10, 12, tzinfo=UTC)
    return FleetMachine(
        host_id="runpod:pod-123",
        allocation_id=allocation_id,
        name="bazaar-h100-01",
        state="running",
        gpu_model="H100_80GB",
        gpu_count=1,
        created_at=created_at,
        ssh=SshEndpoint(
            host="203.0.113.10",
            port=22123,
            user="root",
            identity_file=str(identity_file),
        ),
    )


PROBE_OUTPUT = """\
CBZ\tkernel\tLinux 6.8.0
CBZ\tos_name\tUbuntu 24.04 LTS
CBZ\tcpu_model\tAMD EPYC 9354P
CBZ\tcpu_count\t13.60
CBZ\tcpu_utilization_pct\t2.5
CBZ\tmemory_mb\t239372
CBZ\tmemory_used_mb\t154
CBZ\tdisk_total_gb\t50
CBZ\tdisk_used_gb\t1
CBZ\tdisk_free_gb\t80
CBZ\tuptime_seconds\t42
CBZ\tdriver_cuda_version\t12.8
CBZ\tcuda_toolkit_version\t12.8
CBZ\tdocker_version\tDocker version 27.0.0
CBZ\tgpu_execution_status\tpass
CBZ\tgpu_execution_detail\tPyTorch CUDA tensor operation completed
CBZ_GPU_BEGIN
0, GPU-abc, NVIDIA H100 80GB HBM3, 81559, 120, 14, 80.2, 310, 31, 47, 570.86.15, P0, 00000000:01:00.0, 4, 4, 16, 16
CBZ_GPU_END
CBZ_GPU_PROCESS_BEGIN
4242, python, GPU-abc, 96
CBZ_GPU_PROCESS_END
"""


class FleetTest(unittest.TestCase):
    def test_registry_round_trips_machine_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = machine(root / "id_ed25519")
            registry = FleetRegistry(root / "fleet")

            registry.put(selected)

            self.assertEqual(registry.get(selected.host_id), selected)
            self.assertEqual(registry.list(), [selected])

    def test_inspect_and_doctor_verify_gpu_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "id_ed25519"
            identity.write_text("test", encoding="utf-8")
            selected = machine(identity)
            registry = FleetRegistry(root / "fleet")
            registry.put(selected)
            calls: list[tuple[list[str], str]] = []

            def fake_runner(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                script = str(kwargs.get("input", ""))
                calls.append((command, script))
                output = PROBE_OUTPUT
                if script.startswith("CBZ_VERIFY_GPU_EXECUTION=0"):
                    output = output.replace(
                        "CBZ\tgpu_execution_status\tpass",
                        "CBZ\tgpu_execution_status\tnot_tested",
                    ).replace(
                        "CBZ\tgpu_execution_detail\tPyTorch CUDA tensor operation completed",
                        "CBZ\tgpu_execution_detail\tnot checked by telemetry probe",
                    )
                return subprocess.CompletedProcess(command, 0, output, "")

            inspector = FleetInspector(
                runner=fake_runner,
                known_hosts_file=root / "known_hosts",
            )
            service = FleetService(registry=registry, inspector=inspector)

            inspection = service.inspect(selected.host_id)
            result = service.doctor(selected.host_id)

            self.assertEqual(inspection.gpus[0].name, "NVIDIA H100 80GB HBM3")
            self.assertEqual(inspection.gpus[0].memory_total_mb, 81559)
            self.assertEqual(inspection.gpus[0].memory_used_mb, 120)
            self.assertEqual(inspection.gpus[0].utilization_pct, 14)
            self.assertEqual(
                inspection.gpu_processes,
                (
                    GpuProcess(
                        pid=4242,
                        process_name="python",
                        gpu_uuid="GPU-abc",
                        gpu_index=0,
                        memory_used_mb=96,
                    ),
                ),
            )
            self.assertEqual(inspection.cpu_count, 13.6)
            self.assertEqual(result.readiness, "ready")
            self.assertIn("StrictHostKeyChecking=accept-new", calls[0][0])
            self.assertIn("ControlMaster=auto", calls[0][0])
            self.assertTrue(calls[0][1].startswith("CBZ_VERIFY_GPU_EXECUTION=0"))
            self.assertTrue(calls[1][1].startswith("CBZ_VERIFY_GPU_EXECUTION=1"))

    def test_monitor_is_lightweight_and_records_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = machine(root / "id_ed25519")
            registry = FleetRegistry(root / "fleet")
            registry.put(selected)
            scripts: list[str] = []
            records: list[tuple[object, object]] = []

            def fake_runner(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                scripts.append(str(kwargs.get("input", "")))
                output = PROBE_OUTPUT.replace(
                    "CBZ\tgpu_execution_status\tpass",
                    "CBZ\tgpu_execution_status\tnot_tested",
                ).replace(
                    "CBZ\tgpu_execution_detail\tPyTorch CUDA tensor operation completed",
                    "CBZ\tgpu_execution_detail\tnot checked by telemetry probe",
                )
                return subprocess.CompletedProcess(command, 0, output, "")

            class Ledger:
                def record_telemetry(self, inspection: object) -> None:
                    records.append((inspection, None))

            service = FleetService(
                registry=registry,
                inspector=FleetInspector(
                    runner=fake_runner,
                    known_hosts_file=root / "known_hosts",
                ),
                ledger=Ledger(),  # type: ignore[arg-type]
            )

            _, result = service.monitor(selected.host_id)

            self.assertEqual(result.health, "healthy")
            self.assertNotIn("gpu_execution", {check.check for check in result.checks})
            self.assertEqual(len(records), 1)
            self.assertTrue(scripts[0].startswith("CBZ_VERIFY_GPU_EXECUTION=0"))

    def test_background_monitor_keeps_last_sample_after_host_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = machine(root / "id_ed25519")
            registry = FleetRegistry(root / "fleet")
            registry.put(selected)
            failing = False

            def fake_runner(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                if failing:
                    return subprocess.CompletedProcess(command, 255, "", "timeout")
                return subprocess.CompletedProcess(command, 0, PROBE_OUTPUT, "")

            service = FleetService(
                registry=registry,
                inspector=FleetInspector(
                    runner=fake_runner,
                    known_hosts_file=root / "known_hosts",
                ),
            )
            monitor = FleetMonitor(service, interval_seconds=1)

            monitor.poll_once()
            first = monitor.state(selected.host_id)
            self.assertIsNotNone(first)
            assert first is not None
            self.assertEqual(first.status, "ok")

            failing = True
            monitor.poll_once()
            stale = monitor.state(selected.host_id)
            self.assertIsNotNone(stale)
            assert stale is not None
            self.assertEqual(stale.status, "stale")
            self.assertEqual(stale.inspection, first.inspection)
            self.assertEqual(stale.consecutive_failures, 1)

    def test_one_bad_gpu_blocks_multi_gpu_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = machine(root / "id_ed25519").model_copy(update={"gpu_count": 2})
            registry = FleetRegistry(root / "fleet")
            registry.put(selected)
            output = PROBE_OUTPUT.replace(
                "CBZ_GPU_END",
                "1, GPU-def, NVIDIA H100 80GB HBM3, 0, 0, 0, 70, 310, 32, 47, "
                "570.86.15, P0, 00000000:02:00.0, 4, 4, 8, 16\n"
                "CBZ_GPU_END",
            )

            def fake_runner(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(command, 0, output, "")

            service = FleetService(
                registry=registry,
                inspector=FleetInspector(
                    runner=fake_runner,
                    known_hosts_file=root / "known_hosts",
                ),
            )

            result = service.doctor(selected.host_id)
            checks = {check.check: check for check in result.checks}

            self.assertEqual(result.readiness, "not_ready")
            self.assertEqual(checks["gpu_memory"].status, "fail")
            self.assertEqual(checks["pcie_link"].status, "warn")

    def test_pcie_generation_downgrade_warns_at_full_width(self) -> None:
        selected = machine(Path("/tmp/id_ed25519"))
        inspection = FleetInspection(
            machine=selected,
            observed_at=datetime(2026, 8, 10, 12, 5, tzinfo=UTC),
            disk_free_gb=40,
            gpu_execution_status="pass",
            gpu_execution_detail="verified",
            gpus=(
                GpuDevice(
                    index=0,
                    name="NVIDIA H100 80GB HBM3",
                    memory_total_mb=81559,
                    driver_version="570.86.15",
                    temperature_c=31,
                    pcie_generation_current=4,
                    pcie_generation_max=5,
                    pcie_width_current=16,
                    pcie_width_max=16,
                ),
            ),
        )

        result = FleetService().doctor_inspection(inspection)
        checks = {check.check: check for check in result.checks}

        self.assertEqual(result.readiness, "degraded")
        self.assertEqual(checks["pcie_link"].status, "warn")

    def test_imported_host_does_not_require_an_allocation(self) -> None:
        imported = machine(Path("/tmp/id_ed25519"), allocation_id=None)

        self.assertIsNone(imported.allocation_id)
        self.assertEqual(imported.row()["host_id"], "runpod:pod-123")


if __name__ == "__main__":
    unittest.main()
