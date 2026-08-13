from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from the_compute_bazaar.market import (
    MarketCatalog,
    MarketLake,
    MarketPipeline,
    default_registry,
    publish_generation,
)
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
    def __init__(self) -> None:
        super().__init__("test")

    def read(self, *, observed_at=None) -> SourceRead:
        return SourceRead(
            source="sesterce",
            endpoint=self.endpoint,
            parameters={},
            observed_at=observed_at,
            status_code=200,
            payload=PAYLOAD,
            elapsed_ms=4.2,
        )


class MarketPipelineTest(unittest.TestCase):
    def test_registry_builds_sesterce_from_its_declared_credential(self):
        source = default_registry.build(
            "sesterce", environment={"SESTERCE_API_KEY": "test"}
        )

        self.assertEqual(source.name, "sesterce")

    def test_sesterce_reaches_bronze_and_silver_without_losing_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            result = MarketPipeline(MarketLake(directory)).run(
                FakeSesterce(),
                observed_at=datetime(2026, 8, 13, 12, tzinfo=UTC),
                run_id="sesterce-test",
            )

            self.assertEqual(result.run.status, "complete")
            self.assertEqual(result.run.source_offer_count, 2)
            self.assertEqual(result.run.silver_row_count, 3)
            self.assertTrue(Path(result.run.raw_ref).is_file())
            self.assertTrue(Path(result.run.silver_ref).is_file())
            manifest = json.loads(Path(result.run.manifest_ref).read_text())
            self.assertEqual(manifest["silver_row_count"], 3)

            available, unavailable, unknown = result.offers
            self.assertEqual(available.gpu_model, "H100_80GB")
            self.assertEqual(available.gpu_vram_gb, 80)
            self.assertEqual(available.marketplace, "sesterce")
            self.assertEqual(available.provider_name, "Supplier One")
            self.assertEqual(available.ask_usd_gpu_hr, 3)
            self.assertFalse(unavailable.available)
            self.assertIsNone(unknown.gpu_model)

            catalog = MarketCatalog.from_runs(result)
            rows = catalog.rows("""
select
  gpu_model,
  min(ask_usd_gpu_hr) as best_ask_usd_gpu_hr,
  count(distinct provider_id) as provider_count,
  count(*) as listing_count
from silver.gpu_offers
where available and gpu_model is not null
group by gpu_model
order by gpu_model
""")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["gpu_model"], "H100_80GB")
            self.assertEqual(rows[0]["listing_count"], 1)
            self.assertEqual(rows[0]["best_ask_usd_gpu_hr"], 3)
            self.assertEqual(rows[0]["provider_count"], 1)

            generation = publish_generation(MarketLake(directory), result)
            self.assertEqual(generation["tables"], ["silver.gpu_offers"])
            reopened = MarketCatalog.from_lake(directory)
            self.assertEqual(reopened.tables()["run"]["run_id"], "sesterce-test")
            self.assertEqual(
                [table["layer"] for table in reopened.tables()["tables"]],
                ["silver"],
            )
            payload = reopened.query(
                "select * from silver.gpu_offers where available",
                limit=1,
            )
            self.assertEqual(payload["row_count"], 1)
            self.assertTrue(payload["truncated"])
            index = json.loads((Path(directory) / "index.json").read_text())
            self.assertEqual(index["contract"], "compute_bazaar_market_lake")
            self.assertEqual(index["file_count"], len(index["files"]))


if __name__ == "__main__":
    unittest.main()
