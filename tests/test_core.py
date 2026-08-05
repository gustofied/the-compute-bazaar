from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from infra.windmill import market_hourly as windmill_market_hourly
from infra.aws.check_public_market import validate_public_market
from the_compute_bazaar.prices.gold import (
    build_gold_market_tables,
    query_gold_listings,
)
from the_compute_bazaar.prices.datafusion import query_tables
from the_compute_bazaar.prices.market_run import (
    _public_market_run_manifest,
    default_market_providers,
    run_market_hourly,
)
from the_compute_bazaar.prices.pipeline import IngestResult
from the_compute_bazaar.prices.provider_registry import (
    PROVIDERS,
    ProviderDefinition,
    ProviderRunContext,
)
from the_compute_bazaar.prices.providers.lium import normalize_executor
from the_compute_bazaar.prices.providers.vast import normalize_offer
from the_compute_bazaar.prices.schemas import GpuOffer
from the_compute_bazaar.prices.query_catalog import load_query_catalog
from the_compute_bazaar.prices.storage import (
    read_json,
    write_json,
    write_offers_parquet,
)
from the_compute_bazaar.publication_contract import PublicationRoute


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

    def test_incomplete_provider_cohort_does_not_build_gold(self) -> None:
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
        ):
            with self.assertRaisesRegex(RuntimeError, "cohort incomplete"):
                run_market_hourly(
                    providers=["vast", "lium"],
                    raw_root="memory://raw",
                    lake_root="memory://lake",
                    dashboard_output_root="memory://dashboard",
                    dry_run=True,
                )

        build_gold.assert_not_called()

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
                    price=2.5,
                ),
            )

            build = build_gold_market_tables(
                lake_root=str(lake_root),
                providers=["vast", "lium"],
                run_id="gold-test",
            )
            rows = query_gold_listings(
                lake_root=str(lake_root),
                gpu_model="H100_80GB",
            )["rows"]
            benchmark_rows = query_tables(
                tables={
                    "fact_benchmark_values": build.table_refs["fact_benchmark_values"]
                },
                sql="""
select benchmark_family_id, benchmark_usd_gpu_hr
from fact_benchmark_values
where benchmark_family_id = 'H100'
""",
            )
            constituent_rows = query_tables(
                tables={
                    "fact_benchmark_constituents": build.table_refs[
                        "fact_benchmark_constituents"
                    ]
                },
                sql="""
select
  provider,
  source_connector,
  source_kind,
  observation_kind,
  price_usd_gpu_hr,
  eligible_for_benchmark,
  included
from fact_benchmark_constituents
where benchmark_family_id = 'H100'
order by provider, price_usd_gpu_hr
""",
            )
            source_rows = query_tables(
                tables={"dim_sources": build.table_refs["dim_sources"]},
                sql="""
select source_connector, source_kind, observation_kind
from dim_sources
order by source_connector
""",
            )
            manifest = read_json(build.manifest_ref)

        self.assertEqual(build.provider_scope, ["vast", "lium"])
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
            manifest["sql_models"]["fact_benchmark_values"]["path"],
            "sql/models/gold/benchmark_values.sql",
        )
        self.assertEqual(
            len(manifest["sql_models"]["fact_benchmark_values"]["sha256"]),
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
                "fact_benchmark_values",
                "fact_benchmark_constituents",
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


def _offer(
    *,
    provider: str,
    offer_id: str,
    price: float,
    source_connector: str | None = None,
) -> GpuOffer:
    return GpuOffer(
        provider=provider,
        source_offer_id=offer_id,
        observed_at=OBSERVED_AT,
        gpu_raw_name="NVIDIA H100 80GB",
        gpu_model="H100_80GB",
        gpu_count=1,
        vram_gb=80,
        price_usd_hr=price,
        available_gpu_count=1,
        source_connector=source_connector or provider,
        currency="USD",
        country="US",
        region="test",
        availability_status="available",
        raw_ref=f"raw/{provider}.json",
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
