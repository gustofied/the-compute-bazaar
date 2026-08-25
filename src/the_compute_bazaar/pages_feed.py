"""Build the public Compute Bazaar feed as a GitHub Pages artifact."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from .prices.market_run import MarketRunResult, run_market_hourly


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

    prepare_pages_site(
        output_root=output,
        static_snapshot_root=static_snapshot_root,
        custom_domain=custom_domain,
    )
    return result


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
  a { color: inherit; text-underline-offset: .2em; }
</style>
<h1>The Compute Bazaar</h1>
<p>This host publishes the Bazaar's live market cards and portable public lake.</p>
<p><a href="/manifest.json">Feed manifest</a> · <a href="/lake/index.json">Public lake</a> · <a href="https://github.com/gustofied/the-compute-bazaar">Repository</a></p>
</html>
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="_site")
    parser.add_argument("--raw-root", default=".market-state/raw")
    parser.add_argument("--lake-root", default=".market-state/lake")
    parser.add_argument("--static-snapshot-root")
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
