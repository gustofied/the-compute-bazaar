from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from the_compute_bazaar.data_catalog import _market_to_fleet_sql
from the_compute_bazaar.fleet import FleetRegistry, FleetService
from the_compute_bazaar.fleet.models import FleetInspection, GpuDevice
from the_compute_bazaar.offers import OfferService
from the_compute_bazaar.operations import OperationalLedger
from the_compute_bazaar.prices.datafusion import DataFusionEngine
from the_compute_bazaar.provider_execution import LaunchReceipt
from the_compute_bazaar.provisioning import LaunchPlanner
from tests.test_fleet import machine
from tests.test_offers import FakeRunpodClient


class OperationalLedgerTest(unittest.TestCase):
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
            offer = service.list_offers(providers=["runpod"]).observations[0]
            plan = LaunchPlanner(service).plan(
                offer.source_offer_id,
                name="fleet-h100-01",
                image="runpod/pytorch:latest",
            )
            selected = machine(root / "id_ed25519")
            registry.put(selected)
            receipt = LaunchReceipt(
                machine=selected,
                plan_id=plan.plan_id,
                launched_at=selected.created_at,
                terminate_at=selected.terminate_at,
                max_hourly_usd=3,
                expected_max_cost_usd=1.245,
                command=("runpodctl",),
            )
            ledger.record_launch(plan, receipt)

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
            ledger.record_inspection(inspection, doctor)

            engine = DataFusionEngine()
            tables = ledger.arrow_tables()
            for name, table in tables.items():
                engine.register_arrow_table(f"_local_{name}", table)
            engine.create_schema("silver")
            engine.create_view(
                "silver",
                "offer_observations",
                "select * from _local_offer_observations",
            )
            engine.create_schema("fleet")
            for name in ("machines", "allocations", "observations"):
                engine.create_view(
                    "fleet",
                    name,
                    f"select * from _local_fleet_{name}",
                )
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
            engine.create_view(
                "gold",
                "fact_market_to_fleet",
                _market_to_fleet_sql(),
            )

            rows = engine.query("select * from gold.fact_market_to_fleet")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["latest_readiness"], "ready")
            self.assertEqual(rows[0]["benchmark_usd_gpu_hr"], 2.0)
            self.assertAlmostEqual(rows[0]["selected_vs_benchmark_pct"], 24.5)


if __name__ == "__main__":
    unittest.main()
