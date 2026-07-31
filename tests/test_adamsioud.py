import hashlib
import json
import re
import unittest
from pathlib import Path

from the_compute_bazaar.adamsioud import create_app


class AdamSioudServerTests(unittest.TestCase):
    def test_compute_article_is_the_public_exemplar_entry(self) -> None:
        site_root = Path("external/AdamSioud")
        home = (site_root / "index.html").read_text(encoding="utf-8")
        exemplars = (site_root / "exemplars/exemplars.html").read_text(encoding="utf-8")
        article = (site_root / "exemplars/compute/feeling_the_compute.html").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'href="exemplars/compute/feeling_the_compute.html"',
            home,
        )
        self.assertIn(
            'href="compute/feeling_the_compute.html"',
            exemplars,
        )
        self.assertNotIn('href="exemplars/compute-bazaar/"', home)
        self.assertNotIn('href="compute-bazaar/"', exemplars)
        self.assertNotIn("noindex,nofollow", article)
        self.assertIn(
            'rel="canonical" href="https://www.adamsioud.com/'
            'exemplars/compute/feeling_the_compute.html"',
            article,
        )

    def test_compute_article_masthead_uses_local_embroidery_renderer(self) -> None:
        site_root = Path("external/AdamSioud")
        article_root = site_root / "exemplars/compute"
        article = (article_root / "feeling_the_compute.html").read_text(
            encoding="utf-8"
        )
        entrypoint = (article_root / "compute-cards.source.js").read_text(
            encoding="utf-8"
        )
        renderer = (article_root / "compute-title-embroidery.js").read_text(
            encoding="utf-8"
        )
        styles = (site_root / "style.css").read_text(encoding="utf-8")
        weave = article_root / "assets/embroidery-weave.webp"

        self.assertIn("data-compute-embroidery", article)
        self.assertIn(
            'aria-label="The Compute Bazaar rendered as embroidered '
            'word-shaped patches"',
            article,
        )
        self.assertIn("setupComputeTitleEmbroidery", entrypoint)
        self.assertIn('word: "THE"', renderer)
        self.assertIn('word: "COMPUTE"', renderer)
        self.assertIn('word: "BAZAAR"', renderer)
        self.assertIn("fill: [0.569, 0.682, 0.796]", renderer)
        self.assertIn("fill: [0.718, 0.816, 0.482]", renderer)
        self.assertIn("fill: [0.953, 0.784, 0.533]", renderer)
        self.assertIn("const FABRIC = [0.937, 0.929, 0.894]", renderer)
        self.assertIn("uniform sampler2D uArt", renderer)
        self.assertIn("uniform sampler2D uField", renderer)
        self.assertIn("uniform sampler2D uWeave", renderer)
        self.assertIn("UNPACK_PREMULTIPLY_ALPHA_WEBGL", renderer)
        self.assertIn("IntersectionObserver", renderer)
        self.assertIn("requestIdleCallback", renderer)
        self.assertIn("(prefers-reduced-motion: reduce)", renderer)
        self.assertIn("alpha: true", renderer)
        self.assertIn(
            '.compute-logo-title[data-embroidery-ready="true"]',
            styles,
        )
        for index in range(1, 6):
            self.assertIn(
                f"./assets/masthead/compute-masthead-{index:02d}.webp",
                article,
            )
            self.assertTrue(
                (
                    article_root / f"assets/masthead/compute-masthead-{index:02d}.webp"
                ).is_file()
            )
        self.assertNotIn("../images/stock/logo-mercator.jpg", article)
        self.assertIn("--compute-panel-tint: #91aecb", styles)
        self.assertIn("--compute-panel-tint: #b7d07b", styles)
        self.assertIn("--compute-panel-tint: #f3c888", styles)
        self.assertIn("mix-blend-mode: multiply", styles)
        self.assertIn("0 0 0 2px #efede4", styles)
        self.assertTrue(weave.is_file())
        self.assertEqual(
            hashlib.sha256(weave.read_bytes()).hexdigest(),
            "b9e5bde9c84106518abc183e9cc3ccf799aad9190b94c725a64c2e6c2237f5ab",
        )

    def test_clean_article_cards_read_versioned_public_gold_contracts(self) -> None:
        article_root = Path("external/AdamSioud/exemplars/compute")
        article = (article_root / "feeling_the_compute.html").read_text(
            encoding="utf-8"
        )
        gpu_source = (article_root / "gpu-index-card.source.js").read_text(
            encoding="utf-8"
        )
        sandbox_source = (article_root / "sandbox-market-card.source.js").read_text(
            encoding="utf-8"
        )
        transitions = (article_root / "card-transitions.js").read_text(encoding="utf-8")
        presentation = (article_root / "card-presentation.js").read_text(
            encoding="utf-8"
        )
        feed_source = (article_root / "compute-card-feed.js").read_text(
            encoding="utf-8"
        )
        work_source = (article_root / "compute-card-work.js").read_text(
            encoding="utf-8"
        )
        style_source = (article_root / "gpu-index-card.tailwind.css").read_text(
            encoding="utf-8"
        )
        bundle = (article_root / "compute-cards.js").read_text(encoding="utf-8")
        styles = (article_root / "compute-card.css").read_text(encoding="utf-8")
        package = json.loads(
            Path("external/AdamSioud/package.json").read_text(encoding="utf-8")
        )

        self.assertIn('id="gpu-benchmark-card"', article)
        self.assertIn('id="sandbox-benchmark-card"', article)
        self.assertIn('id="relative-market-card"', article)
        self.assertIn("data-gpu-benchmark-card", article)
        self.assertIn("data-sandbox-benchmark-card", article)
        self.assertIn("data-relative-market-card", article)
        self.assertIn('data-index-panel="cover"', article)
        self.assertIn('data-index-panel="detail"', article)
        self.assertIn('data-index-panel="work"', article)
        self.assertIn('data-index-panel="share"', article)
        self.assertIn('data-story-panel="cover"', article)
        self.assertIn('data-story-panel="detail"', article)
        self.assertEqual(article.count('data-story-panel="work"'), 2)
        self.assertEqual(article.count('data-story-panel="share"'), 2)
        self.assertIn("compute-card-rail", article)
        self.assertEqual(article.count("data-story-cover"), 2)
        self.assertIn("data-index-cover", article)
        self.assertEqual(article.count("story-index-share__window"), 2)
        self.assertNotIn("data-share-native", article)
        self.assertNotIn("data-story-share-native", article)
        self.assertIn("data-share-copy-link", article)
        self.assertIn("data-story-copy-link", article)
        self.assertNotIn("Publication link", article)
        self.assertIn("Copied. Ready to share.", gpu_source)
        self.assertIn("payload?.publication?.ranges", gpu_source)
        self.assertIn("publication?.display_line", gpu_source)
        self.assertIn("getPublicationUrl", sandbox_source)
        self.assertIn("publication?.states", sandbox_source)
        self.assertIn("display_line", sandbox_source)
        self.assertIn("data-share-artifact-svg", article)
        self.assertIn("data-story-share-artifact-svg", article)
        self.assertEqual(article.count("data-index-work"), 2)
        self.assertEqual(article.count("data-story-work"), 4)
        self.assertEqual(article.count("data-work-rows"), 3)
        self.assertNotIn("data-work-inspector", article)
        self.assertNotIn("data-work-copy-endpoint", article)
        self.assertNotIn("data-work-open-endpoint", article)
        self.assertEqual(article.count("data-work-endpoint"), 3)
        self.assertNotIn("compute-api-card", article)
        self.assertNotIn("data-share-api-url", article)
        self.assertNotIn("data-story-share-api-url", article)
        self.assertNotIn("gpu-index-detail__header", article)
        self.assertNotIn("story-index-detail__header", article)
        self.assertNotIn(">Front<", article.replace("\n", ""))
        self.assertIn(
            "https://bazaar.adamsioud.com/gpu-benchmark/h100.json",
            article,
        )
        self.assertIn(
            "https://bazaar.adamsioud.com/sandbox/rates.json",
            article,
        )
        self.assertIn(
            "https://bazaar.adamsioud.com/sandbox/relative.json",
            article,
        )
        self.assertIn("data-workload-history-summary", article)
        self.assertIn("data-workload-history-note", article)
        self.assertIn("compute-ledger compute-ledger--scroll", article)
        self.assertIn("data-sandbox-rate-count", article)
        self.assertIn(
            'aria-label="Current public sandbox rates. Scroll to review every '
            'source and billing basis."',
            article,
        )
        self.assertIn(
            "`${rows.length} ${plural(rows.length, \"source\")} · scroll`",
            sandbox_source,
        )
        self.assertIn(".compute-ledger--scroll ol", style_source)
        self.assertIn("max-height: 126px;", style_source)
        self.assertIn("overscroll-behavior: contain;", style_source)
        self.assertIn("scrollbar-gutter: stable;", style_source)
        self.assertIn("function configureRateLedger()", sandbox_source)
        self.assertIn('event.key === "Home" || event.key === "End"', sandbox_source)
        self.assertIn("nodes.rateTable.scrollBy", sandbox_source)
        self.assertNotIn("Seven matching source runs over five calendar days", article)
        self.assertIn("Every complete aligned job", article)
        self.assertNotIn("Provider-floor median", article)
        self.assertNotIn("Median line · provider-floor p25–p75 band", article)
        self.assertNotIn("benchmark-methodology.md", article)
        self.assertNotIn("benchmark-constituents.json", article)
        self.assertNotIn("27 providers · 27 eligible prices", article)
        self.assertIn('src="./compute-cards.js?v=19"', article)
        self.assertIn('href="./compute-card.css?v=25"', article)
        self.assertIn("family=Geist:wght@400;500;600", article)
        self.assertEqual(article.count("data-card-feed="), 3)
        self.assertEqual(article.count('class="compute-card-prose"'), 3)
        self.assertEqual(article.count("data-gpu-family-value="), 4)
        self.assertIn("data-card-feed-track", article)
        self.assertIn("gpu-index-share__window", article)
        self.assertIn("createCardFeed", gpu_source)
        self.assertIn("visibleSeries", gpu_source)
        self.assertIn("pointRows", gpu_source)
        self.assertIn(".domain([0, maximum * 1.08])", gpu_source)
        self.assertIn("createCardFeed", sandbox_source)
        self.assertIn("updateWorkloadHistoryCopy", sandbox_source)
        self.assertIn("workload.source_batch_count", sandbox_source)
        self.assertIn("workload.calendar_day_count", sandbox_source)
        self.assertIn('import { animate } from "motion"', feed_source)
        self.assertIn("(prefers-reduced-motion: reduce)", feed_source)
        self.assertIn('root.addEventListener("pointerenter", pause)', feed_source)
        self.assertIn('root.addEventListener("focusin", pause)', feed_source)
        self.assertIn('document.addEventListener("visibilitychange"', feed_source)
        self.assertIn(
            "createCardFeed(root, { links = false } = {})",
            feed_source,
        )
        self.assertIn('row.rel = "noopener noreferrer"', feed_source)
        self.assertNotIn("width: min(100vw, 1600px);", style_source)
        self.assertIn("pointer-events: none;", style_source)
        self.assertEqual(article.count('width="600"'), 6)
        self.assertEqual(article.count('height="600"'), 6)
        for name, digest in {
            "gpu-index-dither.webp": (
                "8c4ba250a1861bde7015bfa7f68fc753de99735fbf7c5f660e0d0a672d1ccdaa"
            ),
            "rate-movement-dither.webp": (
                "f48c8d6542743502a356317e0ab4a70102a0aa6dd770ff47797f9c0f3acbda3c"
            ),
            "sandbox-cost-dither.webp": (
                "d145572ca7246b1f5e122602e082940da732e84082ef7b2f8e0b5e59f58efc71"
            ),
        }.items():
            asset = article_root / "assets/work" / name
            self.assertTrue(asset.is_file())
            self.assertEqual(hashlib.sha256(asset.read_bytes()).hexdigest(), digest)
        self.assertNotIn("gpu-benchmark-card.js", article)
        self.assertNotIn("compute-card-motion.js", article)
        self.assertIn('import * as d3 from "d3"', gpu_source)
        self.assertIn('import * as d3 from "d3"', sandbox_source)
        self.assertIn('import * as d3 from "d3"', work_source)
        self.assertIn('import { animate } from "motion"', transitions)
        self.assertIn('import { animate } from "motion"', work_source)
        self.assertIn("createCardWork", gpu_source)
        self.assertIn("createCardWork", sandbox_source)
        self.assertIn("export function createCardWork", work_source)
        self.assertIn('attr("role", "slider")', work_source)
        self.assertIn("compute-work-row__position", work_source)
        self.assertIn("circularOffset", work_source)
        self.assertEqual(article.count("data-work-position"), 3)
        self.assertNotIn("Market observer 01", gpu_source)
        self.assertNotIn("Market observer 01", sandbox_source)
        self.assertNotIn("data-work-row-toggle", work_source)
        self.assertNotIn('setAttribute("role", "tab")', work_source)
        self.assertNotIn("renderInspector", work_source)
        self.assertNotIn("copyTextToClipboard", work_source)
        self.assertIn("AUTO_ADVANCE_MS = 2600", work_source)
        self.assertIn("renderSignal", work_source)
        self.assertNotIn("Publish Gold JSON", gpu_source)
        self.assertNotIn("Publish Gold JSON", sandbox_source)
        self.assertNotIn("public JSON", article)
        self.assertIn(
            'button.addEventListener("click", () => showPanel("share", true))',
            gpu_source,
        )
        self.assertIn(
            'button.addEventListener("click", () => showPanel("share", true))',
            sandbox_source,
        )
        self.assertIn("compute_bazaar_card_v1", gpu_source)
        self.assertIn("compute_bazaar_card_v1", sandbox_source)
        self.assertIn('payload?.card_type !== "gpu_benchmark"', gpu_source)
        self.assertIn('"compute_rate_market"', sandbox_source)
        self.assertIn('"sandbox_workload"', sandbox_source)
        self.assertIn('"compute_relative_prices"', sandbox_source)
        self.assertIn("payload.series", gpu_source)
        self.assertIn("row?.lower === null", gpu_source)
        self.assertIn("row?.upper === null", gpu_source)
        self.assertIn('toggleAttribute("inert"', gpu_source)
        self.assertIn('toggleAttribute("inert"', sandbox_source)
        self.assertIn("swapCardPanels", transitions)
        self.assertIn("bindCardCover", transitions)
        self.assertIn("settledPanelHeight", transitions)
        self.assertIn("await onPrepare?.()", transitions)
        self.assertIn("previous.offsetHeight", transitions)
        self.assertIn("panel.offsetHeight", transitions)
        self.assertIn("heightDelta", transitions)
        self.assertIn("duration = Math.min(0.48", transitions)
        self.assertIn("const ease = [0.32, 0.72, 0, 1]", transitions)
        self.assertIn("height: [`${fromHeight}px`, `${toHeight}px`]", transitions)
        self.assertIn("rotateY", transitions)
        self.assertNotIn("shareSvgAsPng", transitions)
        self.assertIn("copyTextToClipboard", transitions)
        self.assertIn('document.execCommand("copy")', transitions)
        self.assertNotIn('type: "image/png"', transitions)
        self.assertIn('url.searchParams.set("present", "card")', presentation)
        self.assertIn('url.searchParams.set("view", "share")', presentation)
        self.assertIn("setupStandaloneCardPresentation", presentation)
        self.assertIn("./assets/munch-the-sun.webp", presentation)
        self.assertIn("Return to The Compute Bazaar article", presentation)
        self.assertIn("MM.M.00822", presentation)
        self.assertIn("articleReturnUrl", presentation)
        self.assertIn('articleUrl.searchParams.set("view", "detail")', presentation)
        self.assertIn("compute-card-presentation__flip", presentation)
        self.assertIn("syncFlipControl", presentation)
        self.assertNotIn("event.stopImmediatePropagation()", presentation)
        self.assertIn("event.clientX - bounds.left", gpu_source)
        self.assertIn("event.clientX - bounds.left", sandbox_source)
        self.assertIn("latest_replicate_count", sandbox_source)
        self.assertIn("source_replicate_slot_count", sandbox_source)
        self.assertNotIn('title: "SAME SOFTWARE JOB"', sandbox_source)
        self.assertIn('title: ""', sandbox_source)
        self.assertIn("gpu-benchmark/h100.json", article)
        self.assertNotIn("statistics", gpu_source)
        self.assertNotIn("statistics", sandbox_source)
        self.assertNotIn("Math.min(...", gpu_source)
        self.assertGreater(len(bundle), 150_000)
        self.assertEqual(package["dependencies"]["motion"], "12.42.2")
        self.assertEqual(package["dependencies"]["d3"], "7.9.0")
        self.assertIn("build:compute", package["scripts"])
        self.assertFalse((article_root / "gpu-index-card.js").exists())
        self.assertFalse((article_root / "gpu-benchmark-card.js").exists())
        self.assertFalse((article_root / "compute-card.js").exists())
        self.assertFalse((article_root / "compute-card-motion.js").exists())
        self.assertIn(".gpu-benchmark__band", styles)
        self.assertIn(".gpu-benchmark__line", styles)
        self.assertIn(".gpu-benchmark__line.is-context", styles)
        self.assertIn(".gpu-benchmark__line.is-selected", styles)
        self.assertIn(".gpu-benchmark__tooltip", styles)
        self.assertIn(".gpu-benchmark__tooltip-row", styles)
        self.assertIn(".gpu-index-cover", styles)
        self.assertIn(".gpu-index-share__window", styles)
        self.assertIn(".story-index-share__window", styles)
        self.assertIn(".compute-card-rail", styles)
        self.assertIn(".compute-share-artifact", styles)
        self.assertIn(".compute-work-card", styles)
        self.assertIn(".compute-work-card__surface", styles)
        self.assertIn(".compute-work-row", styles)
        self.assertIn(".compute-work-signal", styles)
        self.assertNotIn(".compute-work-inspector", styles)
        self.assertNotIn(".compute-work-endpoint", styles)
        self.assertIn(".compute-share-card-frame", styles)
        self.assertNotIn(".compute-api-card", styles)
        self.assertIn("data-compute-card-presentation=standalone", styles)
        self.assertIn(".compute-card-presentation__backdrop", styles)
        self.assertIn(".compute-card-presentation__credit", styles)
        self.assertNotIn(".gpu-share-card", styles)
        self.assertIn(".story-index-cover", styles)
        self.assertIn(".story-index-detail", styles)
        self.assertNotIn(".story-share-card", styles)
        self.assertIn(".sandbox-workload__job", styles)
        self.assertIn(".relative-market__line.is-gpu", styles)
        self.assertIn("--index-azure:#91aecb", styles)
        self.assertIn("--index-linen:#efede4", styles)
        self.assertIn("--story-accent:#b7d07b", styles)
        self.assertIn("--story-accent:#f3c888", styles)

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
        viz_script = (article_root / "compute-viz.js").read_text(encoding="utf-8")
        viz_styles = (article_root / "compute-viz.css").read_text(encoding="utf-8")
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
            {row["measurement_kind"] for row in market_state["current_rows"]},
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
        self.assertEqual(payload["workload"]["source_batch_count"], 8)
        self.assertEqual(payload["workload"]["fixed_service_count"], 6)
        self.assertEqual(payload["workload"]["complete_run_count"], 4)
        self.assertEqual(len(payload["workload"]["run_history"]), 8)
        self.assertEqual(payload["workload"]["calendar_day_count"], 6)
        self.assertEqual(payload["workload"]["methodology_generation_count"], 7)
        self.assertEqual(payload["workload"]["latest_replicate_count"], 72)
        self.assertEqual(
            payload["workload"]["latest_source_replicate_slot_count"],
            12,
        )
        self.assertEqual(
            payload["workload"]["latest_incomplete_replicate_count"],
            0,
        )
        self.assertEqual(payload["workload"]["latest_phase_count"], 720)
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
        self.assertEqual(len(payload["workload"]["batch_history"]), 44)
        self.assertEqual(len(payload["workload"]["latest_replicates"]), 72)
        self.assertFalse(payload["workload"]["lifecycle_included"])
        self.assertEqual(
            payload["manifest"]["row_counts"]["compute_utilization_public_ladder"],
            5,
        )
        self.assertEqual(
            [row["stage_id"] for row in payload["utilization"]["rows"]],
            ["available", "rented", "allocated", "active", "productive"],
        )

    def test_compute_article_remains_an_editorial_prose_shell(self) -> None:
        site_root = Path("external/AdamSioud")
        shell = (
            site_root / "exemplars" / "compute" / "feeling_the_compute.html"
        ).read_text(encoding="utf-8")

        self.assertIn("Lorem ipsum", shell)
        self.assertNotIn("data-viz-card", shell)
        self.assertNotIn("compute-market.js", shell)
        self.assertNotIn("sandbox-cost.js", shell)


if __name__ == "__main__":
    unittest.main()
