from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq

from the_compute_bazaar.data_catalog import ComputeBazaarCatalog
from the_compute_bazaar.data_sync import inspect_lake, sync_public_lake
from the_compute_bazaar.offers import OfferService
from the_compute_bazaar.operations import OperationalLedger
from the_compute_bazaar.portable_lake import build_portable_lake
from the_compute_bazaar.prices.datafusion import DataFusionEngine
from the_compute_bazaar.prices.gold import build_gold_market_tables
from the_compute_bazaar.prices.gold_manifest import read_latest_gold_manifest
from the_compute_bazaar.prices.ingestion import persist_provider_snapshot
from the_compute_bazaar.prices.schemas import OfferObservation
from the_compute_bazaar.prices.silver_contract import silver_observation_select
from the_compute_bazaar.prices.storage import write_offer_observations_parquet


class DataFusionEngineTest(unittest.TestCase):
    def test_offer_observation_contract_builds_gold_and_portable_lake(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lake = root / "lake"
            observed_at = datetime(2026, 8, 10, 12, tzinfo=UTC)
            for provider, price in (("vast", 2.5), ("lium", 3.0)):
                persist_provider_snapshot(
                    provider=provider,
                    run_id=f"{provider}-market-1",
                    trace_id="market-1",
                    observed_at=observed_at,
                    lake_root=str(lake),
                    raw_ref=str(root / "raw" / f"{provider}.json"),
                    raw_payload={"provider": provider, "offers": 1},
                    raw_offer_count=1,
                    normalized=[
                        OfferObservation(
                            provider=provider,
                            source_offer_id=f"{provider}-h100",
                            observed_at=observed_at,
                            gpu_raw_name="H100 SXM",
                            gpu_model="H100_80GB",
                            gpu_count=1,
                            vram_gb=80,
                            price_usd_instance_hr=price,
                        )
                    ],
                    unknown_gpu_names=[],
                    snapshot_query={"gpu_family": "H100"},
                    automq_bootstrap_servers=None,
                    automq_config=None,
                    topic_prefix="compute_bazaar.test",
                    dry_run=True,
                )

            gold = build_gold_market_tables(
                lake_root=str(lake),
                providers=["vast", "lium"],
                run_id="gold-market-1",
                calculated_at=observed_at.isoformat(),
                manifest_observed_at=observed_at.isoformat(),
            )
            for normalized_ref in gold.source_normalized_refs.values():
                self.assertIn("/silver/offer_observations/", normalized_ref)
                self.assertEqual(Path(normalized_ref).name, "observations.parquet")
                columns = set(pq.read_schema(normalized_ref).names)
                self.assertIn("price_usd_instance_hr", columns)
                self.assertIn("source_run_id", columns)
                self.assertNotIn("price_usd_hr", columns)
            portable = root / "portable"
            build_portable_lake(
                source_lake_root=str(lake),
                output_root=str(portable),
            )
            cache = root / "cache"
            first_sync = sync_public_lake(
                base_url=portable.as_uri(), output_root=str(cache)
            )
            repeat_sync = sync_public_lake(
                base_url=portable.as_uri(), output_root=str(cache)
            )
            self.assertEqual(first_sync["status"], "synced")
            self.assertGreater(first_sync["downloaded_bytes"], 0)
            self.assertEqual(repeat_sync["status"], "current")
            self.assertEqual(repeat_sync["downloaded_bytes"], 0)

            portable_manifest = read_latest_gold_manifest(str(portable))
            for normalized_ref in portable_manifest["source_normalized_refs"].values():
                table = pq.read_table(normalized_ref)
                pq.write_table(table.drop(["market_product_key"]), normalized_ref)
            index = json.loads((portable / "index.json").read_text())
            self.assertEqual(index["contract"], "compute_bazaar_market_lake")
            catalog = ComputeBazaarCatalog(lake_root=str(portable))

            observations = catalog.query(
                "select * from silver.offer_observations order by provider"
            )["rows"]
            benchmark = catalog.query(
                "select * from gold.fact_gpu_price_index where "
                "benchmark_family_id = 'H100'"
            )["rows"][0]

            self.assertEqual(gold.run_id, "gold-market-1")
            self.assertEqual(
                [row["provider"] for row in observations], ["lium", "vast"]
            )
            self.assertEqual(
                {row["market_run_id"] for row in observations}, {"market-1"}
            )
            self.assertEqual(
                {row["source_run_id"] for row in observations},
                {"lium-market-1", "vast-market-1"},
            )
            self.assertEqual(
                {row["market_product_key"] for row in observations}, {None}
            )
            self.assertEqual(benchmark["provider_count"], 2)

            class DirectRunpodClient:
                def fetch_live_market(self) -> SimpleNamespace:
                    return SimpleNamespace(
                        gpu_types=[
                            {
                                "id": "NVIDIA H100 80GB HBM3",
                                "displayName": "H100 PCIe",
                                "memoryInGb": 80,
                                "secureCloud": True,
                                "communityCloud": False,
                                "securePrice": 2.75,
                            }
                        ],
                        data_centers=[
                            {
                                "id": "EU-RO-1",
                                "gpuAvailability": [
                                    {
                                        "gpuTypeId": "NVIDIA H100 80GB HBM3",
                                        "stockStatus": "High",
                                    }
                                ],
                            }
                        ],
                    )

            ledger = OperationalLedger(root / "operations.sqlite3")
            OfferService(
                runpod_client=DirectRunpodClient(),
                ledger=ledger,
            ).list_offers(providers=["runpod"])
            combined = ComputeBazaarCatalog(
                lake_root=str(portable), operations=ledger
            ).query(
                """
select observation_purpose, count(*) as observation_count
from silver.offer_observations
group by observation_purpose
order by observation_purpose
"""
            )["rows"]

            self.assertEqual(
                combined,
                [
                    {"observation_purpose": "interactive", "observation_count": 1},
                    {"observation_purpose": "scheduled", "observation_count": 2},
                ],
            )
            self.assertEqual(
                inspect_lake(root=str(portable), kind="local", label="test")["status"],
                "ready",
            )
            index["contract"] = "retired_market_lake"
            (portable / "index.json").write_text(json.dumps(index))
            self.assertEqual(
                inspect_lake(root=str(portable), kind="local", label="test")["status"],
                "incompatible",
            )

            latest_manifest = lake / "_manifests" / "gold_market" / "latest.json"
            manifest = json.loads(latest_manifest.read_text())
            manifest["source_run_ids"].pop("vast")
            latest_manifest.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(
                RuntimeError, "incomplete provider lineage: vast"
            ):
                build_portable_lake(
                    source_lake_root=str(lake),
                    output_root=str(root / "incomplete"),
                )

    def test_scheduled_silver_keeps_market_and_connector_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parquet_path = Path(directory) / "observations.parquet"
            write_offer_observations_parquet(
                str(parquet_path),
                [
                    OfferObservation(
                        provider="vast",
                        source_offer_id="offer-1",
                        observed_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
                        gpu_raw_name="H100 SXM",
                        gpu_model="H100_80GB",
                        gpu_count=1,
                        vram_gb=80,
                        price_usd_instance_hr=2.5,
                        observation_id="obs-1",
                        batch_id="vast-market-1",
                        market_run_id="market-1",
                        source_run_id="vast-market-1",
                        source_manifest_ref="manifest.json",
                        source_normalized_ref="observations.parquet",
                    )
                ],
            )
            engine = DataFusionEngine({"source": str(parquet_path)})
            engine.create_schema("silver")
            engine.create_view(
                "silver",
                "offer_observations",
                silver_observation_select("source"),
            )

            row = engine.query("select * from silver.offer_observations")[0]

            self.assertEqual(row["market_run_id"], "market-1")
            self.assertEqual(row["source_run_id"], "vast-market-1")
            self.assertEqual(row["source_normalized_ref"], "observations.parquet")
            self.assertEqual(row["observation_purpose"], "scheduled")
            self.assertEqual(row["observation_resolution"], "market_summary")

    def test_query_arrow_accepts_datafusion_physical_string_views(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parquet_path = Path(directory) / "market.parquet"
            pq.write_table(
                pa.table(
                    {
                        "source_role": ["aggregator", "direct"],
                        "matching_direct_source": [True, False],
                        "exclusion_reason": [None, "not_available"],
                    }
                ),
                parquet_path,
            )
            engine = DataFusionEngine({"market": str(parquet_path)})

            result = engine.query_arrow(
                """
                select case
                    when source_role = 'aggregator' and matching_direct_source
                        then 'matching_direct_provider_source'
                    else exclusion_reason
                end as exclusion_reason
                from market
                order by source_role
                """
            )

            self.assertEqual(
                result.column("exclusion_reason").to_pylist(),
                ["matching_direct_provider_source", "not_available"],
            )

    def test_empty_query_retains_logical_schema(self) -> None:
        engine = DataFusionEngine()

        result = engine.query_arrow(
            "select cast(null as varchar) as reason where false"
        )

        self.assertEqual(result.num_rows, 0)
        self.assertEqual(result.column_names, ["reason"])
        reason_type = result.schema.field("reason").type
        self.assertTrue(
            pa.types.is_string(reason_type) or pa.types.is_string_view(reason_type)
        )


if __name__ == "__main__":
    unittest.main()
