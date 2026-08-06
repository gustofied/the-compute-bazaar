"""Public-safe projections for Prime frontier offer data."""

from __future__ import annotations

from typing import Any

from .offer_reference import PRIME_FRONTIER_PRICE_INCREMENT, PRIME_FRONTIER_PRODUCTS


def public_prime_frontier_products(
    *,
    payload: dict[str, Any],
    benchmark_values: list[dict[str, Any]],
    benchmark_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_benchmarks = {
        str(row.get("benchmark_family_id") or ""): row for row in benchmark_values
    }
    benchmark_by_run = {
        (
            str(row.get("benchmark_family_id") or ""),
            str(row.get("gold_run_id") or ""),
        ): row
        for row in benchmark_history
        if row.get("gold_run_id")
    }
    products: list[dict[str, Any]] = []
    for product in PRIME_FRONTIER_PRODUCTS:
        family_id = product.family_id
        history = [
            _public_reference(
                row,
                benchmark=benchmark_by_run.get(
                    (family_id, str(row.get("gold_run_id") or ""))
                ),
            )
            for row in payload.get("history", [])
            if row.get("gpu_family_id") == family_id
        ]
        benchmark_current = current_benchmarks.get(family_id)
        last_seen_source = payload.get("last_seen", {}).get(family_id)
        raw_offers = _family_rows(payload, "offers", family_id)
        raw_events = _family_rows(payload, "events", family_id)
        offers = [
            _public_offer(
                row,
                benchmark=benchmark_current,
                source_url=product.market_url,
            )
            for row in raw_offers
        ]
        products.append(
            {
                "family_id": family_id,
                "label": product.label,
                "gpu_product_family": product.canonical_model,
                "prime_api_gpu_type": product.api_gpu_type,
                "market_url": product.market_url,
                "current": _public_reference(
                    payload.get("current", {}).get(family_id),
                    benchmark=benchmark_current,
                ),
                "last_seen": _public_reference(
                    last_seen_source,
                    benchmark=benchmark_by_run.get(
                        (family_id, str((last_seen_source or {}).get("gold_run_id") or ""))
                    ),
                ),
                "benchmark_current": benchmark_current,
                "history": [row for row in history if row],
                "benchmark_history": [
                    row
                    for row in benchmark_history
                    if row.get("benchmark_family_id") == family_id
                ],
                "ladder": [
                    _public_ladder_row(
                        row,
                        offers=raw_offers,
                        events=raw_events,
                        benchmark=benchmark_current,
                        source_url=product.market_url,
                    )
                    for row in _family_rows(payload, "ladder", family_id)
                ],
                "events": [_public_event(row) for row in raw_events],
                "event_history": [
                    _public_event(row)
                    for row in _family_rows(payload, "event_history", family_id)
                ],
                "offers": offers,
                "sources": _public_sources(offers),
            }
        )
    return products


def _family_rows(
    payload: dict[str, Any], key: str, family_id: str
) -> list[dict[str, Any]]:
    return [
        row
        for row in payload.get(key, [])
        if row.get("gpu_family_id") == family_id
    ]


def _public_reference(
    row: Any,
    *,
    benchmark: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    result = _select(
        row,
        "offer_reference_symbol",
        "reference_scope",
        "gpu_family_id",
        "gpu_product_family",
        "unit",
        "price_basis",
        "reference_usd_gpu_hr",
        "minimum_executable_reference_usd_gpu_hr",
        "provider_floor_mean_usd_gpu_hr",
        "provider_floor_p25_usd_gpu_hr",
        "provider_floor_p75_usd_gpu_hr",
        "best_usd_gpu_hr",
        "highest_provider_floor_usd_gpu_hr",
        "provider_count",
        "configuration_count",
        "single_gpu_configuration_count",
        "socket_count",
        "country_count",
        "variable_price_provider_count",
        "low_price_provider_count",
        "status",
        "latest_source_observed_at",
        "gold_run_id",
        "gold_observed_at",
        "gold_observed_date",
        "methodology_version",
    )
    market_value = _float_or_none((benchmark or {}).get("benchmark_usd_gpu_hr"))
    prime_value = _float_or_none(row.get("reference_usd_gpu_hr"))
    result.update(
        {
            "market_benchmark_usd_gpu_hr": market_value,
            "market_benchmark_p25_usd_gpu_hr": (
                (benchmark or {}).get("provider_floor_p25_usd_gpu_hr")
            ),
            "market_benchmark_p75_usd_gpu_hr": (
                (benchmark or {}).get("provider_floor_p75_usd_gpu_hr")
            ),
            "market_benchmark_provider_count": (benchmark or {}).get("provider_count"),
            "premium_to_market_benchmark_fraction": (
                prime_value / market_value - 1
                if prime_value is not None and market_value is not None and market_value > 0
                else None
            ),
        }
    )
    return result


def _public_ladder_row(
    row: dict[str, Any],
    *,
    offers: list[dict[str, Any]],
    events: list[dict[str, Any]],
    benchmark: dict[str, Any] | None,
    source_url: str,
) -> dict[str, Any]:
    level = row.get("price_level_usd_gpu_hr")
    family_id = row.get("gpu_family_id")
    projected = _select(
        row,
        "gpu_family_id",
        "price_level_usd_gpu_hr",
        "price_level_rank",
        "configuration_count",
        "provider_count",
        "single_gpu_configuration_count",
        "minimum_offer_usd_gpu_hr",
        "maximum_offer_usd_gpu_hr",
        "entered_count",
        "repriced_count",
        "left_availability_count",
        "stock_status_changed_count",
        "remained_count",
        "reference_usd_gpu_hr",
        "market_benchmark_usd_gpu_hr",
        "market_benchmark_p25_usd_gpu_hr",
        "market_benchmark_p75_usd_gpu_hr",
        "market_benchmark_provider_count",
        "distance_from_prime_reference_usd_gpu_hr",
        "distance_from_market_benchmark_usd_gpu_hr",
        "premium_to_market_benchmark_fraction",
        "is_prime_reference_level",
        "is_market_benchmark_level",
        "gold_run_id",
        "gold_observed_at",
        "status",
        "methodology_version",
    )
    projected["offers"] = [
        _public_offer(offer, benchmark=benchmark, source_url=source_url)
        for offer in offers
        if offer.get("gpu_family_id") == family_id
        and _same_price_level(offer.get("price_usd_gpu_hr"), level)
    ]
    projected["events"] = [
        _public_event(event)
        for event in events
        if event.get("gpu_family_id") == family_id
        and _same_number(event.get("price_level_usd_gpu_hr"), level)
    ]
    return projected


def _public_event(row: dict[str, Any]) -> dict[str, Any]:
    return _select(
        row,
        "event_id",
        "listing_id",
        "event_type",
        "event_label",
        "provider",
        "gpu_family_id",
        "gpu_model",
        "gpu_count",
        "gpu_socket",
        "region",
        "stock_status_before",
        "stock_status_after",
        "price_before_usd_gpu_hr",
        "price_after_usd_gpu_hr",
        "price_delta_usd_gpu_hr",
        "price_delta_fraction",
        "price_level_usd_gpu_hr",
        "previous_observed_at",
        "observed_at",
        "comparison_gap_seconds",
        "gold_run_id",
        "methodology_version",
        "source_url",
        "notes",
    )


def _public_offer(
    row: dict[str, Any],
    *,
    benchmark: dict[str, Any] | None,
    source_url: str,
) -> dict[str, Any]:
    minimum_total = _float_or_none(row.get("minimum_executable_price_usd_hr"))
    gpu_count = _float_or_none(row.get("gpu_count"))
    minimum_total_per_gpu = (
        minimum_total / gpu_count
        if minimum_total is not None and gpu_count is not None and gpu_count > 0
        else None
    )
    market_value = _float_or_none((benchmark or {}).get("benchmark_usd_gpu_hr"))
    offer_value = _float_or_none(row.get("price_usd_gpu_hr"))
    return {
        **_select(
            row,
            "source_offer_id",
            "provider",
            "gpu_family_id",
            "gpu_model",
            "gpu_count",
            "gpu_socket",
            "vram_gb",
            "country",
            "region",
            "stock_status",
            "price_is_variable",
            "price_usd_gpu_hr",
            "price_usd_instance_hr",
            "required_resource_price_usd_hr",
            "price_basis",
            "observed_at",
        ),
        "minimum_executable_price_usd_gpu_hr": minimum_total_per_gpu,
        "market_benchmark_usd_gpu_hr": market_value,
        "premium_to_market_benchmark_fraction": (
            offer_value / market_value - 1
            if offer_value is not None and market_value is not None and market_value > 0
            else None
        ),
        "requestable_via_prime": True,
        "source_url": source_url,
    }


def _public_sources(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for offer in offers:
        provider = str(offer.get("provider") or "")
        if provider:
            grouped.setdefault(provider, []).append(offer)
    rows: list[dict[str, Any]] = []
    for provider, provider_offers in grouped.items():
        prices = [
            value
            for offer in provider_offers
            if (value := _float_or_none(offer.get("price_usd_gpu_hr"))) is not None
        ]
        rows.append(
            {
                "provider": provider,
                "configuration_count": len(provider_offers),
                "best_usd_gpu_hr": min(prices) if prices else None,
                "highest_usd_gpu_hr": max(prices) if prices else None,
                "regions": sorted(
                    {
                        str(offer.get("region"))
                        for offer in provider_offers
                        if offer.get("region")
                    }
                ),
                "gpu_counts": sorted(
                    {
                        int(offer.get("gpu_count") or 0)
                        for offer in provider_offers
                        if int(offer.get("gpu_count") or 0) > 0
                    }
                ),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            float(row.get("best_usd_gpu_hr") or float("inf")),
            str(row.get("provider") or ""),
        ),
    )


def _select(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: row.get(key) for key in keys}


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_price_level(value: Any, level: Any) -> bool:
    try:
        rounded = (
            int(float(value) / PRIME_FRONTIER_PRICE_INCREMENT + 0.5)
            * PRIME_FRONTIER_PRICE_INCREMENT
        )
        return _same_number(rounded, level)
    except (TypeError, ValueError):
        return False


def _same_number(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) < 1e-9
    except (TypeError, ValueError):
        return False
