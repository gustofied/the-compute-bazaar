from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from the_compute_bazaar.prices.gold import (
    build_gold_market_tables,
    query_gold_provider_comparison,
)
from the_compute_bazaar.prices.normalize import canonical_gpu_model
from the_compute_bazaar.prices.providers.lium import normalize_executor
from the_compute_bazaar.prices.schemas import GpuOffer
from the_compute_bazaar.prices.storage import write_json, write_offers_parquet


OBSERVED_AT = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)


class GpuNormalizationTests(unittest.TestCase):
    def test_lium_executor_normalizes_price_per_gpu_to_total_offer_price(self) -> None:
        offer = normalize_executor(
            {
                "id": "lium-1",
                "machine_name": "NVIDIA H100",
                "price_per_gpu": 1.25,
                "available_gpu_count": 2,
                "gpu_count": 2,
                "tier": "secure",
                "location": {"country": "Finland", "city": "Helsinki", "region_name": "Uusimaa"},
                "specs": {"gpu": {"count": 2, "details": [{"name": "NVIDIA H100", "capacity": 81920}]}},
            },
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/lium.json",
        )

        self.assertIsNotNone(offer)
        assert offer is not None
        self.assertEqual(offer.provider, "lium")
        self.assertEqual(offer.gpu_model, "H100_80GB_x2")
        self.assertEqual(offer.gpu_count, 2)
        self.assertEqual(offer.price_usd_hr, 2.5)
        self.assertEqual(offer.vram_gb, 80)
        self.assertTrue(offer.is_secure)
        self.assertEqual(offer.country, "Finland")
        self.assertEqual(offer.region, "Helsinki, Uusimaa")

    def test_provider_gpu_name_variants_share_canonical_model(self) -> None:
        self.assertEqual(canonical_gpu_model("NVIDIA A100-SXM4-80GB", 81920), "A100_80GB")
        self.assertEqual(
            canonical_gpu_model("NVIDIA RTX PRO 6000 Blackwell Server Edition", 98304),
            "RTXPro6000B_96GB",
        )
        self.assertEqual(canonical_gpu_model("GeForce RTX 4090", 24576), "RTX4090_24GB")
        self.assertEqual(
            canonical_gpu_model("NVIDIA RTX 6000 Ada Generation", 49152),
            "RTX6000Ada_48GB",
        )


class GoldQueryTests(unittest.TestCase):
    def test_provider_comparison_uses_available_offers_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-test",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="vast-unavailable",
                        price_usd_hr=0.10,
                        availability_status="unavailable",
                    ),
                    _offer(provider="vast", source_offer_id="vast-available", price_usd_hr=0.20),
                ],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="lium",
                run_id="lium-test",
                offers=[
                    _offer(provider="lium", source_offer_id="lium-available", price_usd_hr=0.30),
                ],
            )

            build_gold_market_tables(lake_root=lake_root, providers=["vast", "lium"], run_id="gold-test")
            result = query_gold_provider_comparison(
                lake_root=lake_root,
                gpu_model="RTX4090_24GB",
                limit=10,
            )

        rows = sorted(result["rows"], key=lambda row: row["provider"])
        self.assertEqual([row["provider"] for row in rows], ["lium", "vast"])
        self.assertEqual(rows[0]["floor_usd_gpu_hr"], 0.30)
        self.assertEqual(rows[1]["floor_usd_gpu_hr"], 0.20)
        self.assertEqual(rows[1]["listing_count"], 1)


def _offer(
    *,
    provider: str,
    source_offer_id: str,
    price_usd_hr: float,
    availability_status: str = "available",
) -> GpuOffer:
    return GpuOffer(
        provider=provider,
        source_offer_id=source_offer_id,
        observed_at=OBSERVED_AT,
        gpu_raw_name="RTX 4090",
        gpu_model="RTX4090_24GB",
        gpu_count=1,
        vram_gb=24,
        price_usd_hr=price_usd_hr,
        country="US",
        region="California",
        availability_status=availability_status,
        raw_ref=f"raw/{provider}.json",
    )


def _write_provider_run(
    *,
    lake_root: str,
    raw_root: str,
    provider: str,
    run_id: str,
    offers: list[GpuOffer],
) -> None:
    raw_ref = f"{raw_root}/provider={provider}/date=2026-06-17/run_id={run_id}/offers.json"
    normalized_ref = (
        f"{lake_root}/silver/gpu_offers/date=2026-06-17/provider={provider}/run_id={run_id}/offers.parquet"
    )
    manifest_ref = f"{lake_root}/_manifests/gpu_offers/provider={provider}/date=2026-06-17/run_id={run_id}.json"
    latest_ref = f"{lake_root}/_manifests/gpu_offers/provider={provider}/latest.json"
    manifest = {
        "manifest_version": "v1",
        "table": "gpu_offers",
        "provider": provider,
        "run_id": run_id,
        "observed_at": OBSERVED_AT.isoformat(),
        "raw_ref": raw_ref,
        "normalized_ref": normalized_ref,
        "raw_offer_count": len(offers),
        "normalized_offer_count": len(offers),
        "published_events": len(offers) + 1,
        "publish_mode": "test",
        "unknown_gpu_names": [],
        "manifest_ref": manifest_ref,
    }
    write_json(raw_ref, [offer.to_dict() for offer in offers])
    write_offers_parquet(normalized_ref, offers)
    write_json(manifest_ref, manifest)
    write_json(latest_ref, manifest)


if __name__ == "__main__":
    unittest.main()
