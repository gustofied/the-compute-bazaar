from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from the_compute_bazaar.data_catalog import _market_to_fleet_sql
from the_compute_bazaar.fleet import FleetRegistry, FleetService
from the_compute_bazaar.fleet.models import FleetInspection, GpuDevice
from the_compute_bazaar.offers import OfferService
from the_compute_bazaar.operations import OperationalLedger
from the_compute_bazaar.prices.datafusion import DataFusionEngine
from the_compute_bazaar.provider_execution import RunpodExecutor
from the_compute_bazaar.provisioning import LaunchPlanner
from tests.test_offers import FakeRunpodClient


class OperationalLedgerTest(unittest.TestCase):
    def test_current_schema_is_initialized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "operations.sqlite3"
            ledger = OperationalLedger(path)
            with closing(ledger._connect()) as connection:
                version = connection.execute("pragma user_version").fetchone()[0]
                tables = {
                    row[0]
                    for row in connection.execute(
                        "select name from sqlite_master where type='table'"
                    )
                }

            self.assertEqual(version, 8)
            self.assertIn("offer_observations", tables)
            self.assertIn("allocations", tables)
            self.assertIn("capacity_verifications", tables)

    def test_concurrent_initialization_uses_one_current_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "operations.sqlite3"

            def initialize(_: int) -> int:
                ledger = OperationalLedger(path)
                with closing(ledger._connect()) as connection:
                    return int(connection.execute("pragma user_version").fetchone()[0])

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                versions = list(executor.map(initialize, range(16)))

            self.assertEqual(versions, [8] * 16)

    def test_unsupported_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "operations.sqlite3"
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("pragma user_version=7")

            with self.assertRaisesRegex(
                RuntimeError,
                "Unsupported Fleet database schema 7; expected 8",
            ):
                OperationalLedger(path)

    def test_market_selection_and_fleet_delivery_join_in_datafusion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = FleetRegistry(root / "fleet")
            ledger = OperationalLedger(root / "operations.sqlite3", registry=registry)
            service = OfferService(
                runpod_api_key="configured",
                runpod_client=FakeRunpodClient(),
                ledger=ledger,
            )
            offer = next(
                row
                for row in service.list_offers(providers=["runpod"]).observations
                if row.cloud_type == "secure"
            )
            plan = LaunchPlanner(service).plan(
                offer.source_offer_id,
                name="fleet-h100-01",
                image="runpod/pytorch:latest",
            )
            identity = root / "id_ed25519"
            identity.write_text("test", encoding="utf-8")

            def fake_runner(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                payload = (
                    {"id": "pod-123", "desiredStatus": "RUNNING"}
                    if command[1:3] == ["pod", "create"]
                    else {
                        "id": "pod-123",
                        "ip": "203.0.113.10",
                        "port": 22123,
                        "ssh_command": "ssh root@203.0.113.10 -p 22123",
                    }
                )
                return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

            receipt = RunpodExecutor(
                api_key="configured",
                registry=registry,
                runner=fake_runner,
                identity_file=str(identity),
                ledger=ledger,
            ).execute(
                plan,
                runtime_minutes=30,
                max_hourly_usd=3,
                confirm_spend=True,
            )
            selected = receipt.machine
            sibling = selected.model_copy(
                update={
                    "host_id": "runpod:pod-123/node-2",
                    "name": "fleet-h100-02",
                }
            )
            registry.put(sibling)

            inspection = FleetInspection(
                machine=selected,
                observed_at=datetime(2026, 8, 10, 12, 5, tzinfo=UTC),
                disk_free_gb=40,
                gpu_execution_status="pass",
                gpu_execution_detail="PyTorch CUDA tensor operation completed",
                gpus=(
                    GpuDevice(
                        index=0,
                        name="NVIDIA H100 80GB HBM3",
                        memory_total_mb=81559,
                        driver_version="570.86.15",
                        temperature_c=31,
                        pcie_generation_current=4,
                        pcie_generation_max=4,
                        pcie_width_current=16,
                        pcie_width_max=16,
                    ),
                ),
            )
            doctor = FleetService().doctor_inspection(inspection)
            ledger.record_telemetry(inspection)
            telemetry = ledger.telemetry(selected.host_id)
            self.assertEqual(telemetry[0]["host_id"], selected.host_id)
            self.assertEqual(telemetry[0]["observed_at"], "2026-08-10T12:05:00+00:00")

            before_rows = _query_delivery_facts(ledger)
            self.assertEqual(len(before_rows), 2)
            before_verification = next(
                row for row in before_rows if row["host_id"] == selected.host_id
            )
            self.assertIsNone(before_verification["latest_readiness"])
            self.assertIsNone(before_verification["first_ready_at"])

            ledger.record_capacity_verification(inspection, doctor)
            delivered = next(
                row
                for row in _query_delivery_facts(ledger)
                if row["host_id"] == selected.host_id
            )

            self.assertEqual(delivered["latest_readiness"], "ready")
            self.assertEqual(delivered["verification_count"], 1)
            self.assertEqual(delivered["benchmark_usd_gpu_hr"], 2.0)
            self.assertAlmostEqual(delivered["selected_vs_benchmark_pct"], 24.5)
            self.assertEqual(
                delivered["candidate_observation_id"], plan.candidate_observation_id
            )
            self.assertEqual(
                delivered["preflight_observation_id"], plan.preflight_observation_id
            )


def _query_delivery_facts(ledger: OperationalLedger) -> list[dict[str, object]]:
    engine = DataFusionEngine()
    for name, table in ledger.arrow_tables().items():
        engine.register_arrow_table(f"_local_{name}", table)
    engine.create_schema("silver")
    engine.create_view(
        "silver",
        "offer_observations",
        "select * from _local_offer_observations",
    )
    engine.create_schema("fleet")
    for view, source in {
        "nodes": "fleet_nodes",
        "allocations": "allocations",
        "telemetry": "fleet_telemetry",
        "capacity_verifications": "capacity_verifications",
        "provisioning_requests": "provisioning_requests",
    }.items():
        engine.create_view("fleet", view, f"select * from _local_{source}")
    engine.create_schema("gold")
    benchmark = pa.Table.from_pylist(
        [
            {
                "benchmark_family_id": "H100",
                "benchmark_usd_gpu_hr": 2.0,
                "gold_observed_at": datetime(2026, 8, 10, 11, tzinfo=UTC),
            }
        ]
    )
    engine.register_arrow_table("_benchmark_history", benchmark)
    engine.create_view(
        "gold",
        "fact_gpu_price_index_history",
        "select * from _benchmark_history",
    )
    engine.create_view("gold", "fact_market_to_fleet", _market_to_fleet_sql())
    return engine.query("select * from gold.fact_market_to_fleet order by host_id")


if __name__ == "__main__":
    unittest.main()
