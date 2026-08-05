from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from infra.windmill import market_hourly as windmill_market_hourly
from the_compute_bazaar.dashboard import _snapshot_name_for_filename
from the_compute_bazaar.prices.gold import (
    build_gold_market_tables,
    query_gold_listings,
)
from the_compute_bazaar.prices.datafusion import query_tables
from the_compute_bazaar.prices.market_run import _public_market_run_manifest
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
    def test_windmill_calls_market_service_directly(self) -> None:
        result = Mock()
        result.to_dict.return_value = {"market_run_id": "market-direct"}
        previous_vast_key = os.getenv("VAST_API_KEY")

        with patch.object(
            windmill_market_hourly, "run_market_hourly", return_value=result
        ) as run_market:
            payload = windmill_market_hourly.main(
                vast_api_key="test-vast",
                lium_api_key="test-lium",
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

    def test_datafusion_builds_and_queries_gold_listings(self) -> None:
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
                "lium",
                _offer(provider="lium", offer_id="lium-1", price=2.5),
            )

            build = build_gold_market_tables(
                lake_root=str(lake_root),
                providers=["vast", "lium"],
                run_id="gold-smoke",
            )
            rows = query_gold_listings(
                lake_root=str(lake_root),
                gpu_model="H100_80GB",
            )["rows"]
            benchmark_rows = query_tables(
                tables={
                    "fact_benchmark_values": build.table_refs[
                        "fact_benchmark_values"
                    ]
                },
                sql="""
select benchmark_family_id, benchmark_usd_gpu_hr
from fact_benchmark_values
where benchmark_family_id = 'H100'
""",
            )
            manifest = read_json(build.manifest_ref)

        self.assertEqual(build.provider_scope, ["vast", "lium"])
        self.assertEqual([row["provider"] for row in rows], ["vast", "lium"])
        self.assertEqual([row["price_usd_gpu_hr"] for row in rows], [2.0, 2.5])
        self.assertEqual(benchmark_rows[0]["benchmark_usd_gpu_hr"], 2.25)
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
                "dim_regions",
                "fact_price_index_values",
                "fact_index_constituents",
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
        self.assertEqual(len(load_query_catalog()), 8)

    def test_public_market_payload_does_not_expose_private_storage(self) -> None:
        payload = _public_market_run_manifest(
            {
                "market_run_id": "market-smoke",
                "status": "success",
                "data_quality": {
                    "sandbox_cost": {
                        "build_id": "sandbox-smoke",
                        "manifest_ref": "s3://private/lake/manifest.json",
                    }
                },
            }
        )

        self.assertNotIn("s3://", json.dumps(payload))
        self.assertEqual(
            payload["data_quality"]["sandbox_cost"],
            {"build_id": "sandbox-smoke"},
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
        self.assertEqual(_snapshot_name_for_filename("gpu-benchmark/h100.json"), "gpu-benchmark-h100")


def _offer(*, provider: str, offer_id: str, price: float) -> GpuOffer:
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
        source_connector=provider,
        currency="USD",
        country="US",
        region="test",
        availability_status="available",
        raw_ref=f"raw/{provider}.json",
    )


def _write_provider_snapshot(root: Path, provider: str, offer: GpuOffer) -> None:
    lake_root = root / "lake"
    raw_ref = root / "raw" / f"{provider}.json"
    normalized_ref = lake_root / "silver" / provider / "offers.parquet"
    manifest_ref = lake_root / "_manifests" / "gpu_offers" / f"provider={provider}" / "run.json"
    latest_ref = manifest_ref.with_name("latest.json")
    manifest = {
        "manifest_version": "v1",
        "table": "gpu_offers",
        "provider": provider,
        "run_id": f"{provider}-smoke",
        "observed_at": OBSERVED_AT.isoformat(),
        "raw_ref": str(raw_ref),
        "normalized_ref": str(normalized_ref),
        "raw_offer_count": 1,
        "normalized_offer_count": 1,
        "published_events": 0,
        "publish_mode": "test",
        "unknown_gpu_names": [],
        "market_state_ref": None,
        "market_state_observation_count": 0,
        "manifest_ref": str(manifest_ref),
    }
    write_json(str(raw_ref), [offer.to_dict()])
    write_offers_parquet(str(normalized_ref), [offer])
    write_json(str(manifest_ref), manifest)
    write_json(str(latest_ref), manifest)


if __name__ == "__main__":
    unittest.main()
