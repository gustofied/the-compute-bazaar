from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from the_compute_bazaar.prices.gold import (
    build_gold_market_tables,
    export_gold_dashboard_snapshot,
    query_gold_benchmark_constituents,
    query_gold_benchmark_values,
    query_gold_featured_index,
    query_gold_index_constituents,
    query_gold_index_history,
    query_gold_listings,
    query_gold_provider_comparison,
)
from the_compute_bazaar.prices.market_run import list_market_runs, read_latest_market_run, write_market_run_manifest
from the_compute_bazaar.prices.normalize import canonical_gpu_model
from the_compute_bazaar.prices.operator import (
    list_operator_queries,
    preview_operator_ref,
    run_operator_query,
    run_operator_sql,
    trace_operator_row,
)
from the_compute_bazaar.prices.providers.lium import LiumClient, normalize_executor
from the_compute_bazaar.prices.pipeline import ingest_rate_card
from the_compute_bazaar.prices.providers.rate_cards import rate_card_providers
from the_compute_bazaar.prices.providers.vast import VastClient, default_market_query
from the_compute_bazaar.prices.schemas import GpuOffer
from the_compute_bazaar.prices.storage import read_json, write_json, write_offers_parquet


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
        self.assertEqual(canonical_gpu_model("NVIDIA A800 PCIe", 81920), "A800_80GB")
        self.assertEqual(canonical_gpu_model("NVIDIA RTX 4090D", 24576), "RTX4090D_24GB")
        self.assertEqual(canonical_gpu_model("NVIDIA Tesla T4", 16384), "T4_16GB")
        self.assertEqual(canonical_gpu_model("NVIDIA RTX A2000", 12288), "A2000_12GB")
        self.assertEqual(canonical_gpu_model("NVIDIA Quadro P4000", 8192), "QuadroP4000_8GB")
        self.assertEqual(canonical_gpu_model("NVIDIA Quadro RTX 4000", 8192), "QuadroRTX4000_8GB")

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

    def test_vast_default_market_query_uses_json_post_search(self) -> None:
        session = _FakeSession([{"offers": [{"id": 123, "gpu_name": "RTX 4090"}]}])
        client = VastClient(api_key="test-key", api_base="https://example.test/api/v0", session=session)

        payload = client.search_bundles()

        self.assertEqual(payload, {"offers": [{"id": 123, "gpu_name": "RTX 4090"}]})
        self.assertEqual(len(session.calls), 1)
        call = session.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "https://example.test/api/v0/bundles/")
        self.assertEqual(call["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(call["json"], default_market_query())

    def test_published_rate_cards_normalize_as_provider_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            runpod = ingest_rate_card(
                provider="runpod",
                raw_root=raw_root,
                lake_root=lake_root,
                dry_run=True,
                run_id="runpod-rates",
            )
            hyperstack = ingest_rate_card(
                provider="hyperstack",
                raw_root=raw_root,
                lake_root=lake_root,
                dry_run=True,
                run_id="hyperstack-rates",
            )

            build_gold_market_tables(
                lake_root=lake_root,
                providers=["runpod", "hyperstack"],
                run_id="gold-rate-cards",
            )
            values = query_gold_benchmark_values(lake_root=lake_root)

        self.assertIn("runpod", rate_card_providers())
        self.assertGreater(runpod.normalized_offer_count, 0)
        self.assertGreater(hyperstack.normalized_offer_count, 0)
        rows = {row["benchmark_family_id"]: row for row in values["rows"]}
        self.assertEqual(rows["B300"]["status"], "observed")
        self.assertEqual(rows["B300"]["provider_count"], 2)
        self.assertEqual(rows["H200"]["provider_count"], 2)


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

    def test_gold_index_history_reads_recent_gold_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-history-1",
                offers=[_offer(provider="vast", source_offer_id="vast-1", price_usd_hr=0.20)],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="lium",
                run_id="lium-history-1",
                offers=[_offer(provider="lium", source_offer_id="lium-1", price_usd_hr=0.30)],
            )
            build_gold_market_tables(lake_root=lake_root, providers=["vast", "lium"], run_id="gold-history-1")

            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-history-2",
                offers=[_offer(provider="vast", source_offer_id="vast-2", price_usd_hr=0.40)],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="lium",
                run_id="lium-history-2",
                offers=[_offer(provider="lium", source_offer_id="lium-2", price_usd_hr=0.50)],
            )
            build_gold_market_tables(lake_root=lake_root, providers=["vast", "lium"], run_id="gold-history-2")

            history = query_gold_index_history(
                lake_root=lake_root,
                history_limit=10,
                gpu_models=["RTX4090_24GB"],
            )

        rows = history["rows"]
        self.assertEqual(history["history_manifest_count"], 2)
        self.assertEqual({row["gold_run_id"] for row in rows}, {"gold-history-1", "gold-history-2"})
        self.assertEqual({row["gpu_model"] for row in rows}, {"RTX4090_24GB"})
        self.assertEqual({row["floor_usd_gpu_hr"] for row in rows}, {0.20, 0.40})

    def test_gold_benchmark_values_group_frontier_gpu_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            dashboard_root = str(Path(tmpdir) / "dashboard")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-benchmark",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="h100-vast-1",
                        price_usd_hr=1.00,
                        gpu_raw_name="NVIDIA H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    ),
                    _offer(
                        provider="vast",
                        source_offer_id="h100-vast-2",
                        price_usd_hr=2.00,
                        gpu_raw_name="NVIDIA H100 PCIe",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    ),
                ],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="lium",
                run_id="lium-benchmark",
                offers=[
                    _offer(
                        provider="lium",
                        source_offer_id="h100-lium-1",
                        price_usd_hr=3.00,
                        gpu_raw_name="NVIDIA H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    ),
                    _offer(
                        provider="lium",
                        source_offer_id="b200-lium-1",
                        price_usd_hr=12.00,
                        gpu_raw_name="NVIDIA B200",
                        gpu_model="B200_180GB",
                        vram_gb=180,
                    ),
                ],
            )

            build = build_gold_market_tables(lake_root=lake_root, providers=["vast", "lium"], run_id="gold-benchmark")
            values = query_gold_benchmark_values(lake_root=lake_root)
            constituents = query_gold_benchmark_constituents(lake_root=lake_root, benchmark_family_id="H100")
            export = export_gold_dashboard_snapshot(
                lake_root=lake_root,
                output_root=dashboard_root,
                limit=100,
            )
            public_benchmarks = read_json(export["output_refs"]["featured_benchmarks"])
            public_constituents = read_json(export["output_refs"]["benchmark_constituents"])

        rows = {row["benchmark_family_id"]: row for row in values["rows"]}
        self.assertEqual(build.row_counts["fact_benchmark_values"], 4)
        self.assertEqual(build.row_counts["fact_benchmark_constituents"], 4)
        self.assertEqual(rows["H100"]["status"], "observed")
        self.assertEqual(rows["H100"]["offer_count"], 3)
        self.assertEqual(rows["H100"]["provider_count"], 2)
        self.assertEqual(rows["H100"]["floor_usd_gpu_hr"], 1.00)
        self.assertEqual(rows["H100"]["benchmark_usd_gpu_hr"], 2.00)
        self.assertEqual(rows["B200"]["benchmark_usd_gpu_hr"], 12.00)
        self.assertEqual(rows["H200"]["status"], "not_observed")
        self.assertIsNone(rows["H200"]["benchmark_usd_gpu_hr"])
        self.assertEqual(len(constituents["rows"]), 3)
        self.assertTrue(all(row["included"] for row in constituents["rows"]))
        self.assertIn("featured_benchmarks", export["output_refs"])
        self.assertIn("benchmark_constituents", export["output_refs"])
        self.assertEqual(export["row_counts"]["featured_benchmarks"], 4)
        self.assertEqual(export["row_counts"]["benchmark_constituents"], 4)
        self.assertNotIn("source_manifest_ref", public_benchmarks["rows"][0])
        self.assertNotIn("source_normalized_ref", public_benchmarks["rows"][0])
        self.assertNotIn("raw_ref", public_constituents["rows"][0])
        self.assertNotIn("source_manifest_ref", public_constituents["rows"][0])
        self.assertNotIn("source_normalized_ref", public_constituents["rows"][0])

    def test_featured_index_keeps_frontier_gpus_and_last_seen_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            dashboard_root = str(Path(tmpdir) / "dashboard")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-frontier-1",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="h200-old",
                        price_usd_hr=7.60,
                        gpu_raw_name="NVIDIA H200",
                        gpu_model="H200_141GB",
                        vram_gb=141,
                    )
                ],
            )
            build_gold_market_tables(lake_root=lake_root, providers=["vast"], run_id="gold-frontier-1")

            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-frontier-2",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="h100-latest",
                        price_usd_hr=1.25,
                        gpu_raw_name="NVIDIA H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    )
                ],
            )
            build_gold_market_tables(lake_root=lake_root, providers=["vast"], run_id="gold-frontier-2")

            featured = query_gold_featured_index(
                lake_root=lake_root,
                products=[
                    {"gpu_model": "H100_80GB", "label": "H100"},
                    {"gpu_model": "H200_141GB", "label": "H200"},
                ],
                history_limit=10,
            )
            export = export_gold_dashboard_snapshot(
                lake_root=lake_root,
                output_root=dashboard_root,
                limit=1,
            )

        rows = {row["gpu_model"]: row for row in featured["rows"]}
        self.assertEqual(rows["H100_80GB"]["status"], "observed_latest")
        self.assertTrue(rows["H100_80GB"]["is_latest"])
        self.assertEqual(rows["H100_80GB"]["floor_usd_gpu_hr"], 1.25)
        self.assertEqual(rows["H200_141GB"]["status"], "not_present_latest")
        self.assertFalse(rows["H200_141GB"]["is_latest"])
        self.assertIsNone(rows["H200_141GB"]["floor_usd_gpu_hr"])
        self.assertEqual(rows["H200_141GB"]["last_seen_floor_usd_gpu_hr"], 7.60)
        self.assertIn("featured_index", export["output_refs"])
        self.assertEqual(export["row_counts"]["featured_index"], 4)

    def test_operator_saved_queries_run_against_latest_gold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-operator",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="h100-operator",
                        price_usd_hr=2.00,
                        gpu_raw_name="NVIDIA H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    )
                ],
            )
            build_gold_market_tables(lake_root=lake_root, providers=["vast"], run_id="gold-operator")

            catalog = list_operator_queries(lake_root=lake_root)
            values = run_operator_query(lake_root=lake_root, query_id="benchmark_values", limit=10)
            constituents = run_operator_query(lake_root=lake_root, query_id="benchmark_constituents", limit=10)
            counts = run_operator_query(lake_root=lake_root, query_id="gold_table_counts", limit=20)
            scratch = run_operator_sql(
                lake_root=lake_root,
                sql="""
                select
                  benchmark_family_id,
                  benchmark_usd_gpu_hr
                from fact_benchmark_values
                order by benchmark_family_id
                """,
                limit=2,
            )
            lineage = trace_operator_row(
                lake_root=lake_root,
                query_id="benchmark_constituents",
                row=constituents["rows"][0],
            )
            preview = preview_operator_ref(
                lake_root=lake_root,
                ref=f"{raw_root}/provider=vast/date=2026-06-17/run_id=vast-operator/offers.json",
            )
            sql_preview = preview_operator_ref(
                lake_root=lake_root,
                ref="queries/curia/benchmark_constituents_v0.sql",
            )
            with self.assertRaises(PermissionError):
                preview_operator_ref(lake_root=lake_root, ref=f"{raw_root}/not-in-manifest.json")
            with self.assertRaises(ValueError):
                run_operator_sql(lake_root=lake_root, sql="drop table fact_gpu_listings")
            with self.assertRaises(ValueError):
                run_operator_sql(lake_root=lake_root, sql="select * from fact_gpu_listings; select * from dim_providers")
            with self.assertRaises(ValueError):
                run_operator_sql(lake_root=lake_root, sql="select * from read_parquet('s3://bucket/elsewhere')")

        self.assertEqual(catalog["manifest"]["run_id"], "gold-operator")
        catalog_rows = {query["query_id"]: query for query in catalog["queries"]}
        self.assertIn("benchmark_values", catalog_rows)
        self.assertEqual(catalog_rows["benchmark_values"]["version"], "v0")
        self.assertEqual(catalog_rows["benchmark_values"]["engine"], "datafusion")
        self.assertEqual(catalog_rows["benchmark_values"]["sql_path"], "queries/curia/benchmark_values_v0.sql")
        self.assertEqual(len(catalog_rows["benchmark_values"]["query_hash"]), 64)
        self.assertTrue(all(query["available"] for query in catalog["queries"]))
        self.assertEqual(values["query"]["sql_path"], "queries/curia/benchmark_values_v0.sql")
        self.assertEqual(values["query"]["version"], "v0")
        benchmark_rows = {row["benchmark_family_id"]: row for row in values["rows"]}
        self.assertEqual(benchmark_rows["H100"]["benchmark_usd_gpu_hr"], 2.00)
        self.assertEqual(scratch["query"]["query_id"], "scratch_sql")
        self.assertEqual(scratch["query"]["engine"], "datafusion")
        self.assertTrue(scratch["query"]["read_only"])
        self.assertIn("fact_benchmark_values", scratch["query"]["tables"])
        self.assertEqual(scratch["limit"], 2)
        self.assertEqual(len(scratch["rows"]), 2)
        table_counts = {row["table_name"]: row["row_count"] for row in counts["rows"]}
        self.assertEqual(table_counts["fact_gpu_listings"], 1)
        self.assertEqual(table_counts["fact_benchmark_values"], 4)
        self.assertEqual([step["layer"] for step in lineage["trajectory"]], ["bronze", "silver", "curia", "gold"])
        self.assertEqual(lineage["row_refs"]["provider"], "vast")
        self.assertEqual(lineage["provider_runs"][0]["raw_ref"], f"{raw_root}/provider=vast/date=2026-06-17/run_id=vast-operator/offers.json")
        self.assertIn("fact_benchmark_constituents", lineage["gold"]["table_refs"])
        self.assertEqual(preview["kind"], "json")
        self.assertEqual(preview["json_summary"]["type"], "array")
        self.assertEqual(preview["json_summary"]["item_count"], 1)
        self.assertEqual(sql_preview["kind"], "sql")
        self.assertIn("fact_benchmark_constituents", sql_preview["text"])


def _offer(
    *,
    provider: str,
    source_offer_id: str,
    price_usd_hr: float,
    availability_status: str = "available",
    gpu_raw_name: str = "RTX 4090",
    gpu_model: str = "RTX4090_24GB",
    vram_gb: float = 24,
) -> GpuOffer:
    return GpuOffer(
        provider=provider,
        source_offer_id=source_offer_id,
        observed_at=OBSERVED_AT,
        gpu_raw_name=gpu_raw_name,
        gpu_model=gpu_model,
        gpu_count=1,
        vram_gb=vram_gb,
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
        self.calls.append(
            {"method": "GET", "url": url, "params": dict(params), "headers": dict(headers), "timeout": timeout}
        )
        return _FakeResponse(self.payloads[len(self.calls) - 1])

    def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
        timeout: int,
    ) -> "_FakeResponse":
        self.calls.append(
            {"method": "POST", "url": url, "json": dict(json), "headers": dict(headers), "timeout": timeout}
        )
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
