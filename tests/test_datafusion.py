from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
from the_compute_bazaar.prices.publication_chart_common import (
    _shape_preserving_curve,
    _smooth_observation_values,
)
from the_compute_bazaar.prices.publication_profiles import (
    GPU_PUBLICATION_RENDER_PROFILE,
)
from the_compute_bazaar.prices.publication_store import (
    _publication_digest,
    _renderer_revision,
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
    def test_publication_curve_rounds_turns_without_overshooting(self) -> None:
        dates = [
            datetime(2026, 8, 10, hour, tzinfo=UTC)
            for hour in (10, 11, 12, 13)
        ]
        values = [3.25, 2.4, 3.25, 3.2]

        smooth_dates, smooth_values = _shape_preserving_curve(dates, values)

        self.assertEqual(smooth_dates[0], dates[0])
        self.assertEqual(smooth_dates[-1], dates[-1])
        self.assertEqual(smooth_values[0], values[0])
        self.assertEqual(smooth_values[-1], values[-1])
        self.assertGreater(len(smooth_values), len(values))
        self.assertGreaterEqual(min(smooth_values), min(values))
        self.assertLessEqual(max(smooth_values), max(values))

    def test_publication_smoothing_keeps_endpoints_and_softens_spikes(self) -> None:
        values = [3.2, 3.2, 4.4, 3.2, 3.2]

        smoothed = _smooth_observation_values(values)

        self.assertEqual(smoothed[-1], values[-1])
        self.assertLess(smoothed[2], values[2])
        self.assertGreater(smoothed[2], values[1])

    def test_publication_digest_is_profile_specific_not_commit_specific(self) -> None:
        cards = {"H100": {"as_of": "2026-08-13T12:00:00+00:00", "series": []}}
        original_revision = os.environ.get("COMPUTE_BAZAAR_REVISION")
        try:
            os.environ["COMPUTE_BAZAAR_REVISION"] = "a" * 40
            first = _publication_digest(
                cards,
                public_base_url="https://bazaar.example",
                article_url="https://example.test/article",
                render_profile=GPU_PUBLICATION_RENDER_PROFILE,
            )
            os.environ["COMPUTE_BAZAAR_REVISION"] = "b" * 40
            second = _publication_digest(
                cards,
                public_base_url="https://bazaar.example",
                article_url="https://example.test/article",
                render_profile=GPU_PUBLICATION_RENDER_PROFILE,
            )
        finally:
            if original_revision is None:
                os.environ.pop("COMPUTE_BAZAAR_REVISION", None)
            else:
                os.environ["COMPUTE_BAZAAR_REVISION"] = original_revision

        self.assertEqual(first, second)

    def test_publication_records_worker_revision(self) -> None:
        original_revision = os.environ.get("COMPUTE_BAZAAR_REVISION")
        try:
            os.environ["COMPUTE_BAZAAR_REVISION"] = "e8d5744"
            self.assertEqual(_renderer_revision(), "e8d5744")
        finally:
            if original_revision is None:
                os.environ.pop("COMPUTE_BAZAAR_REVISION", None)
            else:
                os.environ["COMPUTE_BAZAAR_REVISION"] = original_revision

    def test_embedded_worker_revision_wins_over_job_environment(self) -> None:
        with (
            patch("the_compute_bazaar.build_info.BUILD_REVISION", "a" * 40),
            patch.dict(os.environ, {"COMPUTE_BAZAAR_REVISION": "b" * 40}),
        ):
            self.assertEqual(_renderer_revision(), "a" * 40)

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
            portable = root / "portable"
            cache = root / "cache"
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

                build_portable_lake(
                    source_lake_root=str(lake),
                    output_root=str(portable),
                )
                portable_manifest = read_latest_gold_manifest(str(portable))
                portable_refs = portable_manifest["table_refs"][
                    "fact_gpu_price_index_history"
                ]
                self.assertIsInstance(portable_refs, list)
                self.assertEqual(len(portable_refs), int(run))
                index = json.loads((portable / "index.json").read_text())
                sync = sync_public_lake(
                    base_url=portable.as_uri(),
                    output_root=str(cache),
                )
                if run == "1":
                    first_portable_path = (
                        Path(portable_refs[0]).resolve().relative_to(portable.resolve())
                    )
                    first_portable_payload = Path(portable_refs[0]).read_bytes()
                    first_inventory = {
                        item["path"]: item["sha256"] for item in index["files"]
                    }
                    self.assertEqual(
                        sync["downloaded_bytes"],
                        sum(item["size"] for item in index["files"]),
                    )
                else:
                    self.assertEqual(
                        Path(portable_refs[0])
                        .resolve()
                        .relative_to(portable.resolve()),
                        first_portable_path,
                    )
                    self.assertEqual(
                        Path(portable_refs[0]).read_bytes(), first_portable_payload
                    )
                    expected_download = sum(
                        item["size"]
                        for item in index["files"]
                        if first_inventory.get(item["path"]) != item["sha256"]
                    )
                    self.assertEqual(sync["downloaded_bytes"], expected_download)
                    self.assertLess(
                        sync["downloaded_bytes"],
                        sum(item["size"] for item in index["files"]),
                    )

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
                    "resource_type": ["H100", "H100", "H200"],
                    "available_units": [3, 4, 7],
                    "signed_metric": [-4, 2, -7],
                    "stock_status": ["available", "available", "limited"],
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
        grouped = VirtualViewConfig(
            columns=["available_units"],
            filter=[("source_connector", "==", "prime_intellect")],
            sort=[("available_units", "desc")],
            group_by=["resource_type"],
            aggregates={"available_units": "sum"},
        )
        grouped_result = virtual.data(
            VirtualDataRequest.model_validate(
                {**grouped.model_dump(), "start_row": 0, "end_row": 10}
            )
        )
        self.assertEqual(
            grouped_result.schema.field("__ROW_PATH_0__").type, pa.string()
        )
        handwritten = catalog.engine.query_arrow(
            """
            select
              resource_type as "__ROW_PATH_0__",
              sum(available_units) as available_units
            from gold.fact_gpu_availability_history
            where source_connector = 'prime_intellect'
            group by resource_type
            order by available_units desc, "__ROW_PATH_0__" asc
            """
        )

        self.assertEqual(virtual.size(grouped), 2)
        self.assertEqual(grouped_result.to_pylist(), handwritten.to_pylist())
        self.assertEqual(
            grouped_result.to_pylist(),
            [
                {"__ROW_PATH_0__": "H200", "available_units": 7},
                {"__ROW_PATH_0__": "H100", "available_units": 3},
            ],
        )
        all_aggregates = VirtualViewConfig(
            columns=[
                "available_units",
                "signed_metric",
                "observation_id",
                "observed_at",
                "observed_date",
            ],
            sort=[("source_connector", "asc")],
            group_by=["source_connector"],
            aggregates={
                "available_units": "sum",
                "signed_metric": "avg",
                "observation_id": "count",
                "observed_at": "min",
                "observed_date": "max",
            },
        )
        all_aggregate_result = virtual.data(
            VirtualDataRequest.model_validate(
                {**all_aggregates.model_dump(), "start_row": 0, "end_row": 10}
            )
        )
        all_aggregate_expected = catalog.engine.query_arrow(
            """
            select
              source_connector as "__ROW_PATH_0__",
              sum(available_units) as available_units,
              avg(signed_metric) as signed_metric,
              count(observation_id) as observation_id,
              min(observed_at) as observed_at,
              max(observed_date) as observed_date
            from gold.fact_gpu_availability_history
            group by source_connector
            order by "__ROW_PATH_0__" asc
            """
        )
        self.assertEqual(
            all_aggregate_result.to_pylist(), all_aggregate_expected.to_pylist()
        )
        self.assertEqual(
            all_aggregate_result.schema.field("observed_at").type,
            pa.timestamp("ms", tz="UTC"),
        )
        flat_datetimes = virtual.data(
            VirtualDataRequest(columns=["observed_at"], start_row=0, end_row=1)
        )
        self.assertEqual(
            flat_datetimes.schema.field("observed_at").type,
            pa.timestamp("ms", tz="UTC"),
        )
        hidden_sort = VirtualViewConfig(
            columns=["observation_id"],
            group_by=["source_connector"],
            aggregates={"observation_id": "count", "available_units": "sum"},
            sort=[("available_units", "desc")],
        )
        hidden_sort_result = virtual.data(
            VirtualDataRequest.model_validate(
                {**hidden_sort.model_dump(), "start_row": 0, "end_row": 10}
            )
        )
        self.assertEqual(
            hidden_sort_result.to_pylist(),
            [
                {"__ROW_PATH_0__": "prime_intellect", "observation_id": 2},
                {"__ROW_PATH_0__": "runpod", "observation_id": 1},
            ],
        )
        group_keys_only = virtual.data(
            VirtualDataRequest(group_by=["source_connector"], start_row=0, end_row=10)
        )
        self.assertEqual(group_keys_only.column_names, ["__ROW_PATH_0__"])
        with self.assertRaisesRegex(ValueError, "numeric column"):
            virtual.size(
                VirtualViewConfig(
                    columns=["stock_status"],
                    group_by=["resource_type"],
                    aggregates={"stock_status": "avg"},
                )
            )
        with self.assertRaisesRegex(ValueError, "Split by"):
            virtual.size(VirtualViewConfig(split_by=["source_connector"]))
        with self.assertRaisesRegex(ValueError, "Expressions"):
            virtual.size(
                VirtualViewConfig(expressions={"double": "available_units * 2"})
            )
        with self.assertRaisesRegex(ValueError, "2,000"):
            virtual.data(VirtualDataRequest(start_row=0, end_row=2_001))


if __name__ == "__main__":
    unittest.main()
