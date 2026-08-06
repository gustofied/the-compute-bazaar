"""Shape Gold tables into public, static market-card snapshots."""

from __future__ import annotations

from typing import Any

from .gold import (
    MARKET_STATE_METHODOLOGY_VERSION,
    query_gold_benchmark_constituents,
    query_gold_benchmark_history,
    query_gold_benchmark_values,
    query_gold_listings,
    query_gold_market_state,
    query_gold_market_state_history,
    query_gold_prime_frontier_offer_market,
    query_gold_provider_comparison,
    read_latest_gold_manifest,
)
from .gold_models import BENCHMARK_FAMILIES, BENCHMARK_METHODOLOGY_VERSION
from .offer_reference import (
    PRIME_FRONTIER_API_DOCS_URL,
    PRIME_FRONTIER_METHOD_VERSION,
    PRIME_FRONTIER_PRICE_INCREMENT,
    PRIME_FRONTIER_PRODUCTS,
    PRIME_FRONTIER_PROVISION_DOCS_URL,
    PRIME_FRONTIER_SCOPE,
    PRIME_FRONTIER_SOURCE_URL,
)
from .public_views import (
    GPU_FAMILIES,
    gpu_benchmark_view,
    market_overview_view,
    market_state_view,
    prime_frontier_view,
)
from .publications import (
    publish_gpu_benchmark_publications,
    publish_prime_offer_shelf_publications,
)
from .schemas import utc_now
from .storage import read_json, write_json


PUBLIC_MARKET_STATE_HISTORY_RESOURCES = {
    "ALL_GPU",
    "ALL_CPU",
    "ALL_MEMORY",
    "ALL_STORAGE",
    "ALL_EPHEMERAL_STORAGE",
    "ALL_PERSISTENT_STORAGE",
}


def export_gold_dashboard_snapshot(
    *,
    lake_root: str,
    output_root: str,
    limit: int = 100,
    benchmark_history_limit: int = 24,
) -> dict[str, Any]:
    """Export public JSON snapshots for static D3/blog consumers."""
    manifest = read_latest_gold_manifest(lake_root)
    public_manifest = _public_gold_manifest(
        manifest,
        dashboard_exported_at=utc_now().isoformat(),
    )
    warnings = []
    benchmark_values_payload = query_gold_benchmark_values(lake_root=lake_root)
    benchmark_values = benchmark_values_payload["rows"]
    # Benchmark evidence is a complete audit surface, not a sampled dashboard table.
    benchmark_constituents = query_gold_benchmark_constituents(lake_root=lake_root)[
        "rows"
    ]
    public_benchmark_values = [_public_benchmark_value(row) for row in benchmark_values]
    public_benchmark_constituents = [
        _public_benchmark_constituent(row) for row in benchmark_constituents
    ]
    try:
        benchmark_history_payload = query_gold_benchmark_history(
            lake_root=lake_root,
            history_limit=benchmark_history_limit,
            canonical_market_runs_only=True,
        )
    except Exception as exc:  # noqa: BLE001 - latest values should survive a history failure.
        benchmark_history_payload = {"history_manifest_count": 0, "rows": []}
        warnings.append(f"benchmark history export skipped: {exc}")
    public_benchmark_history = [
        _public_benchmark_history_value(row)
        for row in benchmark_history_payload["rows"]
        if _has_benchmark_value(row)
    ]
    benchmark_history_ref = "/".join(
        [output_root.rstrip("/"), "benchmark-history.json"]
    )
    existing_benchmark_history = _read_existing_benchmark_history(benchmark_history_ref)
    public_benchmark_history = _merge_public_benchmark_history(
        existing_benchmark_history,
        public_benchmark_history,
    )
    provider_comparison = query_gold_provider_comparison(
        lake_root=lake_root, limit=limit
    )["rows"]
    listings = query_gold_listings(lake_root=lake_root, limit=limit)["rows"]
    market_state = query_gold_market_state(lake_root=lake_root)["rows"]
    market_state_ref = "/".join([output_root.rstrip("/"), "market-state.json"])
    try:
        market_state_history_payload = query_gold_market_state_history(
            lake_root=lake_root,
        )
    except Exception as exc:  # noqa: BLE001 - current market state should still publish.
        market_state_history_payload = {"history_manifest_count": 0, "rows": []}
        warnings.append(f"market-state history export skipped: {exc}")
    public_market_state = [
        _public_market_state_row(row)
        for row in market_state
        if row.get("measurement_kind") in {"rental_occupancy", "availability_pressure"}
    ]
    public_market_state_history = _merge_public_market_state_history(
        _read_existing_market_state_history(market_state_ref),
        [
            _public_market_state_row(row)
            for row in market_state_history_payload["rows"]
            if row.get("measurement_kind") == "rental_occupancy"
            and row.get("resource_type") in PUBLIC_MARKET_STATE_HISTORY_RESOURCES
            and row.get("aggregation_eligible") is not False
        ],
    )
    try:
        prime_frontier_payload = query_gold_prime_frontier_offer_market(
            lake_root=lake_root
        )
    except Exception as exc:  # noqa: BLE001 - other public products should still publish.
        prime_frontier_payload = {
            "current": {},
            "last_seen": {},
            "history": [],
            "ladder": [],
            "events": [],
            "event_history": [],
            "offers": [],
        }
        warnings.append(f"Prime frontier offer-market export skipped: {exc}")
    output_refs = {
        "manifest": "/".join([output_root.rstrip("/"), "manifest.json"]),
        "featured_benchmarks": "/".join(
            [output_root.rstrip("/"), "featured-benchmarks.json"]
        ),
        "benchmark_history": benchmark_history_ref,
        "benchmark_constituents": "/".join(
            [output_root.rstrip("/"), "benchmark-constituents.json"]
        ),
        "provider_comparison": "/".join(
            [output_root.rstrip("/"), "provider-comparison.json"]
        ),
        "listings_sample": "/".join([output_root.rstrip("/"), "listings-sample.json"]),
        "market_state": market_state_ref,
        "prime_frontier_offer_market": "/".join(
            [output_root.rstrip("/"), "prime-frontier-offer-market.json"]
        ),
        "prime_frontier_offer_shelf": "/".join(
            [output_root.rstrip("/"), "prime-frontier-offer-shelf.json"]
        ),
        "market_overview": "/".join([output_root.rstrip("/"), "market-overview.json"]),
        "capacity_market_state": "/".join(
            [output_root.rstrip("/"), "capacity", "market-state.json"]
        ),
    }
    prime_frontier_products = _public_prime_frontier_products(
        payload=prime_frontier_payload,
        benchmark_values=public_benchmark_values,
        benchmark_history=public_benchmark_history,
    )
    prime_frontier_public = {
        "schema_version": "prime_frontier_offer_market_public_v1",
        "manifest": public_manifest,
        "methodology_version": PRIME_FRONTIER_METHOD_VERSION,
        "reference_scope": PRIME_FRONTIER_SCOPE,
        "source": {
            "name": "Prime Intellect GPU availability",
            "market_url": PRIME_FRONTIER_SOURCE_URL,
            "api_documentation_url": PRIME_FRONTIER_API_DOCS_URL,
            "provisioning_documentation_url": (PRIME_FRONTIER_PROVISION_DOCS_URL),
        },
        "measurement_notes": [
            "Each family reference is the median of one lowest eligible base rate per upstream provider.",
            "Prime rows are requestable configurations, not physical GPU inventory or executed rentals.",
            "Configuration depth counts returned configurations and named upstream providers; it is not posted quantity.",
            "A configuration leaving availability is not classified as a fill or cancellation.",
            "Required storage or configurable resource charges can make the executable machine total higher.",
        ],
        "execution_data": {
            "status": "not_exposed_by_availability_api",
            "available_fields": [
                "configuration identity",
                "upstream provider",
                "price",
                "machine shape",
                "region",
                "stock label",
            ],
            "unavailable_fields": [
                "posted GPU quantity",
                "filled quantity",
                "canceled quantity",
                "remaining quantity",
                "transaction price",
            ],
        },
        "products": prime_frontier_products,
    }
    prime_frontier_shelf_public = {
        "schema_version": "prime_frontier_offer_shelf_public_v1",
        "manifest": public_manifest,
        "methodology_version": PRIME_FRONTIER_METHOD_VERSION,
        "reference_scope": PRIME_FRONTIER_SCOPE,
        "source": prime_frontier_public["source"],
        "measurement_notes": prime_frontier_public["measurement_notes"],
        "products": [
            {
                key: product.get(key)
                for key in [
                    "family_id",
                    "label",
                    "market_url",
                    "current",
                    "last_seen",
                    "history",
                    "event_history",
                    "offers",
                    "sources",
                ]
            }
            for product in prime_frontier_products
            if product.get("family_id") in {"H100", "H200"}
        ],
    }
    benchmark_by_family = {
        str(row.get("benchmark_family_id") or ""): row
        for row in public_benchmark_values
    }
    benchmark_cards = {
        family: gpu_benchmark_view(
            manifest=public_manifest,
            family_id=family,
            current=benchmark_by_family.get(family),
            history=public_benchmark_history,
            constituents=public_benchmark_constituents,
            methodology_version=BENCHMARK_METHODOLOGY_VERSION,
        )
        for family in GPU_FAMILIES
    }
    gpu_publications = publish_gpu_benchmark_publications(
        output_root=output_root,
        cards=benchmark_cards,
    )
    output_refs["gpu_publications"] = gpu_publications["manifest_ref"]
    for family in GPU_FAMILIES:
        output_refs[f"gpu_benchmark_{family.lower()}"] = "/".join(
            [output_root.rstrip("/"), "gpu-benchmark", f"{family.lower()}.json"]
        )
    prime_cards = {
        str(product.get("family_id") or ""): prime_frontier_view(
            manifest=public_manifest,
            product=product,
            methodology_version=PRIME_FRONTIER_METHOD_VERSION,
            source=prime_frontier_public["source"],
            measurement_notes=prime_frontier_public["measurement_notes"],
            execution_data=prime_frontier_public["execution_data"],
        )
        for product in prime_frontier_products
    }
    prime_publications = publish_prime_offer_shelf_publications(
        output_root=output_root,
        cards=prime_cards,
    )
    output_refs["prime_publications"] = prime_publications["manifest_ref"]
    for product in prime_frontier_products:
        family = str(product.get("family_id") or "")
        publication = (prime_cards.get(family) or {}).get("publication")
        if publication:
            product["publication"] = publication
    for product in prime_frontier_shelf_public["products"]:
        family = str(product.get("family_id") or "")
        publication = (prime_cards.get(family) or {}).get("publication")
        if publication:
            product["publication"] = publication
    prime_frontier_shelf_public["publications"] = {
        "manifest_path": "publications/prime-gpu-market/manifest.json",
        "revision": prime_publications["revision"],
        "publication_count": prime_publications["publication_count"],
    }
    for family in GPU_FAMILIES:
        output_refs[f"prime_frontier_{family.lower()}"] = "/".join(
            [output_root.rstrip("/"), "prime-frontier", f"{family.lower()}.json"]
        )
    public_market_state_payload = {
        "schema_version": "compute_market_state_public_v1",
        "manifest": public_manifest,
        "methodology_version": MARKET_STATE_METHODOLOGY_VERSION,
        "measurement_kinds": {
            "rental_occupancy": "Rented units divided by a source-defined total.",
            "availability_pressure": "Current deployability or free stock; not rented share unless a denominator is present.",
        },
        "current_row_count": len(public_market_state),
        "current_rows": public_market_state,
        "history_manifest_count": market_state_history_payload[
            "history_manifest_count"
        ],
        "history_row_count": len(public_market_state_history),
        "history_rows": public_market_state_history,
    }
    capacity_card = market_state_view(public_market_state_payload)
    market_overview = market_overview_view(
        manifest={
            **public_manifest,
            "status": "live",
            "successful_providers": public_manifest.get("provider_scope") or [],
            "failed_providers": [],
        },
        benchmark_cards=list(benchmark_cards.values()),
    )
    write_json(output_refs["manifest"], public_manifest)
    write_json(
        output_refs["featured_benchmarks"],
        {
            "manifest": public_manifest,
            "methodology_version": BENCHMARK_METHODOLOGY_VERSION,
            "families": BENCHMARK_FAMILIES,
            "rows": public_benchmark_values,
        },
    )
    write_json(
        output_refs["benchmark_history"],
        {
            "manifest": public_manifest,
            "methodology_version": BENCHMARK_METHODOLOGY_VERSION,
            "families": BENCHMARK_FAMILIES,
            "history_manifest_count": len(
                {
                    row.get("gold_run_id") or row.get("gold_observed_at")
                    for row in public_benchmark_history
                }
            ),
            "row_count": len(public_benchmark_history),
            "rows": public_benchmark_history,
        },
    )
    write_json(
        output_refs["benchmark_constituents"],
        {
            "manifest": public_manifest,
            "methodology_version": BENCHMARK_METHODOLOGY_VERSION,
            "complete": True,
            "row_count": len(public_benchmark_constituents),
            "rows": public_benchmark_constituents,
        },
    )
    write_json(
        output_refs["provider_comparison"],
        {"manifest": public_manifest, "rows": provider_comparison},
    )
    write_json(
        output_refs["listings_sample"], {"manifest": public_manifest, "rows": listings}
    )
    write_json(
        output_refs["market_state"],
        public_market_state_payload,
    )
    write_json(
        output_refs["prime_frontier_offer_market"],
        prime_frontier_public,
    )
    write_json(
        output_refs["prime_frontier_offer_shelf"],
        prime_frontier_shelf_public,
    )
    for family, card in benchmark_cards.items():
        write_json(output_refs[f"gpu_benchmark_{family.lower()}"], card)
    for family, card in prime_cards.items():
        write_json(output_refs[f"prime_frontier_{family.lower()}"], card)
    write_json(output_refs["capacity_market_state"], capacity_card)
    write_json(output_refs["market_overview"], market_overview)

    return {
        "output_refs": output_refs,
        "row_counts": {
            "featured_benchmarks": len(benchmark_values),
            "benchmark_history": len(public_benchmark_history),
            "benchmark_constituents": len(benchmark_constituents),
            "provider_comparison": len(provider_comparison),
            "listings_sample": len(listings),
            "market_state": len(public_market_state),
            "market_state_history": len(public_market_state_history),
            "prime_frontier_reference_history": len(
                prime_frontier_payload.get("history", [])
            ),
            "prime_frontier_ladder": len(prime_frontier_payload.get("ladder", [])),
            "prime_frontier_events": len(prime_frontier_payload.get("events", [])),
            "prime_frontier_offers": len(prime_frontier_payload.get("offers", [])),
            "gpu_benchmark_cards": len(benchmark_cards),
            "gpu_publications": gpu_publications["publication_count"],
            "prime_frontier_cards": len(prime_cards),
            "capacity_cards": 1,
        },
        "source_gold_manifest_ref": manifest.get("manifest_ref"),
        "warnings": warnings,
    }


def _public_gold_manifest(
    manifest: dict[str, Any],
    *,
    dashboard_exported_at: str | None = None,
) -> dict[str, Any]:
    return {
        "manifest_version": manifest.get("manifest_version"),
        "methodology_version": manifest.get("methodology_version"),
        "run_id": manifest.get("run_id"),
        "observed_at": manifest.get("observed_at"),
        "observed_date": manifest.get("observed_date"),
        "provider_scope": manifest.get("provider_scope"),
        "row_counts": manifest.get("row_counts"),
        "source_run_ids": manifest.get("source_run_ids"),
        "dashboard_exported_at": dashboard_exported_at,
    }


def _public_prime_frontier_products(
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
        raw_history = [
            row
            for row in payload.get("history", [])
            if row.get("gpu_family_id") == family_id
        ]
        history = [
            _public_prime_frontier_reference(
                row,
                benchmark=benchmark_by_run.get(
                    (family_id, str(row.get("gold_run_id") or ""))
                ),
            )
            for row in raw_history
        ]
        benchmark_current = current_benchmarks.get(family_id)
        current = _public_prime_frontier_reference(
            payload.get("current", {}).get(family_id),
            benchmark=benchmark_current,
        )
        last_seen = _public_prime_frontier_reference(
            payload.get("last_seen", {}).get(family_id),
            benchmark=(
                benchmark_by_run.get(
                    (
                        family_id,
                        str(
                            payload.get("last_seen", {})
                            .get(family_id, {})
                            .get("gold_run_id")
                            or ""
                        ),
                    )
                )
            ),
        )
        raw_offers = [
            row
            for row in payload.get("offers", [])
            if row.get("gpu_family_id") == family_id
        ]
        raw_events = [
            row
            for row in payload.get("events", [])
            if row.get("gpu_family_id") == family_id
        ]
        raw_event_history = [
            row
            for row in payload.get("event_history", [])
            if row.get("gpu_family_id") == family_id
        ]
        offers = [
            _public_prime_frontier_offer(
                row,
                benchmark=benchmark_current,
                source_url=product.market_url,
            )
            for row in raw_offers
        ]
        events = [_public_prime_frontier_event(row) for row in raw_events]
        ladder = [
            _public_prime_frontier_ladder_row(
                row,
                offers=raw_offers,
                events=raw_events,
                benchmark=benchmark_current,
                source_url=product.market_url,
            )
            for row in payload.get("ladder", [])
            if row.get("gpu_family_id") == family_id
        ]
        products.append(
            {
                "family_id": family_id,
                "label": product.label,
                "gpu_product_family": product.canonical_model,
                "prime_api_gpu_type": product.api_gpu_type,
                "market_url": product.market_url,
                "current": current,
                "last_seen": last_seen,
                "benchmark_current": benchmark_current,
                "history": [row for row in history if row],
                "benchmark_history": [
                    row
                    for row in benchmark_history
                    if row.get("benchmark_family_id") == family_id
                ],
                "ladder": ladder,
                "events": events,
                "event_history": [
                    _public_prime_frontier_event(row) for row in raw_event_history
                ],
                "offers": offers,
                "sources": _public_prime_frontier_sources(offers),
            }
        )
    return products


def _public_prime_frontier_reference(
    row: Any,
    *,
    benchmark: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    result = {
        key: row.get(key)
        for key in [
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
        ]
    }
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
            "market_benchmark_provider_count": (
                (benchmark or {}).get("provider_count")
            ),
            "premium_to_market_benchmark_fraction": (
                prime_value / market_value - 1
                if prime_value is not None
                and market_value is not None
                and market_value > 0
                else None
            ),
        }
    )
    return result


def _public_prime_frontier_ladder_row(
    row: dict[str, Any],
    *,
    offers: list[dict[str, Any]],
    events: list[dict[str, Any]],
    benchmark: dict[str, Any] | None,
    source_url: str,
) -> dict[str, Any]:
    level = row.get("price_level_usd_gpu_hr")
    family_id = row.get("gpu_family_id")
    level_offers = [
        _public_prime_frontier_offer(
            offer,
            benchmark=benchmark,
            source_url=source_url,
        )
        for offer in offers
        if offer.get("gpu_family_id") == family_id
        if _same_price_level(offer.get("price_usd_gpu_hr"), level)
    ]
    level_events = [
        _public_prime_frontier_event(event)
        for event in events
        if event.get("gpu_family_id") == family_id
        if _same_number(event.get("price_level_usd_gpu_hr"), level)
    ]
    return {
        key: row.get(key)
        for key in [
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
        ]
    } | {
        "offers": level_offers,
        "events": level_events,
    }


def _public_prime_frontier_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in [
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
        ]
    }


def _public_prime_frontier_offer(
    row: dict[str, Any],
    *,
    benchmark: dict[str, Any] | None,
    source_url: str,
) -> dict[str, Any]:
    minimum_total = row.get("minimum_executable_price_usd_hr")
    gpu_count = row.get("gpu_count")
    try:
        minimum_total_per_gpu = (
            float(minimum_total) / float(gpu_count)
            if minimum_total is not None and float(gpu_count) > 0
            else None
        )
    except (TypeError, ValueError, ZeroDivisionError):
        minimum_total_per_gpu = None
    market_value = _float_or_none((benchmark or {}).get("benchmark_usd_gpu_hr"))
    offer_value = _float_or_none(row.get("price_usd_gpu_hr"))
    return {
        "source_offer_id": row.get("source_offer_id"),
        "provider": row.get("provider"),
        "gpu_family_id": row.get("gpu_family_id"),
        "gpu_model": row.get("gpu_model"),
        "gpu_count": row.get("gpu_count"),
        "gpu_socket": row.get("gpu_socket"),
        "vram_gb": row.get("vram_gb"),
        "country": row.get("country"),
        "region": row.get("region"),
        "stock_status": row.get("stock_status"),
        "price_is_variable": row.get("price_is_variable"),
        "price_usd_gpu_hr": row.get("price_usd_gpu_hr"),
        "price_usd_instance_hr": row.get("price_usd_instance_hr"),
        "minimum_executable_price_usd_gpu_hr": minimum_total_per_gpu,
        "required_resource_price_usd_hr": row.get("required_resource_price_usd_hr"),
        "price_basis": row.get("price_basis"),
        "observed_at": row.get("observed_at"),
        "market_benchmark_usd_gpu_hr": market_value,
        "premium_to_market_benchmark_fraction": (
            offer_value / market_value - 1
            if offer_value is not None and market_value is not None and market_value > 0
            else None
        ),
        "requestable_via_prime": True,
        "source_url": source_url,
    }


def _public_prime_frontier_sources(
    offers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for offer in offers:
        provider = str(offer.get("provider") or "")
        if provider:
            grouped.setdefault(provider, []).append(offer)
    rows: list[dict[str, Any]] = []
    for provider, provider_offers in grouped.items():
        prices = [
            float(offer["price_usd_gpu_hr"])
            for offer in provider_offers
            if _float_or_none(offer.get("price_usd_gpu_hr")) is not None
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


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


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


def _public_benchmark_value(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in [
            "benchmark_value_id",
            "benchmark_symbol",
            "benchmark_family_id",
            "benchmark_label",
            "gpu_model_prefixes",
            "methodology_version",
            "methodology_query_id",
            "benchmark_basis",
            "benchmark_usd_gpu_hr",
            "observed_average_usd_gpu_hr",
            "provider_floor_median_usd_gpu_hr",
            "provider_floor_mean_usd_gpu_hr",
            "provider_floor_p25_usd_gpu_hr",
            "provider_floor_p75_usd_gpu_hr",
            "floor_usd_gpu_hr",
            "median_usd_gpu_hr",
            "simple_mean_usd_gpu_hr",
            "trimmed_mean_usd_gpu_hr",
            "p25_usd_gpu_hr",
            "p75_usd_gpu_hr",
            "cheapest_offer_usd_hr",
            "offer_count",
            "included_offer_count",
            "provider_count",
            "gpu_model_count",
            "country_count",
            "secure_offer_count",
            "spot_offer_count",
            "latest_observed_at",
            "status",
            "source_run_id",
            "calculated_at",
        ]
    }


def _public_benchmark_history_value(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in [
            "benchmark_symbol",
            "benchmark_family_id",
            "benchmark_label",
            "methodology_version",
            "benchmark_basis",
            "benchmark_usd_gpu_hr",
            "provider_floor_p25_usd_gpu_hr",
            "provider_floor_p75_usd_gpu_hr",
            "included_offer_count",
            "provider_count",
            "latest_observed_at",
            "calculated_at",
            "gold_run_id",
            "gold_observed_at",
            "gold_observed_date",
        ]
    }


def _has_benchmark_value(row: dict[str, Any]) -> bool:
    value = row.get("benchmark_usd_gpu_hr")
    try:
        return value is not None and float(value) > 0
    except (TypeError, ValueError):
        return False


def _merge_public_benchmark_history(
    existing_rows: Any,
    current_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    candidates = [
        row
        for row in (existing_rows if isinstance(existing_rows, list) else [])
        if isinstance(row, dict)
    ]
    candidates.extend(current_rows)
    for row in candidates:
        if row.get("methodology_version") != BENCHMARK_METHODOLOGY_VERSION:
            continue
        if not _has_benchmark_value(row):
            continue
        run_id = str(row.get("gold_run_id") or "")
        if run_id and not _is_canonical_market_run_id(run_id):
            continue
        observed_at = str(row.get("gold_observed_at") or "")
        family = str(row.get("benchmark_family_id") or "")
        if not observed_at or not family:
            continue
        merged[(run_id or observed_at, family)] = row
    return sorted(
        merged.values(),
        key=lambda row: (
            str(row.get("gold_observed_at") or ""),
            str(row.get("benchmark_family_id") or ""),
        ),
    )


def _read_existing_benchmark_history(ref: str) -> Any:
    try:
        payload = read_json(ref)
    except FileNotFoundError:
        return []
    except Exception as exc:
        error = getattr(exc, "response", {}).get("Error", {})
        if str(error.get("Code") or "") in {"404", "NoSuchKey", "NotFound"}:
            return []
        raise
    return payload.get("rows", []) if isinstance(payload, dict) else []


def _public_market_state_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in [
            "observation_id",
            "observed_at",
            "resource_market",
            "resource_type",
            "provider",
            "source_connector",
            "source_role",
            "measurement_kind",
            "measurement_scope",
            "unit",
            "total_units",
            "rented_units",
            "available_units",
            "pending_units",
            "rented_share",
            "available_share",
            "stock_status",
            "count_precision",
            "numerator_definition",
            "denominator_definition",
            "aggregation_eligible",
            "aggregation_exclusion_reason",
            "source_url",
            "methodology_version",
            "notes",
            "calculated_at",
            "gold_run_id",
            "gold_observed_at",
            "gold_observed_date",
        ]
    }


def _merge_public_market_state_history(
    existing_rows: Any,
    current_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    candidates = [
        row
        for row in (existing_rows if isinstance(existing_rows, list) else [])
        if isinstance(row, dict)
        and row.get("measurement_kind") == "rental_occupancy"
        and row.get("resource_type") in PUBLIC_MARKET_STATE_HISTORY_RESOURCES
        and row.get("aggregation_eligible") is not False
    ]
    candidates.extend(current_rows)
    for row in candidates:
        observation_id = str(row.get("observation_id") or "")
        observed_at = str(row.get("gold_observed_at") or row.get("observed_at") or "")
        run_id = str(row.get("gold_run_id") or "")
        if not observation_id or not observed_at:
            continue
        merged[(run_id or observed_at, observation_id)] = row
    return sorted(
        merged.values(),
        key=lambda row: (
            str(row.get("gold_observed_at") or row.get("observed_at") or ""),
            str(row.get("measurement_kind") or ""),
            str(row.get("provider") or ""),
            str(row.get("resource_type") or ""),
            str(row.get("source_connector") or ""),
        ),
    )


def _read_existing_market_state_history(ref: str) -> Any:
    try:
        payload = read_json(ref)
    except FileNotFoundError:
        return []
    except Exception as exc:
        error = getattr(exc, "response", {}).get("Error", {})
        if str(error.get("Code") or "") in {"404", "NoSuchKey", "NotFound"}:
            return []
        raise
    return payload.get("history_rows", []) if isinstance(payload, dict) else []


def _public_benchmark_constituent(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in [
            "benchmark_value_id",
            "benchmark_symbol",
            "benchmark_family_id",
            "benchmark_label",
            "methodology_version",
            "methodology_query_id",
            "listing_id",
            "provider",
            "source_connector",
            "source_offer_id",
            "gpu_model",
            "gpu_raw_name",
            "gpu_count",
            "available_gpu_count",
            "vram_gb",
            "price_usd_gpu_hr",
            "price_usd_instance_hr",
            "country",
            "region",
            "is_spot",
            "is_secure",
            "availability_status",
            "included",
            "inclusion_reason",
            "exclusion_reason",
            "constituent_rank",
            "provider_rank",
            "is_floor_constituent",
            "observed_at",
            "has_raw_evidence",
            "source_run_id",
            "calculated_at",
        ]
    }
