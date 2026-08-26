"""Build the public Compute Bazaar feed as a GitHub Pages artifact."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .prices.market_run import MarketRunResult, run_market_hourly
from .prices.prime_publications import publish_prime_offer_shelf_publications
from .prices.public_view_prime import prime_frontier_view
from .prices.publication_chart_common import _prime_publication_series
from .prices.sandbox_publications import publish_sandbox_workload_publication


DEFAULT_PUBLIC_BASE_URL = "https://bazaar.adamsioud.com"
DEFAULT_CUSTOM_DOMAIN = "bazaar.adamsioud.com"
PUBLIC_PROVIDERS = (
    "spheron",
    "inference_sh",
    "cloud_gpu_prices",
    "thunder_compute",
    "vultr",
    "scaleway",
    "oracle_cloud",
    "ovhcloud",
    "akash",
    "aws_spot",
    "azure",
    "runpod",
)


def build_pages_feed(
    *,
    output_root: str,
    raw_root: str,
    lake_root: str,
    static_snapshot_root: str | None = None,
    publication_archive_root: str | None = None,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
    custom_domain: str = DEFAULT_CUSTOM_DOMAIN,
    providers: tuple[str, ...] = PUBLIC_PROVIDERS,
    minimum_successful_providers: int = 3,
) -> MarketRunResult:
    """Run the public market pipeline and prepare a deployable Pages site."""
    output = Path(output_root)
    if output.resolve() in {Path.cwd().resolve(), Path(output.anchor).resolve()}:
        raise ValueError("output_root must be a dedicated build directory")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    _restore_publication_archive(
        output=output,
        publication_archive_root=publication_archive_root,
    )

    previous_base_url = os.environ.get("COMPUTE_BAZAAR_PUBLIC_BASE_URL")
    os.environ["COMPUTE_BAZAAR_PUBLIC_BASE_URL"] = public_base_url
    try:
        result = run_market_hourly(
            raw_root=raw_root,
            lake_root=lake_root,
            dashboard_output_root=str(output),
            providers=list(providers),
            minimum_successful_providers=minimum_successful_providers,
        )
    finally:
        if previous_base_url is None:
            os.environ.pop("COMPUTE_BAZAAR_PUBLIC_BASE_URL", None)
        else:
            os.environ["COMPUTE_BAZAAR_PUBLIC_BASE_URL"] = previous_base_url

    _publish_snapshot_fallbacks(
        output=output,
        static_snapshot_root=static_snapshot_root,
        public_base_url=public_base_url,
    )

    prepare_pages_site(
        output_root=output,
        static_snapshot_root=static_snapshot_root,
        custom_domain=custom_domain,
    )
    _save_publication_archive(
        output=output,
        publication_archive_root=publication_archive_root,
    )
    return result


def _restore_publication_archive(
    *, output: Path, publication_archive_root: str | Path | None
) -> None:
    if publication_archive_root is None:
        return
    archive = Path(publication_archive_root)
    if not archive.exists():
        return
    shutil.copytree(archive, output / "publications", dirs_exist_ok=True)


def _save_publication_archive(
    *, output: Path, publication_archive_root: str | Path | None
) -> None:
    if publication_archive_root is None:
        return
    publications = output / "publications"
    if not publications.exists():
        return
    archive = Path(publication_archive_root)
    archive.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publications, archive, dirs_exist_ok=True)


def _publish_snapshot_fallbacks(
    *,
    output: Path,
    static_snapshot_root: str | Path | None,
    public_base_url: str,
) -> None:
    """Fill publication gaps without replacing the live analytical feed."""
    if static_snapshot_root is None:
        return
    snapshots = Path(static_snapshot_root)
    if not snapshots.exists():
        return
    _publish_prime_snapshot_fallback(
        output=output,
        snapshots=snapshots,
        public_base_url=public_base_url,
    )
    _publish_sandbox_snapshot(
        output=output,
        snapshots=snapshots,
        public_base_url=public_base_url,
    )


def _publish_prime_snapshot_fallback(
    *, output: Path, snapshots: Path, public_base_url: str
) -> None:
    collection_path = output / "prime-frontier-offer-shelf.json"
    fallback_path = snapshots / "prime-frontier-offer-shelf.json"
    if not collection_path.exists() or not fallback_path.exists():
        return
    collection = _read_json(collection_path)
    fallback = _read_json(fallback_path)
    fallback_products = {
        str(product.get("family_id") or "").upper(): product
        for product in fallback.get("products", [])
        if isinstance(product, dict)
    }
    cards: dict[str, dict[str, Any]] = {}
    for family in ("H100", "H200"):
        live_card_path = output / "prime-frontier" / f"{family.lower()}.json"
        live_card = _read_json(live_card_path) if live_card_path.exists() else {}
        if _prime_publication_series(live_card):
            cards[family] = live_card
            continue
        product = fallback_products.get(family)
        if not product:
            cards[family] = live_card
            continue
        cards[family] = prime_frontier_view(
            manifest=fallback.get("manifest") or {},
            product=product,
            methodology=str(fallback.get("methodology") or ""),
            source=fallback.get("source") or {},
            measurement_notes=list(fallback.get("measurement_notes") or []),
        )

    if not any(_prime_publication_series(card) for card in cards.values()):
        return
    publish_prime_offer_shelf_publications(
        output_root=str(output),
        cards=cards,
        public_base_url=public_base_url,
    )
    by_family = {
        str(product.get("family_id") or "").upper(): product
        for product in collection.get("products", [])
        if isinstance(product, dict)
    }
    for family, card in cards.items():
        publication = card.get("publication")
        if not publication:
            continue
        if family in by_family:
            by_family[family]["publication"] = publication
        live_card_path = output / "prime-frontier" / f"{family.lower()}.json"
        if live_card_path.exists():
            live_card = _read_json(live_card_path)
            live_card["publication"] = publication
            _write_json(live_card_path, live_card)
    _write_json(collection_path, collection)


def _publish_sandbox_snapshot(
    *, output: Path, snapshots: Path, public_base_url: str
) -> None:
    snapshot = snapshots / "sandbox" / "workload.json"
    live = output / "sandbox" / "workload.json"
    source = live if live.exists() else snapshot
    if not source.exists():
        return
    card = _read_json(source)
    publish_sandbox_workload_publication(
        output_root=str(output),
        workload_card=card,
        public_base_url=public_base_url,
    )
    _write_json(live, card)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def prepare_pages_site(
    *,
    output_root: str | Path,
    static_snapshot_root: str | Path | None = None,
    custom_domain: str = DEFAULT_CUSTOM_DOMAIN,
) -> dict[str, int]:
    """Add Pages metadata, fallbacks, and extensionless publication routes."""
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)

    snapshot_count = _copy_static_snapshots(
        output=output,
        static_snapshot_root=static_snapshot_root,
    )
    route_count = _write_pretty_publication_routes(output)

    (output / ".nojekyll").touch()
    (output / "CNAME").write_text(f"{custom_domain}\n", encoding="utf-8")
    (output / "index.html").write_text(_landing_page(), encoding="utf-8")
    return {
        "static_snapshot_count": snapshot_count,
        "pretty_publication_route_count": route_count,
    }


def _copy_static_snapshots(
    *, output: Path, static_snapshot_root: str | Path | None
) -> int:
    if static_snapshot_root is None:
        return 0
    source = Path(static_snapshot_root)
    if not source.exists():
        return 0

    destination = output / "api" / "dashboard-snapshots"
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return sum(1 for path in source.rglob("*") if path.is_file())


def _write_pretty_publication_routes(output: Path) -> int:
    publications = output / "publications"
    if not publications.exists():
        return 0

    count = 0
    for source in tuple(publications.rglob("*.html")):
        destination = source.with_suffix("") / "index.html"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        count += 1
    return count


def _landing_page() -> str:
    return """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Compute Bazaar · Public Feed</title>
<style>
  :root { color-scheme: light; font-family: ui-monospace, SFMono-Regular, monospace; }
  body { max-width: 42rem; margin: 12vh auto; padding: 0 1.5rem; color: #17354c; }
  h1 { font-size: clamp(1.8rem, 7vw, 3.8rem); letter-spacing: -.05em; }
  p { line-height: 1.65; color: #526777; }
  nav { display: flex; flex-wrap: wrap; gap: .5rem 1.5rem; }
  a { color: inherit; text-underline-offset: .2em; }
</style>
<h1>The Compute Bazaar</h1>
<p>This host publishes the Bazaar's live market cards and portable public lake.</p>
<nav aria-label="Public feed links">
  <a href="/manifest.json">Feed manifest</a>
  <a href="/lake/index.json">Public lake</a>
  <a href="https://github.com/gustofied/the-compute-bazaar">Repository</a>
</nav>
</html>
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="_site")
    parser.add_argument("--raw-root", default=".market-state/raw")
    parser.add_argument("--lake-root", default=".market-state/lake")
    parser.add_argument("--static-snapshot-root")
    parser.add_argument("--publication-archive-root")
    parser.add_argument("--public-base-url", default=DEFAULT_PUBLIC_BASE_URL)
    parser.add_argument("--custom-domain", default=DEFAULT_CUSTOM_DOMAIN)
    parser.add_argument("--minimum-successful-providers", type=int, default=3)
    parser.add_argument("--providers", nargs="+", default=list(PUBLIC_PROVIDERS))
    return parser


def main() -> None:
    args = _parser().parse_args()
    result = build_pages_feed(
        output_root=args.output_root,
        raw_root=args.raw_root,
        lake_root=args.lake_root,
        static_snapshot_root=args.static_snapshot_root,
        publication_archive_root=args.publication_archive_root,
        public_base_url=args.public_base_url,
        custom_domain=args.custom_domain,
        providers=tuple(args.providers),
        minimum_successful_providers=args.minimum_successful_providers,
    )
    print(
        f"Published {result.market_run_id}: "
        f"{len(result.successful_providers)} providers, status={result.status}"
    )


if __name__ == "__main__":
    main()
