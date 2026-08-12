from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import ValidationError

from the_compute_bazaar.data_catalog import ComputeBazaarCatalog
from the_compute_bazaar.data_sync import inspect_lake, sync_public_lake
from the_compute_bazaar.offers import OfferService
from the_compute_bazaar.operations import OperationalLedger
from the_compute_bazaar.portable_lake import build_portable_lake
from the_compute_bazaar.prices.datafusion import DataFusionEngine
from the_compute_bazaar.prices.gold import build_gold_market_tables
from the_compute_bazaar.prices.gold_manifest import read_latest_gold_manifest
from the_compute_bazaar.prices.ingestion import persist_provider_snapshot
from the_compute_bazaar.prices.offer_reference import (
    build_prime_frontier_offer_events,
)
from the_compute_bazaar.prices.schemas import OfferObservation
from the_compute_bazaar.prices.silver_contract import silver_observation_select
from the_compute_bazaar.prices.storage import write_offer_observations_parquet
from the_compute_bazaar.terminal.virtual_table import (
    DataFusionVirtualTable,
    VirtualDataRequest,
    VirtualViewConfig,
)


class DataFusionEngineTest(unittest.TestCase):
    def test_prime_empty_snapshot_records_departures(self) -> None:
        first = datetime(2026, 8, 10, 12, tzinfo=UTC)
        second = datetime(2026, 8, 10, 13, tzinfo=UTC)
        history = [
            {
                "listing_id": "prime-h200-1",
                "provider": "verda",
                "source_offer_id": "prime-h200-1",
                "gpu_model": "H200_141GB",
                "source_connector": "prime_intellect",
                "gpu_count": 8,
                "price_usd_gpu_hr": 3.95,
                "is_spot": False,
                "is_secure": True,
                "source_availability_status": "available",
                "observed_at": first,
                "gold_run_id": "gold-1",
                "gold_observed_at": first,
            }
        ]

        events = build_prime_frontier_offer_events(
            history,
            snapshot_keys=[(first, "gold-1"), (second, "gold-2")],
        )

        self.assertEqual(
            [(row["gold_run_id"], row["event_type"]) for row in events],
            [("gold-1", "entered"), ("gold-2", "left_availability")],
        )

    def test_prime_events_treat_one_gold_run_as_one_snapshot(self) -> None:
        observed_at = datetime(2026, 8, 10, 12, tzinfo=UTC)
        history = [
            {
                "listing_id": "prime-h200-1",
                "provider": "verda",
                "source_offer_id": "prime-h200-1",
                "gpu_model": "H200_141GB",
                "source_connector": "prime_intellect",
                "gpu_count": 8,
                "price_usd_gpu_hr": 3.95,
                "is_spot": False,
                "is_secure": True,
                "source_availability_status": "available",
                "observed_at": observed_at,
                "gold_run_id": "gold-1",
                "gold_observed_at": observed_at,
            }
        ]

        events = build_prime_frontier_offer_events(
            history,
            snapshot_keys=[(datetime(2026, 8, 10, 12, 5, tzinfo=UTC), "gold-1")],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "entered")
        self.assertEqual(events[0]["observed_at"], "2026-08-10T12:05:00+00:00")

    def test_gold_history_appends_immutable_run_parts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lake = root / "lake"
            for run, hour, price in (("1", 12, 2.5), ("2", 13, 2.75)):
                observed_at = datetime(2026, 8, 10, hour, tzinfo=UTC)
                persist_provider_snapshot(
                    provider="vast",
                    run_id=f"vast-market-{run}",
                    trace_id=f"market-{run}",
                    observed_at=observed_at,
                    lake_root=str(lake),
                    raw_ref=str(root / "raw" / f"vast-{run}.json"),
                    raw_payload={"provider": "vast", "offers": 1},
                    raw_offer_count=1,
                    normalized=[
                        OfferObservation(
                            provider="vast",
                            source_offer_id="vast-h100",
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
                    providers=["vast"],
                    run_id=f"gold-market-{run}",
                    calculated_at=observed_at.isoformat(),
                    manifest_observed_at=observed_at.isoformat(),
                )
                history_refs = gold.table_refs["fact_gpu_price_index_history"]
                self.assertIsInstance(history_refs, list)
                self.assertEqual(len(history_refs), int(run))
                if run == "1":
                    first_ref = history_refs[0]
                    first_payload = Path(first_ref).read_bytes()

            self.assertEqual(Path(first_ref).read_bytes(), first_payload)
            self.assertEqual(gold.row_counts["fact_gpu_price_index_history"], 2)
            rows = DataFusionEngine(
                {"history": gold.table_refs["fact_gpu_price_index_history"]}
            ).query("select * from history order by gold_observed_at")
            self.assertEqual([row["benchmark_usd_gpu_hr"] for row in rows], [2.5, 2.75])

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

    def test_catalog_reports_truncation_only_when_more_rows_exist(self) -> None:
        catalog = object.__new__(ComputeBazaarCatalog)
        catalog.engine = DataFusionEngine()
        catalog.engine.register_arrow_table("numbers", pa.table({"value": [1, 2, 3]}))

        bounded, selected_limit, has_more = catalog.query_arrow(
            "select * from numbers order by value", limit=2
        )
        exact, _, exact_has_more = catalog.query_arrow(
            "select * from numbers where value < 3 order by value", limit=2
        )

        self.assertEqual(bounded.column("value").to_pylist(), [1, 2])
        self.assertEqual(selected_limit, 2)
        self.assertTrue(has_more)
        self.assertEqual(exact.column("value").to_pylist(), [1, 2])
        self.assertFalse(exact_has_more)

    def test_virtual_availability_uses_datafusion_for_viewports(self) -> None:
        catalog = object.__new__(ComputeBazaarCatalog)
        catalog.manifest = {"run_id": "gold-test", "observed_at": None}
        catalog.engine = DataFusionEngine()
        catalog.engine.register_arrow_table(
            "availability",
            pa.table(
                {
                    "observation_id": ["obs-1", "obs-2", "obs-3"],
                    "observed_at": [
                        datetime(2026, 8, 10, hour, tzinfo=UTC) for hour in (10, 11, 12)
                    ],
                    "source_connector": [
                        "prime_intellect",
                        "runpod",
                        "prime_intellect",
                    ],
                    "available_units": [3, 4, 7],
                    "signed_metric": [-4, 2, -7],
                    "observed_date": [date(2026, 8, day) for day in (9, 10, 11)],
                }
            ),
        )
        catalog.engine.create_schema("gold")
        catalog.engine.create_view(
            "gold",
            "fact_gpu_availability_history",
            "select * from availability",
        )
        virtual = DataFusionVirtualTable(catalog)
        config = VirtualViewConfig(
            filter=[("source_connector", "==", "prime_intellect")],
            sort=[("available_units", "desc")],
        )

        self.assertEqual(virtual.size(config), 2)
        self.assertEqual(virtual.schema()["observed_at"], "datetime")
        viewport = virtual.data(
            VirtualDataRequest.model_validate(
                {
                    **config.model_dump(),
                    "columns": ["observation_id", "available_units"],
                    "start_row": 1,
                    "end_row": 2,
                }
            )
        )

        self.assertEqual(
            viewport.to_pylist(),
            [{"observation_id": "obs-1", "available_units": 3}],
        )
        absolute = virtual.data(
            VirtualDataRequest(
                columns=["observation_id", "signed_metric"],
                sort=[("signed_metric", "desc abs")],
                start_row=0,
                end_row=3,
            )
        )
        self.assertEqual(
            [row["observation_id"] for row in absolute.to_pylist()],
            ["obs-3", "obs-1", "obs-2"],
        )
        self.assertEqual(
            virtual.size(
                VirtualViewConfig(
                    filter=[
                        (
                            "observed_at",
                            ">=",
                            int(
                                datetime(2026, 8, 10, 11, tzinfo=UTC).timestamp() * 1000
                            ),
                        )
                    ]
                )
            ),
            2,
        )
        self.assertEqual(
            virtual.size(
                VirtualViewConfig(filter=[("observed_date", ">=", "2026-08-10")])
            ),
            2,
        )
        self.assertEqual(
            virtual.size(VirtualViewConfig(sort=[("available_units", "none")])),
            3,
        )
        with self.assertRaises(ValidationError):
            VirtualViewConfig.model_validate(
                {"table": "gold.fact_gpu_availability_history", "unknown": True}
            )
        with self.assertRaisesRegex(ValueError, "256"):
            virtual.size(
                VirtualViewConfig(filter=[("available_units", "in", list(range(257)))])
            )
        with self.assertRaisesRegex(ValueError, "flat views"):
            virtual.size(VirtualViewConfig(group_by=["source_connector"]))
        with self.assertRaisesRegex(ValueError, "2,000"):
            virtual.data(VirtualDataRequest(start_row=0, end_row=2_001))


if __name__ == "__main__":
    unittest.main()
