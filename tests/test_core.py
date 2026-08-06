from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from infra.windmill import market_hourly as windmill_market_hourly
from infra.aws.check_public_market import validate_public_market
from the_compute_bazaar.cli_output import render_table_payload
from the_compute_bazaar.data_root import resolve_lake_root
from the_compute_bazaar.market_query_service import MarketQueryService
from the_compute_bazaar.prices.datafusion import DataFusionEngine
from the_compute_bazaar.prices.gold import build_gold_market_tables
from the_compute_bazaar.prices.gold_exports import export_gold_dashboard_snapshot
from the_compute_bazaar.prices.gold_manifest import (
    gold_manifest_ref,
    list_gold_manifests,
)
from the_compute_bazaar.prices.gold_queries import query_gold_listings
from the_compute_bazaar.prices.ingestion import IngestResult, persist_provider_snapshot
from the_compute_bazaar.prices.market_run import (
    default_market_providers,
    run_market_hourly,
)
from the_compute_bazaar.prices.market_run_manifest import (
    _public_market_run_manifest,
)
from the_compute_bazaar.prices.market_catalog import MarketDataCatalog
from the_compute_bazaar.prices.provider_registry import (
    PROVIDERS,
    ProviderDefinition,
    ProviderRunContext,
)
from the_compute_bazaar.prices.providers.lium import normalize_executor
from the_compute_bazaar.prices.providers.vast import normalize_offer
from the_compute_bazaar.prices.schemas import GpuOffer
from the_compute_bazaar.prices.query_catalog import load_query_catalog
from the_compute_bazaar.prices.silver_contract import (
    GPU_OFFER_COLUMNS,
    silver_offer_select,
)
from the_compute_bazaar.prices.storage import (
    read_json,
    write_json,
    write_offers_parquet,
)
from the_compute_bazaar.publication_contract import PublicationRoute
from the_compute_bazaar.sandbox_cost import build_sandbox_cost
from the_compute_bazaar.api import create_app


OBSERVED_AT = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


class CoreTests(unittest.TestCase):
    def test_provider_registry_is_unique_and_callable(self) -> None:
        names = [provider.name for provider in PROVIDERS]

        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(callable(provider.ingester) for provider in PROVIDERS))
        self.assertTrue(all(provider.source_kind for provider in PROVIDERS))
        self.assertTrue(all(provider.observation_kind for provider in PROVIDERS))
        self.assertNotIn("published_rate_cards", names)

    def test_provider_adapter_owns_defaults_and_validates_identity(self) -> None:
        calls: dict[str, object] = {}

        def ingest_test(**kwargs: object) -> IngestResult:
            calls.update(kwargs)
            return IngestResult(
                provider="test_provider",
                run_id=str(kwargs["run_id"]),
                raw_ref="memory://raw/test.json",
                normalized_ref="memory://lake/test.parquet",
                raw_offer_count=1,
                normalized_offer_count=1,
                unknown_gpu_names=[],
                published_events=2,
                publish_mode="dry_run",
            )

        adapter = ProviderDefinition(
            "test_provider",
            ingest_test,
            "marketplace",
            "live_offer",
            default_options={"page_size": 100},
        )
        result = adapter.ingest(
            ProviderRunContext(
                market_run_id="market-test",
                raw_root="memory://raw",
                lake_root="memory://lake",
                automq_bootstrap_servers=None,
                automq_config={},
                topic_prefix="gpu",
                dry_run=True,
                provider_options={"test_provider": {"page_size": 250}},
            )
        )

        self.assertEqual(result.provider, "test_provider")
        self.assertEqual(calls["page_size"], 250)
        self.assertEqual(calls["run_id"], "test_provider-market-test")

    def test_windmill_calls_market_service_directly(self) -> None:
        self.assertNotIn("published_rate_cards", default_market_providers())
        result = Mock()
        result.to_dict.return_value = {"market_run_id": "market-direct"}
        previous_vast_key = os.getenv("VAST_API_KEY")

        with patch.object(
            windmill_market_hourly, "run_market_hourly", return_value=result
        ) as run_market:
            payload = windmill_market_hourly.main(
                provider_credentials_json=json.dumps(
                    {"VAST_API_KEY": "test-vast", "LIUM_API_KEY": "test-lium"}
                ),
                providers="vast,lium",
                raw_root="memory://raw",
                lake_root="memory://lake",
                dashboard_output_root="memory://dashboard",
                automq_bootstrap_servers="kafka.internal:9092",
                kafka_security_protocol="SASL_PLAINTEXT",
                kafka_sasl_mechanism="SCRAM-SHA-256",
                kafka_username="ingest",
                kafka_password="secret",
                dry_run=True,
            )

        self.assertEqual(payload, {"market_run_id": "market-direct"})
        run_market.assert_called_once()
        call = run_market.call_args.kwargs
        self.assertEqual(call["providers"], ["vast", "lium"])
        self.assertEqual(call["raw_root"], "memory://raw")
        self.assertEqual(call["lake_root"], "memory://lake")
        self.assertEqual(call["automq_config"]["sasl.username"], "ingest")
        self.assertEqual(os.getenv("VAST_API_KEY"), previous_vast_key)
        with self.assertRaisesRegex(ValueError, "Unknown provider credential"):
            windmill_market_hourly._provider_credentials('{"PATH": "/tmp/bad"}')

    def test_provider_offers_normalize_to_gpu_hour_records(self) -> None:
        vast = normalize_offer(
            {
                "id": "vast-h100",
                "gpu_name": "H100 SXM",
                "gpu_ram": 81920,
                "num_gpus": 1,
                "dph_total": 2.25,
                "rentable": True,
            },
            observed_at=OBSERVED_AT,
            raw_ref="raw/vast.json",
        )
        lium = normalize_executor(
            {
                "id": "lium-h100",
                "machine_name": "NVIDIA H100",
                "price_per_gpu": 1.25,
                "gpu_count": 2,
                "available_gpu_count": 2,
                "specs": {
                    "gpu": {
                        "count": 2,
                        "details": [{"name": "NVIDIA H100", "capacity": 81920}],
                    }
                },
            },
            observed_at=OBSERVED_AT,
            raw_ref="raw/lium.json",
        )

        self.assertEqual((vast.gpu_model, vast.price_usd_hr), ("H100_80GB", 2.25))
        self.assertEqual((lium.gpu_model, lium.price_usd_hr), ("H100_80GB_x2", 2.5))

    def test_ingestion_persists_raw_silver_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_ref = root / "raw" / "vast.json"
            result = persist_provider_snapshot(
                provider="vast",
                run_id="vast-market-test",
                trace_id="market-test",
                observed_at=OBSERVED_AT,
                lake_root=str(root / "lake"),
                raw_ref=str(raw_ref),
                raw_payload={"offers": [{"id": "vast-1"}]},
                raw_offer_count=1,
                normalized=[_offer(provider="vast", offer_id="vast-1", price=2.0)],
                unknown_gpu_names=[],
                snapshot_query={"source_type": "test_fixture"},
                automq_bootstrap_servers=None,
                automq_config=None,
                topic_prefix="gpu",
                dry_run=True,
            )

            manifest = read_json(str(result.manifest_ref))
            raw_payload = read_json(str(raw_ref))

        self.assertEqual(raw_payload, {"offers": [{"id": "vast-1"}]})
        self.assertEqual(result.normalized_offer_count, 1)
        self.assertEqual(result.published_events, 2)
        self.assertEqual(result.publish_mode, "dry_run")
        self.assertEqual(manifest["raw_ref"], str(raw_ref))
        self.assertEqual(manifest["normalized_ref"], result.normalized_ref)

    def test_partial_provider_cohort_publishes_warning_gold(self) -> None:
        successful = IngestResult(
            provider="vast",
            run_id="vast-market-test",
            raw_ref="memory://raw/vast.json",
            normalized_ref="memory://lake/vast.parquet",
            raw_offer_count=1,
            normalized_offer_count=1,
            unknown_gpu_names=[],
            published_events=1,
            publish_mode="dry-run",
        )
        with (
            patch(
                "the_compute_bazaar.prices.market_run._ingest_market_provider",
                side_effect=[successful, RuntimeError("provider unavailable")],
            ),
            patch(
                "the_compute_bazaar.prices.market_run.build_gold_market_tables"
            ) as build_gold,
            patch(
                "the_compute_bazaar.prices.market_run.export_gold_dashboard_snapshot"
            ) as export_dashboard,
            patch(
                "the_compute_bazaar.prices.market_run.query_frontier_coverage_ref",
                return_value=[],
            ),
            patch(
                "the_compute_bazaar.prices.market_run.read_json",
                return_value={"card_id": "test"},
            ),
            patch("the_compute_bazaar.prices.market_run.write_json"),
            patch(
                "the_compute_bazaar.prices.market_run.write_market_run_manifest",
                return_value="memory://market-run.json",
            ),
            patch(
                "the_compute_bazaar.prices.market_run.write_dashboard_market_run_snapshots"
            ),
        ):
            build_gold.return_value = Mock(
                run_id="gold-market-test",
                manifest_ref="memory://gold-manifest.json",
                table_refs={"fact_gpu_listings": "memory://listings.parquet"},
                row_counts={
                    "fact_gpu_listings": 1,
                    "dim_gpu_products": 1,
                    "fact_gpu_price_index": 1,
                    "fact_gpu_price_index_constituents": 1,
                    "fact_compute_market_state": 1,
                },
            )
            export_dashboard.return_value = {
                "output_refs": {
                    "market_overview": "memory://market-overview.json",
                    **{
                        f"gpu_benchmark_{family}": f"memory://{family}.json"
                        for family in ("h100", "h200", "b200", "b300")
                    },
                }
            }
            result = run_market_hourly(
                providers=["vast", "lium"],
                raw_root="memory://raw",
                lake_root="memory://lake",
                dashboard_output_root="memory://dashboard",
                dry_run=True,
            )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.successful_providers, ["vast"])
        self.assertEqual(result.failed_providers, ["lium"])
        build_gold.assert_called_once()
        self.assertEqual(build_gold.call_args.kwargs["providers"], ["vast"])
        self.assertEqual(
            result.data_quality["cohort"],
            {
                "required_providers": [],
                "optional_providers": ["vast", "lium"],
                "minimum_successful_providers": 1,
                "missing_required_providers": [],
                "status": "degraded",
            },
        )

    def test_missing_required_provider_is_recorded_without_replacing_latest(
        self,
    ) -> None:
        successful = IngestResult(
            provider="vast",
            run_id="vast-market-test",
            raw_ref="memory://raw/vast.json",
            normalized_ref="memory://lake/vast.parquet",
            raw_offer_count=1,
            normalized_offer_count=1,
            unknown_gpu_names=[],
            published_events=1,
            publish_mode="dry-run",
        )
        with (
            patch(
                "the_compute_bazaar.prices.market_run._ingest_market_provider",
                side_effect=[
                    successful,
                    RuntimeError("lium unavailable"),
                ],
            ),
            patch(
                "the_compute_bazaar.prices.market_run.write_market_run_manifest",
                return_value="memory://failed-market-run.json",
            ) as write_manifest,
            patch(
                "the_compute_bazaar.prices.market_run.build_gold_market_tables"
            ) as build_gold,
        ):
            with self.assertRaisesRegex(RuntimeError, "publication policy"):
                run_market_hourly(
                    providers=["vast", "lium"],
                    required_providers=["lium"],
                    minimum_successful_providers=1,
                    raw_root="memory://raw",
                    lake_root="memory://lake",
                    dashboard_output_root="memory://dashboard",
                    dry_run=True,
                )

        build_gold.assert_not_called()
        write_manifest.assert_called_once()
        call = write_manifest.call_args.kwargs
        self.assertFalse(call["update_latest"])
        self.assertEqual(call["payload"]["status"], "failed")
        self.assertEqual(call["payload"]["provider_runs"], {"vast": "vast-market-test"})
        self.assertEqual(call["payload"]["failed_providers"], ["lium"])

    def test_datafusion_builds_and_queries_gold_listings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            lake_root = root / "lake"
            _write_provider_snapshot(
                root,
                "vast",
                [
                    _offer(provider="vast", offer_id="vast-1", price=2.0),
                    _offer(provider="vast", offer_id="vast-2", price=4.0),
                ],
            )
            _write_provider_snapshot(
                root,
                "lium",
                _offer(
                    provider="coreweave",
                    source_connector="lium",
                    offer_id="lium-1",
                    price=5.0,
                    gpu_count=2,
                ),
            )

            build = build_gold_market_tables(
                lake_root=str(lake_root),
                providers=["vast", "lium"],
                run_id="gold-test",
            )
            rows = query_gold_listings(
                lake_root=str(lake_root),
            )["rows"]
            engine = DataFusionEngine(
                {"fact_gpu_price_index": build.table_refs["fact_gpu_price_index"]}
            )
            benchmark_rows = engine.query("""
select benchmark_family_id, benchmark_usd_gpu_hr
from fact_gpu_price_index
where benchmark_family_id = 'H100'
""")
            engine.register_tables(
                {
                    "fact_gpu_price_index_constituents": build.table_refs[
                        "fact_gpu_price_index_constituents"
                    ]
                }
            )
            constituent_rows = engine.query("""
select
  provider,
  source_connector,
  source_kind,
  observation_kind,
  price_usd_gpu_hr,
  eligible_for_benchmark,
  included
from fact_gpu_price_index_constituents
where benchmark_family_id = 'H100'
order by provider, price_usd_gpu_hr
""")
            engine.register_tables({"dim_sources": build.table_refs["dim_sources"]})
            source_rows = engine.query("""
select source_connector, source_kind, observation_kind
from dim_sources
order by source_connector
""")
            catalog = MarketDataCatalog(lake_root=str(lake_root))
            catalog_tables = catalog.tables()["tables"]
            silver_rows = catalog.query(
                """
select provider, count(*) as offer_count
from silver.gpu_offers
group by provider
order by provider
"""
            )["rows"]
            gold_description = catalog.describe("gold.fact_gpu_listings")
            silver_description = catalog.describe("silver.gpu_offers")
            silver_contract_rows = catalog.query(
                """
select
  provider,
  gpu_count,
  available_gpu_count_lower_bound,
  price_usd_instance_hr,
  price_usd_gpu_hr,
  is_available,
  source_availability_status,
  observed_at
from silver.gpu_offers
order by provider, price_usd_instance_hr
"""
            )["rows"]
            manifest = read_json(build.manifest_ref)
            export = export_gold_dashboard_snapshot(
                lake_root=str(lake_root),
                output_root=str(root / "public"),
            )
            exported_manifest = read_json(export["output_refs"]["manifest"])

        self.assertEqual(build.provider_scope, ["vast", "lium"])
        self.assertIn(
            {
                "layer": "silver",
                "table_name": "gpu_offers",
                "table_type": "VIEW",
                "row_count": None,
            },
            catalog_tables,
        )
        self.assertIn(
            {
                "layer": "gold",
                "table_name": "fact_gpu_listings",
                "table_type": "VIEW",
                "row_count": 3,
            },
            catalog_tables,
        )
        self.assertEqual(
            silver_rows,
            [
                {"provider": "coreweave", "offer_count": 1},
                {"provider": "vast", "offer_count": 2},
            ],
        )
        self.assertEqual(gold_description["table"], "gold.fact_gpu_listings")
        self.assertEqual(
            [
                (column["column_name"], column["data_type"])
                for column in silver_description["columns"]
            ],
            [(column.name, column.data_type) for column in GPU_OFFER_COLUMNS],
        )
        self.assertTrue(
            all(column["meaning"] for column in silver_description["columns"])
        )
        self.assertEqual(
            silver_contract_rows,
            [
                {
                    "provider": "coreweave",
                    "gpu_count": 2,
                    "available_gpu_count_lower_bound": 2,
                    "price_usd_instance_hr": 5.0,
                    "price_usd_gpu_hr": 2.5,
                    "is_available": True,
                    "source_availability_status": "available",
                    "observed_at": OBSERVED_AT,
                },
                {
                    "provider": "vast",
                    "gpu_count": 1,
                    "available_gpu_count_lower_bound": 1,
                    "price_usd_instance_hr": 2.0,
                    "price_usd_gpu_hr": 2.0,
                    "is_available": True,
                    "source_availability_status": "available",
                    "observed_at": OBSERVED_AT,
                },
                {
                    "provider": "vast",
                    "gpu_count": 1,
                    "available_gpu_count_lower_bound": 1,
                    "price_usd_instance_hr": 4.0,
                    "price_usd_gpu_hr": 4.0,
                    "is_available": True,
                    "source_availability_status": "available",
                    "observed_at": OBSERVED_AT,
                },
            ],
        )
        self.assertIn(
            "price_usd_gpu_hr",
            [column["column_name"] for column in gold_description["columns"]],
        )
        gold_columns = {
            column["column_name"] for column in gold_description["columns"]
        }
        self.assertFalse(
            {
                "price_usd_hr",
                "available_gpu_count",
                "availability_status",
                "stock_status",
            }
            & gold_columns
        )
        self.assertEqual(
            [row["provider"] for row in rows], ["vast", "coreweave", "vast"]
        )
        self.assertEqual([row["price_usd_gpu_hr"] for row in rows], [2.0, 2.5, 4.0])
        self.assertEqual(benchmark_rows[0]["benchmark_usd_gpu_hr"], 2.25)
        self.assertEqual(
            source_rows,
            [
                {
                    "source_connector": "lium",
                    "source_kind": "marketplace",
                    "observation_kind": "live_offer",
                },
                {
                    "source_connector": "vast",
                    "source_kind": "marketplace",
                    "observation_kind": "live_offer",
                },
            ],
        )
        self.assertEqual(
            constituent_rows,
            [
                {
                    "provider": "coreweave",
                    "source_connector": "lium",
                    "source_kind": "marketplace",
                    "observation_kind": "live_offer",
                    "price_usd_gpu_hr": 2.5,
                    "eligible_for_benchmark": True,
                    "included": True,
                },
                {
                    "provider": "vast",
                    "source_connector": "vast",
                    "source_kind": "marketplace",
                    "observation_kind": "live_offer",
                    "price_usd_gpu_hr": 2.0,
                    "eligible_for_benchmark": True,
                    "included": True,
                },
                {
                    "provider": "vast",
                    "source_connector": "vast",
                    "source_kind": "marketplace",
                    "observation_kind": "live_offer",
                    "price_usd_gpu_hr": 4.0,
                    "eligible_for_benchmark": True,
                    "included": False,
                },
            ],
        )
        self.assertEqual(
            manifest["sql_models"]["fact_gpu_price_index"]["path"],
            "sql/models/gold/gpu_price_index.sql",
        )
        self.assertEqual(
            len(manifest["sql_models"]["fact_gpu_price_index"]["sha256"]),
            64,
        )
        self.assertEqual(
            set(manifest["sql_models"]),
            {
                "fact_gpu_listings",
                "dim_gpu_products",
                "dim_providers",
                "dim_sources",
                "fact_compute_market_state",
                "fact_gpu_availability",
                "fact_gpu_availability_history",
                "fact_gpu_price_index",
                "fact_gpu_price_index_constituents",
            },
        )
        self.assertTrue(
            all(
                model["path"].startswith("sql/models/gold/")
                and len(model["sha256"]) == 64
                for model in manifest["sql_models"].values()
            )
        )
        self.assertEqual(len(load_query_catalog()), 7)
        self.assertEqual(export["row_counts"]["gpu_benchmark_cards"], 4)
        self.assertEqual(exported_manifest["run_id"], "gold-test")

    def test_bundled_sample_is_default_and_queries_both_layers(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            selection = resolve_lake_root()
            catalog = MarketDataCatalog(lake_root=selection.root)
            silver = catalog.query(
                "select count(*) as offer_count from silver.gpu_offers"
            )
            gold = catalog.query(
                "select count(*) as index_count from gold.fact_gpu_price_index"
            )
            availability = MarketQueryService(
                lake_root=selection.root
            ).gpu_availability(gpu_model="H100", limit=2)
            client = TestClient(create_app())
            health_response = client.get("/healthz")
            index_response = client.get(
                "/v1/gpu-price-index",
                params={"family": "H100"},
            )
            index_table = render_table_payload(
                index_response.json(), command="price-index"
            )
            availability_response = client.get(
                "/v1/gpu-availability",
                params={"gpu_model": "H100", "limit": 2},
            )
        with patch.dict(
            os.environ,
            {"COMPUTE_BAZAAR_LAKE_ROOT": "/tmp/environment-lake"},
            clear=True,
        ):
            environment_selection = resolve_lake_root()
            explicit_selection = resolve_lake_root("/tmp/explicit-lake")

        self.assertEqual(selection.kind, "bundled_sample")
        self.assertEqual(environment_selection.root, "/tmp/environment-lake")
        self.assertEqual(environment_selection.kind, "environment")
        self.assertEqual(explicit_selection.root, "/tmp/explicit-lake")
        self.assertEqual(explicit_selection.kind, "explicit")
        self.assertGreater(silver["rows"][0]["offer_count"], 1000)
        self.assertEqual(gold["rows"][0]["index_count"], 4)
        self.assertEqual(availability["row_count"], 2)
        self.assertTrue(
            all(
                str(row["resource_type"]).startswith("H100")
                for row in availability["rows"]
            )
        )
        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(index_response.status_code, 200)
        self.assertEqual(index_response.json()["row_count"], 1)
        self.assertIn("GPU PRICE INDEX", index_table)
        self.assertIn("H100", index_table)
        self.assertEqual(availability_response.status_code, 200)
        self.assertEqual(availability_response.json()["row_count"], 2)

    def test_silver_availability_is_explicit_and_tri_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parquet_ref = Path(temporary_directory) / "offers.parquet"
            write_offers_parquet(
                str(parquet_ref),
                [
                    _offer(
                        provider="available",
                        offer_id="available",
                        price=2.0,
                        availability_status="available",
                    ),
                    _offer(
                        provider="unavailable",
                        offer_id="unavailable",
                        price=3.0,
                        availability_status="unavailable",
                    ),
                    _offer(
                        provider="rate_card",
                        offer_id="rate",
                        price=4.0,
                        availability_status="published_rate",
                    ),
                    _offer(
                        provider="expired_rate_card",
                        offer_id="expired-rate",
                        price=5.0,
                        availability_status="published_rate_expired",
                    ),
                ],
            )
            engine = DataFusionEngine({"raw_offers": str(parquet_ref)})
            rows = engine.query(
                silver_offer_select("raw_offers") + " order by price_usd_instance_hr"
            )

        self.assertEqual(
            [
                (
                    row["source_availability_status"],
                    row["is_available"],
                )
                for row in rows
            ],
            [
                ("available", True),
                ("unavailable", False),
                ("published_rate", None),
                ("published_rate_expired", None),
            ],
        )

    def test_normalized_offer_rejects_invalid_currency_and_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            GpuOffer(
                provider="test",
                source_offer_id="naive-time",
                observed_at=datetime(2026, 8, 1, 12, 0),
                gpu_raw_name="H100",
                gpu_model="H100_80GB",
                gpu_count=1,
                vram_gb=80,
                price_usd_hr=2.0,
            )
        with self.assertRaisesRegex(ValueError, "normalized to USD"):
            GpuOffer(
                provider="test",
                source_offer_id="wrong-currency",
                observed_at=OBSERVED_AT,
                gpu_raw_name="H100",
                gpu_model="H100_80GB",
                gpu_count=1,
                vram_gb=80,
                price_usd_hr=2.0,
                currency="EUR",
            )

    def test_gold_history_filters_before_limiting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lake_root = str(Path(temporary_directory) / "lake")
            for run_id, observed_at in (
                ("gold-market-20260801T010000-11111111", "2026-08-01T01:00:00+00:00"),
                ("gold-manual-review", "2026-08-01T03:00:00+00:00"),
                ("gold-market-20260801T020000-22222222", "2026-08-01T02:00:00+00:00"),
            ):
                write_json(
                    gold_manifest_ref(
                        lake_root,
                        observed_date="2026-08-01",
                        run_id=run_id,
                    ),
                    {
                        "run_id": run_id,
                        "observed_at": observed_at,
                        "table_refs": {"fact_gpu_price_index": "memory://values"},
                    },
                )

            manifests = list_gold_manifests(
                lake_root,
                limit=1,
                canonical_market_runs_only=True,
            )

        self.assertEqual(
            manifests[0]["run_id"],
            "gold-market-20260801T020000-22222222",
        )

    def test_benchmark_excludes_aggregated_reference_prices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            lake_root = root / "lake"
            _write_provider_snapshot(
                root,
                "vast",
                _offer(provider="vast", offer_id="vast-1", price=2.0),
            )
            _write_provider_snapshot(
                root,
                "cloud_gpu_prices",
                _offer(
                    provider="reference-source",
                    source_connector="cloud_gpu_prices",
                    offer_id="reference-1",
                    price=0.5,
                ),
            )
            build = build_gold_market_tables(
                lake_root=str(lake_root),
                providers=["vast", "cloud_gpu_prices"],
                run_id="gold-eligibility-test",
            )
            rows = DataFusionEngine(
                {
                    "fact_gpu_price_index_constituents": build.table_refs[
                        "fact_gpu_price_index_constituents"
                    ]
                }
            ).query("""
select
  provider,
  eligible_for_benchmark,
  included,
  exclusion_reason
from fact_gpu_price_index_constituents
where benchmark_family_id = 'H100'
order by provider
""")

        self.assertEqual(
            rows,
            [
                {
                    "provider": "reference-source",
                    "eligible_for_benchmark": False,
                    "included": False,
                    "exclusion_reason": "aggregated_reference_price",
                },
                {
                    "provider": "vast",
                    "eligible_for_benchmark": True,
                    "included": True,
                    "exclusion_reason": None,
                },
            ],
        )

    def test_public_market_payload_does_not_expose_private_storage(self) -> None:
        payload = _public_market_run_manifest(
            {
                "market_run_id": "market-test",
                "status": "success",
                "data_quality": {
                    "sandbox_cost": {
                        "build_id": "sandbox-test",
                        "manifest_ref": "s3://private/lake/manifest.json",
                    }
                },
            }
        )

        self.assertNotIn("s3://", json.dumps(payload))
        self.assertEqual(
            payload["data_quality"]["sandbox_cost"],
            {"build_id": "sandbox-test"},
        )

    def test_publication_routes_are_stable_and_extensionless(self) -> None:
        route = PublicationRoute.create(
            card_id="GPU Index",
            subject_id="H100",
            view_id="1 Day",
            observed_at=OBSERVED_AT,
            content_digest="abcdef1234567890",
        )

        self.assertEqual(
            route.public_path,
            "publications/gpu-index/h100/1-day/2026-08-01-1200-utc-abcdef1234",
        )
        self.assertEqual(route.page_path, f"{route.public_path}.html")

    def test_public_market_freshness_requires_complete_current_payload(self) -> None:
        cards = {
            family: {"as_of": OBSERVED_AT.isoformat(), "status": "live"}
            for family in ("h100", "h200", "b200", "b300")
        }
        summary = validate_public_market(
            market_run={
                "market_run_id": "market-test",
                "observed_at": OBSERVED_AT.isoformat(),
                "status": "success",
                "successful_providers": ["vast", "lium"],
                "failed_providers": [],
            },
            cards=cards,
            max_age_hours=2.5,
            required_providers={"vast", "lium"},
            forbidden_providers={"published_rate_cards"},
            now=OBSERVED_AT,
        )

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["provider_count"], 2)

    def test_sandbox_publication_preserves_runs_and_exposes_measured_history(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            public_root = root / "public"
            build = build_sandbox_cost(
                output_root=str(root / "lake"),
                dashboard_output_root=str(public_root),
            )
            card = read_json(str(public_root / "sandbox" / "workload.json"))

        measured_history = card["data"]["workload"]["measured_history"]
        run_history = card["series"]
        self.assertEqual(card["card_type"], "sandbox_workload_cost")
        self.assertEqual(
            build.public_ref,
            str(public_root / "sandbox" / "workload.json"),
        )
        self.assertFalse((public_root / "sandbox-cost.json").exists())
        self.assertEqual(build.row_counts["sandbox_workload_measured_history"], 63)
        self.assertEqual(len(measured_history), 63)
        self.assertEqual(len(run_history), 14)
        self.assertTrue(all(row["observed_date"] for row in measured_history))
        self.assertTrue(all(row["source_run_count"] >= 1 for row in measured_history))

    def test_query_api_reads_latest_gold_and_blocks_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            lake_root = root / "lake"
            _write_provider_snapshot(
                root,
                "vast",
                [
                    _offer(provider="vast", offer_id="vast-1", price=2.0),
                    _offer(provider="vast", offer_id="vast-2", price=4.0),
                ],
            )
            _write_provider_snapshot(
                root,
                "lium",
                _offer(
                    provider="coreweave",
                    source_connector="lium",
                    offer_id="lium-1",
                    price=2.5,
                ),
            )
            build_gold_market_tables(
                lake_root=str(lake_root),
                providers=["vast", "lium"],
                run_id="gold-api-test",
            )
            client = TestClient(
                create_app(
                    lake_root=str(lake_root),
                    enable_scratch_sql=True,
                    query_api_key="test-query-key",
                )
            )

            manifest_response = client.get("/v1/manifest")
            listings_response = client.get(
                "/v1/listings",
                params={"provider": "vast", "limit": 1},
            )
            catalog_response = client.get("/v1/queries/gpu_price_index")
            sql_response = client.post(
                "/v1/sql",
                json={
                    "sql": "select provider, price_usd_gpu_hr from fact_gpu_listings order by price_usd_gpu_hr",
                    "limit": 2,
                },
                headers={"Authorization": "Bearer test-query-key"},
            )
            private_ref_response = client.post(
                "/v1/sql",
                json={
                    "sql": "select raw_ref as evidence from fact_gpu_listings",
                    "limit": 2,
                },
                headers={"Authorization": "Bearer test-query-key"},
            )
            write_response = client.post(
                "/v1/sql",
                json={"sql": "delete from fact_gpu_listings", "limit": 2},
                headers={"Authorization": "Bearer test-query-key"},
            )
            unauthorized_response = client.post(
                "/v1/sql",
                json={"sql": "select * from fact_gpu_listings", "limit": 2},
            )

        self.assertEqual(manifest_response.status_code, 200)
        manifest = manifest_response.json()
        self.assertEqual(manifest["run_id"], "gold-api-test")
        self.assertNotIn("table_refs", manifest)
        self.assertNotIn("s3://", json.dumps(manifest))
        self.assertEqual(listings_response.status_code, 200)
        self.assertEqual(listings_response.json()["row_count"], 1)
        self.assertEqual(listings_response.json()["rows"][0]["provider"], "vast")
        self.assertEqual(catalog_response.status_code, 200)
        self.assertEqual(catalog_response.json()["query"]["engine"], "datafusion")
        self.assertNotIn("s3://", catalog_response.text)
        self.assertNotIn("source_manifest_ref", catalog_response.text)
        self.assertEqual(sql_response.status_code, 200)
        self.assertEqual(sql_response.json()["row_count"], 2)
        self.assertEqual(private_ref_response.status_code, 400)
        self.assertNotIn("s3://", private_ref_response.text)
        self.assertEqual(write_response.status_code, 400)
        self.assertEqual(unauthorized_response.status_code, 401)

    def test_query_api_health_is_unavailable_without_gold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            client = TestClient(create_app(lake_root=temporary_directory))
            response = client.get("/healthz")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})


def _offer(
    *,
    provider: str,
    offer_id: str,
    price: float,
    source_connector: str | None = None,
    gpu_count: int = 1,
    availability_status: str = "available",
) -> GpuOffer:
    return GpuOffer(
        provider=provider,
        source_offer_id=offer_id,
        observed_at=OBSERVED_AT,
        gpu_raw_name="NVIDIA H100 80GB",
        gpu_model="H100_80GB" if gpu_count == 1 else f"H100_80GB_x{gpu_count}",
        gpu_count=gpu_count,
        vram_gb=80,
        price_usd_hr=price,
        available_gpu_count=gpu_count,
        source_connector=source_connector or provider,
        currency="USD",
        country="US",
        region="test",
        availability_status=availability_status,
        raw_ref=f"raw/{provider}.json",
        metadata={f"{provider}_field": "provider-specific"},
    )


def _write_provider_snapshot(
    root: Path,
    provider: str,
    offers: GpuOffer | list[GpuOffer],
) -> None:
    offer_rows = [offers] if isinstance(offers, GpuOffer) else offers
    lake_root = root / "lake"
    raw_ref = root / "raw" / f"{provider}.json"
    normalized_ref = lake_root / "silver" / provider / "offers.parquet"
    manifest_ref = (
        lake_root / "_manifests" / "gpu_offers" / f"provider={provider}" / "run.json"
    )
    latest_ref = manifest_ref.with_name("latest.json")
    manifest = {
        "manifest_version": "v1",
        "table": "gpu_offers",
        "provider": provider,
        "run_id": f"{provider}-test",
        "observed_at": OBSERVED_AT.isoformat(),
        "raw_ref": str(raw_ref),
        "normalized_ref": str(normalized_ref),
        "raw_offer_count": len(offer_rows),
        "normalized_offer_count": len(offer_rows),
        "published_events": 0,
        "publish_mode": "test",
        "unknown_gpu_names": [],
        "market_state_ref": None,
        "market_state_observation_count": 0,
        "manifest_ref": str(manifest_ref),
    }
    write_json(str(raw_ref), [offer.to_dict() for offer in offer_rows])
    write_offers_parquet(str(normalized_ref), offer_rows)
    write_json(str(manifest_ref), manifest)
    write_json(str(latest_ref), manifest)


if __name__ == "__main__":
    unittest.main()
