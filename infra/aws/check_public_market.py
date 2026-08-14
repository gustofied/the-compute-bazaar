"""Fail when the public GPU market feed is stale or unusable."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any
from urllib.request import urlopen

from the_compute_bazaar.prices.publication_profiles import (
    GPU_PUBLICATION_RENDER_PROFILE,
    PRIME_PUBLICATION_RENDER_PROFILE,
    WORKLOAD_PUBLICATION_RENDER_PROFILE,
)
from the_compute_bazaar.prices.market_run import PUBLIC_MARKET_MINIMUM_PROVIDERS

GPU_FAMILIES = ("h100", "h200", "b200", "b300")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://bazaar.adamsioud.com")
    parser.add_argument("--max-age-hours", type=float, default=2.5)
    parser.add_argument("--require-provider", action="append", default=[])
    parser.add_argument("--forbid-provider", action="append", default=[])
    parser.add_argument(
        "--minimum-provider-count",
        type=int,
        default=PUBLIC_MARKET_MINIMUM_PROVIDERS,
    )
    parser.add_argument(
        "--require-renderer-revision",
        help="Fail unless every publication was rendered by this Git revision",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    market_run = _fetch_json(f"{base_url}/market-run.json")
    portable_lake = _fetch_json(f"{base_url}/lake/portable.json")
    cards = {
        family: _fetch_json(f"{base_url}/gpu-benchmark/{family}.json")
        for family in GPU_FAMILIES
    }
    gpu_publications = _fetch_json(
        f"{base_url}/publications/gpu-index/manifest.json"
    )
    prime_publications = _fetch_json(
        f"{base_url}/publications/prime-gpu-market/manifest.json"
    )
    workload_publications = _fetch_json(
        f"{base_url}/publications/sandbox-cost/manifest.json"
    )
    summary = validate_public_market(
        market_run=market_run,
        portable_lake=portable_lake,
        cards=cards,
        gpu_publications=gpu_publications,
        prime_publications=prime_publications,
        workload_publications=workload_publications,
        max_age_hours=args.max_age_hours,
        required_providers=set(args.require_provider),
        forbidden_providers=set(args.forbid_provider),
        minimum_provider_count=args.minimum_provider_count,
        required_renderer_revision=args.require_renderer_revision,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def validate_public_market(
    *,
    market_run: dict[str, Any],
    portable_lake: dict[str, Any],
    cards: dict[str, dict[str, Any]],
    gpu_publications: dict[str, Any],
    prime_publications: dict[str, Any],
    workload_publications: dict[str, Any],
    max_age_hours: float,
    required_providers: set[str],
    forbidden_providers: set[str],
    minimum_provider_count: int = PUBLIC_MARKET_MINIMUM_PROVIDERS,
    required_renderer_revision: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    observed_at = _timestamp(market_run.get("observed_at"), field="observed_at")
    age_hours = (current_time - observed_at).total_seconds() / 3600
    if age_hours < 0 or age_hours > max_age_hours:
        raise RuntimeError(
            f"Public market run is {age_hours:.2f} hours old; limit is {max_age_hours:.2f}"
        )
    if market_run.get("status") not in {"success", "warning"}:
        raise RuntimeError(f"Public market run status is {market_run.get('status')!r}")
    worker_revision = str(market_run.get("worker_revision") or "")
    if not worker_revision or worker_revision == "unknown":
        raise RuntimeError("Public market run does not identify its worker revision")
    if required_renderer_revision and worker_revision != required_renderer_revision:
        raise RuntimeError(
            f"Public market run used worker {worker_revision!r}; "
            f"expected {required_renderer_revision!r}"
        )

    market_run_id = str(market_run.get("market_run_id") or "")
    gold_run_id = str(market_run.get("gold_run_id") or "")
    if not market_run_id or gold_run_id != f"gold-{market_run_id}":
        raise RuntimeError("Public market and Gold run IDs do not align")
    if portable_lake.get("run_id") != gold_run_id:
        raise RuntimeError("Portable lake does not match the current Gold run")
    if portable_lake.get("history_mode") != "complete":
        raise RuntimeError("Portable lake does not contain complete Gold history")

    providers, failed, cohort_status = _validate_market_cohort(
        market_run,
        required_providers=required_providers,
        forbidden_providers=forbidden_providers,
        minimum_provider_count=minimum_provider_count,
    )

    for family, card in cards.items():
        card_time = _timestamp(card.get("as_of"), field=f"{family}.as_of")
        card_age_hours = (current_time - card_time).total_seconds() / 3600
        if card_age_hours < 0 or card_age_hours > max_age_hours:
            raise RuntimeError(
                f"{family.upper()} card is {card_age_hours:.2f} hours old; "
                f"limit is {max_age_hours:.2f}"
            )
        if card.get("status") not in {"live", "observed", "success"}:
            raise RuntimeError(
                f"{family.upper()} card status is {card.get('status')!r}"
            )
        card_manifest = card.get("manifest")
        if not isinstance(card_manifest, dict):
            raise RuntimeError(f"{family.upper()} card is missing its Gold manifest")
        if card_manifest.get("run_id") != gold_run_id:
            raise RuntimeError(
                f"{family.upper()} card does not match the current Gold run"
            )

    _validate_publication_manifest(
        gpu_publications,
        label="GPU",
        expected_profile=GPU_PUBLICATION_RENDER_PROFILE,
        expected_count=12,
        required_renderer_revision=required_renderer_revision,
    )
    _validate_publication_manifest(
        prime_publications,
        label="Prime",
        expected_profile=PRIME_PUBLICATION_RENDER_PROFILE,
        expected_count=2,
        required_renderer_revision=required_renderer_revision,
    )
    _validate_publication_manifest(
        workload_publications,
        label="Workload",
        expected_profile=WORKLOAD_PUBLICATION_RENDER_PROFILE,
        expected_count=1,
        required_renderer_revision=required_renderer_revision,
    )

    return {
        "market_run_id": market_run_id,
        "gold_run_id": gold_run_id,
        "portable_lake_run_id": portable_lake.get("run_id"),
        "observed_at": observed_at.isoformat(),
        "age_hours": round(age_hours, 3),
        "provider_count": len(providers),
        "failed_providers": sorted(failed),
        "cohort_status": cohort_status,
        "worker_revision": worker_revision,
        "cards": sorted(cards),
        "gpu_publication_profile": gpu_publications.get("render_profile"),
        "prime_publication_profile": prime_publications.get("render_profile"),
        "workload_publication_profile": workload_publications.get("render_profile"),
        "renderer_revisions": {
            "gpu": gpu_publications.get("renderer_revision"),
            "prime": prime_publications.get("renderer_revision"),
            "workload": workload_publications.get("renderer_revision"),
        },
        "status": "ok",
    }


def _validate_market_cohort(
    market_run: dict[str, Any],
    *,
    required_providers: set[str],
    forbidden_providers: set[str],
    minimum_provider_count: int,
) -> tuple[set[str], set[str], str]:
    providers = set(market_run.get("successful_providers") or [])
    failed = set(market_run.get("failed_providers") or [])
    declared = set(market_run.get("providers") or [])
    quality = market_run.get("data_quality")
    cohort = quality.get("cohort") if isinstance(quality, dict) else None
    if not isinstance(cohort, dict):
        raise RuntimeError("Public market run is missing its provider cohort")

    cohort_status = str(cohort.get("status") or "")
    if cohort_status not in {"complete", "degraded"}:
        raise RuntimeError(f"Public market cohort status is {cohort_status!r}")
    published_minimum = int(cohort.get("minimum_successful_providers") or 0)
    if published_minimum < minimum_provider_count:
        raise RuntimeError(
            f"Public market publication policy requires {published_minimum} providers; "
            f"minimum is {minimum_provider_count}"
        )
    if len(providers) < minimum_provider_count:
        raise RuntimeError(
            f"Public market run has {len(providers)} providers; "
            f"minimum is {minimum_provider_count}"
        )

    manifest_required = set(cohort.get("required_providers") or [])
    missing = (required_providers | manifest_required) - providers
    if missing:
        raise RuntimeError(
            f"Public market run is missing providers: {', '.join(sorted(missing))}"
        )
    forbidden = forbidden_providers & declared
    if forbidden:
        raise RuntimeError(
            f"Retired providers are still public: {', '.join(sorted(forbidden))}"
        )
    return providers, failed, cohort_status


def _validate_publication_manifest(
    manifest: dict[str, Any],
    *,
    label: str,
    expected_profile: str,
    expected_count: int,
    required_renderer_revision: str | None,
) -> None:
    profile = str(manifest.get("render_profile") or "")
    if profile != expected_profile:
        raise RuntimeError(
            f"{label} publications use render profile {profile!r}; "
            f"expected {expected_profile!r}"
        )
    count = int(manifest.get("publication_count") or 0)
    if count != expected_count:
        raise RuntimeError(
            f"{label} publication count is {count}; expected {expected_count}"
        )
    renderer_revision = str(manifest.get("renderer_revision") or "")
    if not renderer_revision or renderer_revision == "unknown":
        raise RuntimeError(f"{label} publications do not identify their renderer")
    if (
        required_renderer_revision
        and renderer_revision != required_renderer_revision
    ):
        raise RuntimeError(
            f"{label} publications were rendered by {renderer_revision!r}; "
            f"expected {required_renderer_revision!r}"
        )


def _fetch_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=15) as response:  # noqa: S310 - fixed operator URL.
        return dict(json.load(response))


def _timestamp(value: Any, *, field: str) -> datetime:
    if not value:
        raise RuntimeError(f"Public payload is missing {field}")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RuntimeError(f"Public payload field {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    main()
