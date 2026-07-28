import json
import re
import unittest
from pathlib import Path

from the_compute_bazaar.adamsioud import create_app


class AdamSioudServerTests(unittest.TestCase):
    def test_clean_article_gpu_card_reads_the_public_gold_contract(self) -> None:
        article_root = Path("external/AdamSioud/exemplars/compute")
        article = (article_root / "feeling_the_compute.html").read_text(
            encoding="utf-8"
        )
        script = (article_root / "gpu-benchmark-card.js").read_text(
            encoding="utf-8"
        )
        styles = (article_root / "compute-card.css").read_text(encoding="utf-8")

        self.assertIn('id="gpu-benchmark-card"', article)
        self.assertIn("data-gpu-benchmark-card", article)
        self.assertNotIn("Provider-floor median", article)
        self.assertNotIn("Median line · provider-floor p25–p75 band", article)
        self.assertNotIn("benchmark-methodology.md", article)
        self.assertNotIn("benchmark-constituents.json", article)
        self.assertNotIn("27 providers · 27 eligible prices", article)
        self.assertIn('src="./gpu-benchmark-card.js?v=4"', article)
        self.assertIn('src="./compute-card.js?v=5"', article)
        self.assertIn('src="./compute-card-motion.js?v=2"', article)
        self.assertIn("compute_bazaar_card_v1", script)
        self.assertIn('payload?.card_type !== "gpu_benchmark"', script)
        self.assertIn("payload.series", script)
        self.assertIn("row?.lower === null", script)
        self.assertIn("row?.upper === null", script)
        self.assertIn("root.dataset.cardShareState", script)
        self.assertNotIn("statistics", script)
        self.assertNotIn("Math.min(...", script)
        share_script = (article_root / "compute-card.js").read_text(
            encoding="utf-8"
        )
        motion_script = (article_root / "compute-card-motion.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("remapCloneIds", share_script)
        self.assertIn("data-share-portrait", share_script)
        self.assertIn('toggleAttribute("inert"', share_script)
        self.assertIn("motion@12.42.2", motion_script)
        self.assertIn("compute-card:flip", motion_script)
        self.assertIn("rotateY", motion_script)
        self.assertIn(".gpu-benchmark__band", styles)
        self.assertIn(".gpu-benchmark__line", styles)
        self.assertIn(".gpu-benchmark__tooltip", styles)
        self.assertIn(".compute-share-card__front", styles)
        self.assertIn(".compute-share-card__back", styles)

    def test_publication_server_registers_site_and_snapshot_routes(self) -> None:
        app = create_app(site_dir=Path("external/AdamSioud"), snapshot_source="local")
        paths = {getattr(route, "path", "") for route in app.routes}

        self.assertIn("/api/health", paths)
        self.assertIn("/api/dashboard-snapshots/{filename:path}", paths)
        self.assertIn("/api/snapshots/{name}", paths)
        self.assertIn("/", paths)
        home = next(route for route in app.routes if route.path == "/")
        health = next(route for route in app.routes if route.path == "/api/health")
        self.assertEqual(
            home.endpoint().headers["location"],
            "/exemplars/compute-bazaar/",
        )
        self.assertEqual(
            health.endpoint()["compute_page"],
            "/exemplars/compute-bazaar/",
        )

    def test_compute_bazaar_surface_contains_the_maintained_views(self) -> None:
        article_root = Path("external/AdamSioud/exemplars/compute-bazaar")
        article = (article_root / "index.html").read_text(encoding="utf-8")
        script = (article_root / "sandbox-cost.js").read_text(encoding="utf-8")
        viz_script = (article_root / "compute-viz.js").read_text(
            encoding="utf-8"
        )
        viz_styles = (article_root / "compute-viz.css").read_text(
            encoding="utf-8"
        )
        history_script = (article_root / "compute-market-history.js").read_text(
            encoding="utf-8"
        )
        prime_frontier_script = (article_root / "prime-frontier-market.js").read_text(
            encoding="utf-8"
        )
        payload = json.loads(
            (article_root / "sandbox-cost.json").read_text(encoding="utf-8")
        )
        market_state = json.loads(
            (article_root / "market-state.json").read_text(encoding="utf-8")
        )

        self.assertIn("data-sandbox-cost", article)
        self.assertIn(
            "Four vCPUs and 8 GiB, before and after the sandbox layer",
            article,
        )
        self.assertIn(
            "What the same software job costs on each sandbox",
            article,
        )
        self.assertIn(
            "Price, available capacity, and one measured software job",
            article,
        )
        self.assertIn('data-pulse-window="1d"', article)
        self.assertIn('data-pulse-window="7d"', article)
        self.assertIn('data-pulse-window="1m"', article)
        self.assertIn('data-pulse-window="all"', article)
        self.assertIn('id="market-pulse-gpu-price-chart"', article)
        self.assertIn('id="market-pulse-gpu-availability-chart"', article)
        self.assertIn('id="market-pulse-cpu-price-chart"', article)
        self.assertIn('id="market-pulse-cpu-availability-chart"', article)
        self.assertIn('id="market-pulse-sandbox-cost-chart"', article)
        self.assertIn('id="market-pulse-sandbox-runtime-chart"', article)
        self.assertIn("Estimated cost of the same job", article)
        self.assertIn("Cost ranking", article)
        self.assertNotIn('data-job-metric="time"', article)
        self.assertNotIn('data-job-metric="cost"', article)
        self.assertIn("Inspect the seven underlying VM offers", article)
        self.assertIn("Public VM/VPS and managed sandbox prices", article)
        self.assertIn("Rates behind the sandbox median", article)
        self.assertIn('id="sandbox-vendor-chart"', article)
        self.assertIn("all seven VM offers", article)
        self.assertIn('data-relative-series="gpu"', article)
        self.assertIn('data-relative-series="vm"', article)
        self.assertIn('data-relative-series="sandbox"', article)
        self.assertIn('data-occupancy-provider="akash"', article)
        self.assertIn('data-occupancy-provider="clore"', article)
        self.assertIn('data-occupancy-window="1d"', article)
        self.assertIn('data-occupancy-window="7d"', article)
        self.assertIn('data-occupancy-window="1m"', article)
        self.assertIn('data-occupancy-window="all"', article)
        self.assertIn('id="sandbox-job-scatter"', article)
        self.assertIn('id="sandbox-phase-summary"', article)
        self.assertIn('id="sandbox-batch-table-body"', article)
        self.assertIn('id="sandbox-combined-chart"', article)
        self.assertIn('id="sandbox-coverage-chart"', article)
        self.assertIn('id="market-state-current"', article)
        self.assertIn('id="market-occupancy-chart"', article)
        self.assertIn('id="market-state-availability"', article)
        self.assertIn("data-prime-frontier-market", article)
        self.assertIn('id="prime-frontier-reference-chart"', article)
        self.assertIn('id="prime-frontier-ladder"', article)
        for family in ["H100", "H200", "B200", "B300"]:
            self.assertIn(f'data-prime-product="{family}"', article)
        self.assertIn("more weight for listing more machine shapes", article)
        self.assertIn("fills, cancellations", article)
        self.assertNotIn('id="vm-hourly-chart"', article)
        self.assertNotIn('id="sandbox-batch-history"', article)
        self.assertIn('href="./compute-viz.css?v=5"', article)
        self.assertIn('src="./compute-viz.js?v=7"', article)
        self.assertIn('src="./compute-market.js?v=12"', article)
        self.assertIn('src="./compute-market-history.js?v=9"', article)
        self.assertIn('src="./prime-frontier-market.js?v=4"', article)
        self.assertIn('src="./sandbox-cost.js?v=28"', article)
        self.assertEqual(article.count("data-viz-card"), 14)
        for status_label in {
            "Hourly benchmark history",
            "Hourly seven-vendor cohort",
            "Latest compatible StarSling run",
            "Dated public rate-card evidence",
            "Observed marketplace capacity",
        }:
            self.assertIn(f'data-viz-status-label="{status_label}"', article)
        self.assertEqual(
            len(re.findall(r'\bid="([^"]+)"', article)),
            len(set(re.findall(r'\bid="([^"]+)"', article))),
        )
        for card_id in {
            "gpu-price-card",
            "prime-frontier-market-card",
            "gpu-price-pulse-card",
            "gpu-availability-pulse-card",
            "cpu-price-pulse-card",
            "cpu-availability-pulse-card",
            "sandbox-cost-pulse-card",
            "sandbox-runtime-pulse-card",
            "vm-sandbox-price-card",
            "sandbox-vendor-rate-card",
            "sandbox-job-cost-card",
            "relative-price-card",
            "gpu-coverage-card",
            "market-occupancy-card",
        }:
            self.assertIn(f'id="{card_id}"', article)
        self.assertIn("window.ComputeViz", viz_script)
        self.assertIn("effectiveCssZoom", viz_script)
        self.assertIn("localPointer", viz_script)
        self.assertIn("positionTooltip", viz_script)
        self.assertIn("resolveDataBase", viz_script)
        self.assertIn("observe", viz_script)
        self.assertIn("cardUrl", viz_script)
        self.assertIn("embedCode", viz_script)
        self.assertIn("embedHeight", viz_script)
        self.assertIn("embedUrl", viz_script)
        self.assertIn("articleUrl", viz_script)
        self.assertIn("cardLayout", viz_script)
        self.assertIn("syncCardLinks", viz_script)
        self.assertIn('"card", "embed"', viz_script)
        self.assertIn("viz-standalone-shell", viz_script)
        self.assertIn("Open expanded", viz_script)
        self.assertIn("viz-card-share-action", viz_script)
        self.assertIn(".viz-observation", viz_styles)
        self.assertIn(".viz-card-footer", viz_styles)
        self.assertIn(".viz-card-view", viz_styles)
        self.assertIn(".viz-embed-view", viz_styles)
        self.assertIn(".viz-standalone-header", viz_styles)
        self.assertNotIn("market-history-observation", history_script)
        self.assertIn('attr("role", "slider")', history_script)
        self.assertIn('attr("aria-valuenow", focusIndex)', history_script)
        self.assertIn("viz.localPointer", history_script)
        self.assertIn(
            "prime-frontier-offer-market.json",
            prime_frontier_script,
        )
        self.assertIn("viz.localPointer", prime_frontier_script)
        self.assertIn("viz.positionTooltip", prime_frontier_script)
        self.assertIn("viz.observe", prime_frontier_script)
        self.assertIn("market benchmark", prime_frontier_script)
        self.assertIn("left public availability", prime_frontier_script)
        self.assertIn("requestable", prime_frontier_script.lower())
        self.assertNotIn("traded volume", prime_frontier_script.lower())
        self.assertNotIn("remaining volume", prime_frontier_script.lower())
        self.assertIn(".market-card", viz_styles)
        self.assertIn(".offer-market-products", viz_styles)
        self.assertIn("sandbox-cost.json", script)
        self.assertIn('"sandbox_cost_gold_v5"', script)
        self.assertNotIn('"sandbox_cost_gold_v4"', script)
        self.assertNotIn("summarizeJobs", script)
        self.assertIn("renderJobRanking", script)
        self.assertNotIn("activeMetric", script)
        self.assertNotIn("sandbox-job-view-note", script)
        self.assertIn("workload.service_summary", script)
        self.assertNotIn("function effectiveCssZoom", script)
        self.assertNotIn("function localPointer", script)
        self.assertIn("viz.localPointer", script)
        self.assertIn("viz.positionTooltip", script)
        self.assertIn("viz.observe", script)
        self.assertIn('attr("aria-valuenow", focusIndex)', script)
        self.assertIn("compute-viz:layout", script)
        self.assertNotIn('label: "Source-backed data loaded"', script)
        self.assertIn("createRateHistoryChart", script)
        self.assertIn("createSandboxVendorChart", script)
        self.assertIn("sandbox-vendor-series", script)
        self.assertIn("keyChangeRows", script)
        self.assertNotIn("const pointRows", script)
        self.assertIn("partial source check", script)
        self.assertIn("latest complete", script)
        self.assertIn('id="vm-current-rates"', article)
        self.assertIn('id="vm-marketplace-rates"', article)
        self.assertIn('id="vm-capacity-table-body"', article)
        self.assertIn("createJobDistributionChart", script)
        self.assertIn("renderMarketStateSummary", script)
        self.assertIn("createMarketPulse", script)
        self.assertIn("workloadRunHistory", script)
        self.assertIn("fixedCohortComplete", script)
        self.assertIn("createMarketOccupancyChart", script)
        self.assertIn("sandbox-capacity-total", script)
        self.assertIn("data-occupancy-window", article)
        self.assertIn("windowConfig.milliseconds", script)
        self.assertIn("base_100", script)
        self.assertIn("market-state.json", script)
        self.assertEqual(
            market_state["schema_version"],
            "compute_market_state_public_v1",
        )
        self.assertEqual(
            market_state["current_row_count"],
            len(market_state["current_rows"]),
        )
        self.assertEqual(
            market_state["history_row_count"],
            len(market_state["history_rows"]),
        )
        self.assertEqual(
            {
                row["measurement_kind"]
                for row in market_state["current_rows"]
            },
            {"rental_occupancy", "availability_pressure"},
        )
        self.assertTrue(
            all(
                row["measurement_kind"] == "rental_occupancy"
                and row["resource_type"]
                in {
                    "ALL_GPU",
                    "ALL_CPU",
                    "ALL_MEMORY",
                    "ALL_STORAGE",
                    "ALL_EPHEMERAL_STORAGE",
                    "ALL_PERSISTENT_STORAGE",
                }
                for row in market_state["history_rows"]
            )
        )
        self.assertIn(
            "ALL_GPU",
            {row["resource_type"] for row in market_state["history_rows"]},
        )
        self.assertNotIn("raw_ref", json.dumps(market_state))
        self.assertNotIn("s3://", json.dumps(market_state))
        self.assertEqual(
            payload["manifest"]["manifest_version"],
            "sandbox_cost_gold_v5",
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["vm_capacity_current"],
            4,
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["vm_capacity_expanded_rate"],
            len(payload["vm_capacity"]["fixed_cohort_rate"]),
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["vm_capacity_fixed_rate"],
            len(payload["vm_capacity"]["legacy_fixed_cohort_rate"]),
        )
        self.assertGreaterEqual(
            payload["manifest"]["row_counts"]["vm_capacity_observed_rate"],
            2,
        )
        self.assertTrue(
            all(
                {
                    "base_observed_at",
                    "base_median_usd_per_hour",
                    "base_100",
                    "p25_base_100",
                    "p75_base_100",
                    "minimum_base_100",
                    "maximum_base_100",
                }.issubset(row)
                for row in payload["vm_capacity"]["observed_market_rate"]
            )
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["vm_capacity_expanded_current"],
            7,
        )
        self.assertEqual(
            len(payload["vm_capacity"]["current_cross_section"]),
            7,
        )
        self.assertEqual(len(payload["vm_capacity"]["marketplace_indications"]), 1)
        self.assertNotIn(
            "raw_refs_json",
            json.dumps(payload["vm_capacity"]),
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["sandbox_hourly_price_series"],
            33,
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["sandbox_price_events"],
            10,
        )
        coverage_count = payload["manifest"]["row_counts"]["gpu_h100_daily_coverage"]
        eligible_count = payload["manifest"]["row_counts"]["gpu_h100_eligible_history"]
        self.assertGreaterEqual(coverage_count, 37)
        self.assertEqual(
            coverage_count,
            len(payload["combined"]["coverage_history"]),
        )
        self.assertGreaterEqual(eligible_count, 30)
        self.assertEqual(
            payload["manifest"]["row_counts"]["sandbox_gpu_cpu_common_start"],
            eligible_count,
        )
        self.assertEqual(len(payload["combined"]["rows"]), eligible_count)
        self.assertEqual(payload["workload"]["source_batch_count"], 7)
        self.assertEqual(payload["workload"]["fixed_service_count"], 6)
        self.assertEqual(payload["workload"]["complete_run_count"], 3)
        self.assertEqual(len(payload["workload"]["run_history"]), 7)
        self.assertEqual(payload["workload"]["calendar_day_count"], 5)
        self.assertEqual(payload["workload"]["methodology_generation_count"], 6)
        self.assertEqual(payload["workload"]["latest_replicate_count"], 69)
        self.assertEqual(
            payload["workload"]["latest_source_replicate_slot_count"],
            12,
        )
        self.assertEqual(
            payload["workload"]["latest_incomplete_replicate_count"],
            3,
        )
        self.assertEqual(payload["workload"]["latest_phase_count"], 690)
        self.assertEqual(len(payload["workload"]["service_summary"]), 6)
        self.assertTrue(
            all(
                {
                    "median_runtime_seconds",
                    "p25_runtime_seconds",
                    "p75_runtime_seconds",
                    "median_estimated_cost_usd",
                    "p25_estimated_cost_usd",
                    "p75_estimated_cost_usd",
                }.issubset(row)
                for row in payload["workload"]["service_summary"]
            )
        )
        self.assertEqual(len(payload["workload"]["phase_summary"]), 60)
        self.assertEqual(len(payload["workload"]["batch_history"]), 38)
        self.assertEqual(len(payload["workload"]["latest_replicates"]), 69)
        self.assertFalse(payload["workload"]["lifecycle_included"])
        self.assertEqual(
            payload["manifest"]["row_counts"][
                "compute_utilization_public_ladder"
            ],
            5,
        )
        self.assertEqual(
            [row["stage_id"] for row in payload["utilization"]["rows"]],
            ["available", "rented", "allocated", "active", "productive"],
        )

    def test_compute_article_is_a_hidden_prose_shell(self) -> None:
        site_root = Path("external/AdamSioud")
        shell = (
            site_root / "exemplars" / "compute" / "feeling_the_compute.html"
        ).read_text(encoding="utf-8")
        public_index = (site_root / "index.html").read_text(encoding="utf-8")
        exemplar_index = (
            site_root / "exemplars" / "exemplars.html"
        ).read_text(encoding="utf-8")

        self.assertIn('<meta name="robots" content="noindex,nofollow">', shell)
        self.assertIn("Lorem ipsum", shell)
        self.assertNotIn("data-viz-card", shell)
        self.assertNotIn("compute-market.js", shell)
        self.assertNotIn("sandbox-cost.js", shell)
        self.assertIn('href="exemplars/compute-bazaar/"', public_index)
        self.assertIn('href="compute-bazaar/"', exemplar_index)


if __name__ == "__main__":
    unittest.main()
