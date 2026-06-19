from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from the_compute_bazaar.prices.gold import (
    build_gold_market_tables,
    query_gold_index_constituents,
    query_gold_listings,
    query_gold_provider_comparison,
)
from the_compute_bazaar.prices.market_run import list_market_runs, read_latest_market_run, write_market_run_manifest
from the_compute_bazaar.prices.normalize import canonical_gpu_model
from the_compute_bazaar.prices.providers.lium import LiumClient, normalize_executor
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

    def test_lium_fetch_pages_preserves_raw_pages_and_dedupes_executors(self) -> None:
        session = _FakeSession(
            [
                {"data": [{"id": "exec-a"}, {"id": "exec-b"}]},
                {"data": [{"id": "exec-b"}, {"id": "exec-c"}]},
                {"data": []},
            ]
        )
        client = LiumClient(api_key="test-key", api_base="https://example.test/api", session=session)

        fetched = client.fetch_executor_pages(query={"size": 2}, paginate=True, max_pages=4)

        self.assertEqual([row["id"] for row in fetched.executors], ["exec-a", "exec-b", "exec-c"])
        self.assertEqual(fetched.raw_payload["mode"], "paginated")
        self.assertEqual(fetched.raw_payload["executor_count"], 3)
        self.assertEqual(len(fetched.raw_payload["pages"]), 3)
        self.assertEqual([call["params"]["page"] for call in session.calls], [1, 2, 3])


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
            constituents = query_gold_index_constituents(
                lake_root=lake_root,
                gpu_model="RTX4090_24GB",
                limit=10,
            )
            listings = query_gold_listings(
                lake_root=lake_root,
                gpu_model="RTX4090_24GB",
                limit=10,
            )

        rows = sorted(result["rows"], key=lambda row: row["provider"])
        self.assertEqual([row["provider"] for row in rows], ["lium", "vast"])
        self.assertEqual(rows[0]["floor_usd_gpu_hr"], 0.30)
        self.assertEqual(rows[1]["floor_usd_gpu_hr"], 0.20)
        self.assertEqual(rows[1]["listing_count"], 1)
        excluded = [row for row in constituents["rows"] if row["listing_id"] == "vast:vast-unavailable"]
        self.assertEqual(len(excluded), 1)
        self.assertFalse(excluded[0]["included"])
        self.assertEqual(excluded[0]["exclusion_reason"], "not_available")
        available_listing = [row for row in listings["rows"] if row["listing_id"] == "vast:vast-available"]
        self.assertEqual(len(available_listing), 1)
        self.assertEqual(available_listing[0]["price_usd_instance_hr"], 0.20)
        self.assertEqual(available_listing[0]["price_usd_gpu_hr"], 0.20)
        self.assertTrue(available_listing[0]["has_raw_evidence"])
        self.assertEqual(available_listing[0]["source_run_id"], "vast:vast-test,lium:lium-test")

    def test_market_run_manifest_writes_latest_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            payload = {
                "manifest_version": "v1",
                "table": "market_runs",
                "market_run_id": "market-test",
                "status": "success",
                "checks": {"vast": "ok", "lium": "ok", "gold": "ok"},
            }

            manifest_ref = write_market_run_manifest(
                lake_root=lake_root,
                observed_date="2026-06-17",
                market_run_id="market-test",
                payload=payload,
            )
            latest = read_latest_market_run(lake_root)
            history = list_market_runs(lake_root)

        self.assertEqual(latest["market_run_id"], "market-test")
        self.assertEqual(latest["manifest_ref"], manifest_ref)
        self.assertEqual([row["market_run_id"] for row in history], ["market-test"])
        self.assertTrue(manifest_ref.endswith("/_manifests/market_runs/date=2026-06-17/run_id=market-test.json"))


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


class _FakeSession:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, object],
        headers: dict[str, str],
        timeout: int,
    ) -> "_FakeResponse":
        self.calls.append({"url": url, "params": dict(params), "headers": dict(headers), "timeout": timeout})
        return _FakeResponse(self.payloads[len(self.calls) - 1])


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


if __name__ == "__main__":
    unittest.main()
