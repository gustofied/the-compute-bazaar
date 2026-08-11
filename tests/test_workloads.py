from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from the_compute_bazaar.data_catalog import ComputeBazaarCatalog
from the_compute_bazaar.fleet import (
    FleetMachine,
    FleetRegistry,
    SshEndpoint,
    WorkloadService,
)
from the_compute_bazaar.operations import OperationalLedger
from the_compute_bazaar.prices.datafusion import DataFusionEngine


class WorkloadTest(unittest.TestCase):
    def test_remote_workload_lifecycle_is_durable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = FleetRegistry(root / "fleet")
            identity = root / "id_ed25519"
            identity.write_text("test", encoding="utf-8")
            machine = FleetMachine(
                host_id="runpod:pod-123",
                allocation_id="allocation-123",
                name="gpu-01",
                state="running",
                gpu_model="H100_80GB",
                gpu_count=1,
                created_at=datetime(2026, 8, 11, 8, tzinfo=UTC),
                ssh=SshEndpoint(
                    host="203.0.113.10",
                    port=22022,
                    user="root",
                    identity_file=str(identity),
                ),
            )
            registry.put(machine)
            ledger = OperationalLedger(root / "operations.sqlite3", registry=registry)
            finished = False
            stopped = False

            def fake_runner(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                nonlocal finished, stopped
                remote = command[-1]
                if "nohup setsid" in remote:
                    syntax = subprocess.run(
                        ["sh", "-n"],
                        input=remote,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(syntax.returncode, 0, syntax.stderr)
                    return subprocess.CompletedProcess(command, 0, "4242\n", "")
                if "CBZ_STDOUT_BEGIN" in remote:
                    self.assertIn("tail -c 1048576", remote)
                    output = (
                        "CBZ_STDOUT_BEGIN\nstep one\nstep two\n"
                        "CBZ_STDOUT_END\nCBZ_STDERR_BEGIN\nwarning\n"
                        "CBZ_STDERR_END\n"
                    )
                    return subprocess.CompletedProcess(command, 0, output, "")
                if "kill -TERM" in remote:
                    stopped = True
                    return subprocess.CompletedProcess(command, 0, "", "")
                if "exit_code" in remote and "kill -0" in remote:
                    output = "exit\t0\n" if finished else "running\t4242\n"
                    return subprocess.CompletedProcess(command, 0, output, "")
                raise AssertionError(f"Unexpected remote command: {remote}")

            service = WorkloadService(
                registry=registry,
                ledger=ledger,
                runner=fake_runner,
                known_hosts_file=root / "known_hosts",
            )

            running = service.start(
                machine.host_id,
                name="training",
                command=("python", "train.py", "--steps", "10"),
            )
            self.assertEqual(running.state, "running")
            self.assertEqual(running.remote_pid, 4242)
            self.assertEqual(service.inspect(running.workload_id).state, "running")

            finished = True
            completed = service.inspect(running.workload_id)
            logs = service.logs(running.workload_id, tail=10)

            self.assertEqual(completed.state, "succeeded")
            self.assertEqual(completed.exit_code, 0)
            self.assertEqual(logs["stdout"], "step one\nstep two")
            self.assertEqual(logs["stderr"], "warning")
            self.assertEqual(
                ledger.arrow_tables()["workload_runs"].to_pylist()[0]["state"],
                "succeeded",
            )

            second = service.start(
                machine.host_id,
                name="server",
                command=("python", "serve.py"),
            )
            stopped_run = service.stop(second.workload_id, confirm=True)

            self.assertTrue(stopped)
            self.assertEqual(stopped_run.state, "stopped")
            self.assertEqual(stopped_run.exit_code, 143)
            self.assertEqual(len(service.list(machine.host_id)), 2)

            third = service.start(
                machine.host_id,
                name="training-after-delete",
                command=("python", "train.py"),
            )
            stopped_count = ledger.stop_host_workloads(
                machine.host_id,
                reason="Fleet host terminated",
                ended_at=datetime(2026, 8, 11, 9, tzinfo=UTC),
            )
            closed = ledger.workload(third.workload_id)

            self.assertEqual(stopped_count, 1)
            self.assertEqual(closed.state, "stopped")
            self.assertEqual(closed.error, "Fleet host terminated")

            catalog = object.__new__(ComputeBazaarCatalog)
            catalog.operations = ledger
            catalog.engine = DataFusionEngine()
            catalog.engine.create_schema("silver")
            catalog._scheduled_offer_sql = (
                "select * from _local_offer_observations where false"
            )
            catalog._gold_tables = set()
            catalog._register_operations()
            rows = catalog.engine.query(
                "select name, state from fleet.workloads order by started_at"
            )

            self.assertEqual(
                rows,
                [
                    {"name": "training", "state": "succeeded"},
                    {"name": "server", "state": "stopped"},
                    {"name": "training-after-delete", "state": "stopped"},
                ],
            )


if __name__ == "__main__":
    unittest.main()
