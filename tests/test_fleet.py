from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from the_compute_bazaar.fleet import (
    FleetInspector,
    FleetMachine,
    FleetRegistry,
    FleetService,
    SshEndpoint,
)


def machine(identity_file: Path) -> FleetMachine:
    created_at = datetime(2026, 8, 10, 12, tzinfo=UTC)
    return FleetMachine(
        host_id="runpod:pod-123",
        provider="runpod",
        provider_resource_id="pod-123",
        name="bazaar-h100-01",
        state="running",
        gpu_model="H100_80GB",
        gpu_count=1,
        price_usd_gpu_hr=2.49,
        price_usd_instance_hr=2.49,
        created_at=created_at,
        terminate_at=created_at + timedelta(minutes=30),
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
CBZ\tcuda_version\tCuda compilation tools, release 12.8
CBZ\tdocker_version\tDocker version 27.0.0
CBZ_GPU_BEGIN
0, NVIDIA H100 80GB HBM3, 81559, 120, 14, 80.2, 310, 31, 47, 570.86.15, P0, 00000000:01:00.0, 4, 16
CBZ_GPU_END
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
            calls: list[list[str]] = []

            def fake_runner(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, PROBE_OUTPUT, "")

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
            self.assertEqual(inspection.cpu_count, 13.6)
            self.assertEqual(result.readiness, "ready")
            self.assertIn("StrictHostKeyChecking=accept-new", calls[0])
            self.assertIn("ControlMaster=auto", calls[0])


if __name__ == "__main__":
    unittest.main()
