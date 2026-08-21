from __future__ import annotations

import json
import tempfile
import unittest
from types import SimpleNamespace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from the_compute_bazaar.cli import app
from the_compute_bazaar.market import (
    MarketCatalog,
    MarketLake,
    MarketPipeline,
    SesterceLauncher,
    default_registry,
    publish_generation,
)
from the_compute_bazaar.fleet import FleetRegistry
from the_compute_bazaar.market.contracts import SourceRead
from the_compute_bazaar.market.sources.sesterce import SesterceSource


PAYLOAD = [
    {
        "gpuName": "H100",
        "gpuCount": 8,
        "nvlink": True,
        "deploymentType": "vm",
        "instanceId": "H100x8",
        "cloudInitAvailable": True,
        "cloud": {"_id": "cloud-1", "name": "Supplier One"},
        "configuration": {
            "ramGB": 940,
            "storageGB": 1000,
            "vCpu": 120,
            "vRamGB": 640,
            "os": ["ubuntu22.04_cuda12.2"],
            "interconnect": "pcie",
        },
        "hourlyPrice": 24.0,
        "availability": [
            {
                "region": "us-central-2",
                "name": "US, Central",
                "countryCode": "US",
                "available": True,
            },
            {
                "region": "eu-west-1",
                "name": "EU, West",
                "countryCode": "IE",
                "available": False,
            },
        ],
    },
    {
        "gpuName": "MYSTERY9000",
        "gpuCount": 1,
        "deploymentType": "baremetal",
        "instanceId": "MYSTERY9000x1",
        "cloud": {"_id": "cloud-2", "name": "Supplier Two"},
        "configuration": {"vRamGB": 72, "ramGB": 256, "vCpu": 32},
        "hourlyPrice": 2.0,
        "availability": [
            {
                "region": "no-oslo-1",
                "name": "NO, Oslo",
                "countryCode": "NO",
                "available": True,
            }
        ],
    },
]


class FakeSesterce(SesterceSource):
    payload = PAYLOAD

    def __init__(self) -> None:
        super().__init__("test")
        self.deleted: list[str] = []

    def read(self, *, observed_at=None) -> SourceRead:
        return SourceRead(
            source=self.name,
            endpoint=self.endpoint,
            parameters={},
            observed_at=observed_at or datetime(2026, 8, 13, 13, tzinfo=UTC),
            status_code=200,
            payload=self.payload,
            elapsed_ms=4.2,
            authentication="x-api-key",
        )

    def create_instance(self, payload):
        return {
            "_id": "instance-1",
            "name": payload["name"],
            "status": "active",
            "gpuModel": "H100",
            "gpuCount": 8,
            "hourlyPrice": 24,
            "ip": "192.0.2.10",
            "sshUser": "ubuntu",
            "sshPort": 22,
            "createdAt": "2026-08-13T13:01:00Z",
        }

    def get_instance(self, instance_id):
        return self.create_instance({"name": "h100-test"})

    def delete_instance(self, instance_id):
        self.deleted.append(instance_id)


class EmptySource(FakeSesterce):
    name = "empty"
    payload: list[object] = []


class HttpResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return b'{"message":"schema changed"}'


class MarketPipelineTest(unittest.TestCase):
    def test_local_refresh_keeps_cloud_services_out_of_the_run(self):
        result = SimpleNamespace(
            market_run_id="market-local-test",
            status="complete",
            successful_providers=["runpod"],
            failed_providers=[],
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "the_compute_bazaar.prices.market_run.run_market_hourly",
                return_value=result,
            ) as run:
                response = CliRunner().invoke(
                    app,
                    [
                        "--format",
                        "json",
                        "market",
                        "refresh",
                        "--provider",
                        "runpod",
                        "--output-root",
                        directory,
                    ],
                )

        self.assertEqual(response.exit_code, 0, response.output)
        self.assertEqual(json.loads(response.output)["rows"][0]["providers"], 1)
        run.assert_called_once_with(
            raw_root=str(Path(directory).resolve() / "raw"),
            lake_root=str(Path(directory).resolve() / "lake"),
            dashboard_output_root=str(Path(directory).resolve() / "public"),
            providers=["runpod"],
            minimum_successful_providers=1,
            automq_bootstrap_servers=None,
            run_id=None,
        )

    def test_registry_builds_sesterce_from_its_declared_credential(self):
        source = default_registry.build(
            "sesterce", environment={"SESTERCE_API_KEY": "test"}
        )

        self.assertEqual(source.name, "sesterce")

    def test_sesterce_rejects_a_successful_non_list_response(self):
        source = SesterceSource("test")
        with patch(
            "the_compute_bazaar.market.sources.sesterce.urlopen",
            return_value=HttpResponse(),
        ):
            read = source.read(observed_at=datetime(2026, 8, 13, 12, tzinfo=UTC))

        self.assertFalse(read.complete)
        self.assertEqual(read.payload, {"message": "schema changed"})
        self.assertEqual(read.error, "Sesterce returned an invalid offers response")

        with tempfile.TemporaryDirectory() as directory:
            result = MarketPipeline(MarketLake(directory)).record(
                source,
                read,
                source_run_id="sesterce-malformed",
            )
            self.assertEqual(result.run.status, "failed")
            raw = json.loads(Path(result.run.raw_ref).read_text())
            self.assertEqual(raw["response"]["payload"], read.payload)

    def test_sesterce_reaches_bronze_and_silver_without_losing_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            result = MarketPipeline(MarketLake(directory)).run(
                FakeSesterce(),
                observed_at=datetime(2026, 8, 13, 12, tzinfo=UTC),
                source_run_id="sesterce-test",
            )

            self.assertEqual(result.run.status, "complete")
            self.assertEqual(result.run.source_offer_count, 2)
            self.assertEqual(result.run.silver_row_count, 2)
            self.assertTrue(Path(result.run.raw_ref).is_file())
            self.assertTrue(Path(result.run.silver_ref).is_file())
            manifest = json.loads(Path(result.run.manifest_ref).read_text())
            self.assertEqual(manifest["silver_row_count"], 2)

            available, unavailable = result.offers
            self.assertEqual(available.gpu_model, "H100_80GB")
            self.assertEqual(available.source, "sesterce")
            self.assertEqual(available.intermediary, "sesterce")
            self.assertEqual(available.operator_id, "cloud-1")
            self.assertEqual(available.operator, "Supplier One")
            self.assertEqual(available.offer_id, "H100x8")
            self.assertEqual(available.ask_usd_hr, 3)
            self.assertFalse(unavailable.available)
            self.assertEqual(result.run.rejected[-1].reason, "not a VM offer")

            catalog = MarketCatalog.from_runs(result)
            rows = catalog.rows("""
select
  gpu_model,
  min(ask_usd_hr) as lowest_ask_usd_hr,
  count(*) as listing_count
from silver.gpu_offers
where available and gpu_model is not null
group by gpu_model
order by gpu_model
""")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["gpu_model"], "H100_80GB")
            self.assertEqual(rows[0]["listing_count"], 1)
            self.assertEqual(rows[0]["lowest_ask_usd_hr"], 3)

            empty = MarketPipeline(MarketLake(directory)).run(
                EmptySource(),
                observed_at=datetime(2026, 8, 13, 12, 1, tzinfo=UTC),
                source_run_id="empty-test",
            )
            self.assertEqual(empty.run.status, "complete")
            self.assertEqual(empty.run.silver_row_count, 0)
            self.assertTrue(Path(empty.run.silver_ref).is_file())
            self.assertEqual(
                MarketCatalog.from_runs(empty).rows(
                    "select count(*) as count from silver.gpu_offers"
                )[0]["count"],
                0,
            )

            generation = publish_generation(MarketLake(directory), result, empty)
            self.assertEqual(generation["tables"], ["silver.gpu_offers"])
            self.assertEqual(generation["sources"], ["empty", "sesterce"])
            reopened = MarketCatalog.from_lake(directory)
            self.assertEqual(
                reopened.tables()["run"]["source_runs"],
                {"empty": "empty-test", "sesterce": "sesterce-test"},
            )
            self.assertEqual(
                reopened.tables()["run"]["source_scope"], ["empty", "sesterce"]
            )
            self.assertEqual(
                [table["layer"] for table in reopened.tables()["tables"]],
                ["silver"],
            )
            payload = reopened.query(
                "select * from silver.gpu_offers",
                limit=1,
            )
            self.assertEqual(payload["row_count"], 1)
            self.assertTrue(payload["truncated"])
            index = json.loads((Path(directory) / "index.json").read_text())
            self.assertEqual(index["contract"], "compute_bazaar_market_lake")
            self.assertEqual(index["file_count"], len(index["files"]))

            registry = FleetRegistry(Path(directory) / "fleet")
            source = FakeSesterce()
            launcher = SesterceLauncher(
                lake_root=directory,
                source=source,
                registry=registry,
            )
            plan = launcher.plan(
                available.observation_id,
                name="h100-test",
                ssh_key_id="key-1",
            )
            self.assertEqual(plan.operator_id, "cloud-1")
            self.assertEqual(plan.total_usd_hr, 24)
            self.assertEqual(plan.request["cloudProvider"], "cloud-1")
            self.assertEqual(plan.request["instanceId"], "H100x8")
            self.assertEqual(plan.request["region"], "us-central-2")
            with self.assertRaisesRegex(ValueError, "--confirm"):
                launcher.launch(
                    available.observation_id,
                    name="h100-test",
                    ssh_key_id="key-1",
                    max_hourly_usd=24,
                    confirm=False,
                )
            launched_plan, machine = launcher.launch(
                available.observation_id,
                name="h100-test",
                ssh_key_id="key-1",
                max_hourly_usd=24,
                confirm=True,
            )
            self.assertEqual(machine.host_id, "sesterce:instance-1")
            self.assertIsNotNone(machine.allocation_id)
            self.assertIsNone(machine.source)
            self.assertIsNone(machine.source_offer_id)
            self.assertIsNone(machine.provider_resource_id)
            self.assertIsNone(machine.ask_usd_hr)
            self.assertEqual(machine.ssh.target, "ubuntu@192.0.2.10")
            self.assertEqual(registry.get(machine.host_id), machine)
            allocation = launcher.ledger.allocation_for_machine(machine)
            self.assertEqual(
                allocation["candidate_observation_id"], available.observation_id
            )
            self.assertEqual(
                allocation["preflight_observation_id"],
                launched_plan.live_observation_id,
            )
            self.assertEqual(allocation["source"], "sesterce")
            self.assertEqual(allocation["intermediary"], "sesterce")
            self.assertEqual(allocation["operator"], "Supplier One")
            self.assertEqual(allocation["offer_id"], "H100x8")
            self.assertEqual(allocation["source_resource_id"], "instance-1")
            self.assertEqual(allocation["price_usd_gpu_hr"], 3)
            self.assertEqual(allocation["price_usd_instance_hr"], 24)
            self.assertEqual(allocation["expected_max_cost_usd"], 12)
            self.assertIsNotNone(allocation["terminate_at"])
            self.assertNotEqual(plan.source_run_id, launched_plan.source_run_id)
            self.assertTrue(
                Path(
                    MarketLake(directory).silver_ref(
                        source="sesterce",
                        day=launched_plan.observed_at.date(),
                        source_run_id=launched_plan.source_run_id,
                    )
                ).is_file()
            )
            registry.put(
                machine.model_copy(update={"state": "provisioning", "ssh": None})
            )
            refreshed = launcher.refresh(machine.host_id)
            self.assertEqual(refreshed.state, "running")
            self.assertEqual(refreshed.ssh.target, "ubuntu@192.0.2.10")
            with self.assertRaisesRegex(ValueError, "--confirm"):
                launcher.terminate(machine.host_id, confirm=False)
            terminated = launcher.terminate(machine.host_id, confirm=True)
            self.assertEqual(terminated.state, "terminated")
            self.assertIsNone(terminated.ssh)
            self.assertEqual(source.deleted, ["instance-1"])


if __name__ == "__main__":
    unittest.main()
