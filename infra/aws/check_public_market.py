"""Fail when the public GPU market feed is stale or incomplete."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any
from urllib.request import urlopen

GPU_FAMILIES = ("h100", "h200", "b200", "b300")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://bazaar.adamsioud.com")
    parser.add_argument("--max-age-hours", type=float, default=2.5)
    parser.add_argument("--require-provider", action="append", default=[])
    parser.add_argument("--forbid-provider", action="append", default=[])
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    market_run = _fetch_json(f"{base_url}/market-run.json")
    cards = {
        family: _fetch_json(f"{base_url}/gpu-benchmark/{family}.json")
        for family in GPU_FAMILIES
    }
    summary = validate_public_market(
        market_run=market_run,
        cards=cards,
        max_age_hours=args.max_age_hours,
        required_providers=set(args.require_provider),
        forbidden_providers=set(args.forbid_provider),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def validate_public_market(
    *,
    market_run: dict[str, Any],
    cards: dict[str, dict[str, Any]],
    max_age_hours: float,
    required_providers: set[str],
    forbidden_providers: set[str],
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    observed_at = _timestamp(market_run.get("observed_at"), field="observed_at")
    age_hours = (current_time - observed_at).total_seconds() / 3600
    if age_hours < 0 or age_hours > max_age_hours:
        raise RuntimeError(
            f"Public market run is {age_hours:.2f} hours old; limit is {max_age_hours:.2f}"
        )
    if market_run.get("status") != "success":
        raise RuntimeError(f"Public market run status is {market_run.get('status')!r}")

    providers = set(market_run.get("successful_providers") or [])
    failed = set(market_run.get("failed_providers") or [])
    missing = required_providers - providers
    forbidden = forbidden_providers & providers
    if failed:
        raise RuntimeError(f"Public market run has failed providers: {', '.join(sorted(failed))}")
    if missing:
        raise RuntimeError(f"Public market run is missing providers: {', '.join(sorted(missing))}")
    if forbidden:
        raise RuntimeError(f"Retired providers are still public: {', '.join(sorted(forbidden))}")

    for family, card in cards.items():
        card_time = _timestamp(card.get("as_of"), field=f"{family}.as_of")
        card_age_hours = (current_time - card_time).total_seconds() / 3600
        if card_age_hours < 0 or card_age_hours > max_age_hours:
            raise RuntimeError(
                f"{family.upper()} card is {card_age_hours:.2f} hours old; "
                f"limit is {max_age_hours:.2f}"
            )
        if card.get("status") not in {"live", "observed", "success"}:
            raise RuntimeError(f"{family.upper()} card status is {card.get('status')!r}")

    return {
        "market_run_id": market_run.get("market_run_id"),
        "observed_at": observed_at.isoformat(),
        "age_hours": round(age_hours, 3),
        "provider_count": len(providers),
        "cards": sorted(cards),
        "status": "ok",
    }


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
