"""Shape Gold tables into public, static market-card snapshots."""

from __future__ import annotations

from typing import Any

from ..contracts import CARD_CONTRACT, GOLD_MARKET_CONTRACT, transform_contract
from .gold import MARKET_STATE_METHODOLOGY
from .gold_manifest import read_latest_gold_manifest
from .gold_queries import (
    query_gold_gpu_price_index,
    query_gold_gpu_price_index_constituents,
    query_gold_gpu_price_index_history,
    query_gold_listings,
    query_gold_market_state,
    query_gold_market_state_history,
    query_gold_prime_frontier_offer_market,
    query_gold_provider_comparison,
)
from .gold_models import BENCHMARK_FAMILIES, BENCHMARK_METHODOLOGY
from .offer_reference import (
    PRIME_FRONTIER_API_DOCS_URL,
    PRIME_FRONTIER_METHODOLOGY,
    PRIME_FRONTIER_PROVISION_DOCS_URL,
    PRIME_FRONTIER_SCOPE,
    PRIME_FRONTIER_SOURCE_URL,
)
from .prime_public_data import public_prime_frontier_products
from .public_view_gpu import GPU_FAMILIES, gpu_benchmark_view
from .public_view_market import market_overview_view, market_state_view
from .public_view_prime import prime_frontier_view
from .publications import (
    publish_gpu_benchmark_publications,
    publish_prime_offer_shelf_publications,
)
from .public_series import (
    has_benchmark_value,
    is_public_market_state_history_row,
    merge_benchmark_history,
    merge_market_state_history,
    public_benchmark_constituent,
    public_benchmark_history_value,
    public_benchmark_value,
    public_market_state_row,
    read_benchmark_history,
    read_market_state_history,
)
from .schemas import utc_now
from .storage import write_json


def export_gold_dashboard_snapshot(
    *,
    lake_root: str,
    output_root: str,
    limit: int = 100,
    benchmark_history_limit: int = 24 * 90,
) -> dict[str, Any]:
    """Export public JSON snapshots for static D3/blog consumers."""
    manifest = read_latest_gold_manifest(lake_root)
    public_manifest = _public_gold_manifest(
        manifest,
        dashboard_exported_at=utc_now().isoformat(),
    )
    warnings = []
    benchmark_values_payload = query_gold_gpu_price_index(lake_root=lake_root)
    benchmark_values = benchmark_values_payload["rows"]
    # Benchmark evidence is a complete audit surface, not a sampled dashboard table.
    benchmark_constituents = query_gold_gpu_price_index_constituents(
        lake_root=lake_root
    )["rows"]
    public_benchmark_values = [public_benchmark_value(row) for row in benchmark_values]
    public_benchmark_constituents = [
        public_benchmark_constituent(row) for row in benchmark_constituents
    ]
    try:
        benchmark_history_payload = query_gold_gpu_price_index_history(
            lake_root=lake_root,
            history_limit=benchmark_history_limit,
            canonical_market_runs_only=True,
        )
    except Exception as exc:  # noqa: BLE001 - latest values should survive a history failure.
        benchmark_history_payload = {"history_manifest_count": 0, "rows": []}
        warnings.append(f"benchmark history export skipped: {exc}")
    public_benchmark_history = [
        public_benchmark_history_value(row)
        for row in benchmark_history_payload["rows"]
        if has_benchmark_value(row)
    ]
    benchmark_history_ref = "/".join(
        [output_root.rstrip("/"), "benchmark-history.json"]
    )
    existing_benchmark_history = read_benchmark_history(benchmark_history_ref)
    public_benchmark_history = merge_benchmark_history(
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
        public_market_state_row(row)
        for row in market_state
        if row.get("measurement_kind") in {"rental_occupancy", "availability_pressure"}
    ]
    public_market_state_history = merge_market_state_history(
        read_market_state_history(market_state_ref),
        [
            public_market_state_row(row)
            for row in market_state_history_payload["rows"]
            if is_public_market_state_history_row(row)
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
    prime_frontier_products = public_prime_frontier_products(
        payload=prime_frontier_payload,
        benchmark_values=public_benchmark_values,
        benchmark_history=public_benchmark_history,
    )
    prime_frontier_public = {
        "contract": CARD_CONTRACT,
        "card_type": "prime_frontier_offer_market_collection",
        "manifest": public_manifest,
        "methodology": PRIME_FRONTIER_METHODOLOGY,
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
        "contract": CARD_CONTRACT,
        "card_type": "prime_frontier_offer_shelf_collection",
        "manifest": public_manifest,
        "methodology": PRIME_FRONTIER_METHODOLOGY,
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
            methodology=BENCHMARK_METHODOLOGY,
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
            methodology=PRIME_FRONTIER_METHODOLOGY,
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
        "contract": CARD_CONTRACT,
        "card_type": "compute_market_state_collection",
        "manifest": public_manifest,
        "methodology": MARKET_STATE_METHODOLOGY,
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
            "methodology": BENCHMARK_METHODOLOGY,
            "families": BENCHMARK_FAMILIES,
            "rows": public_benchmark_values,
        },
    )
    write_json(
        output_refs["benchmark_history"],
        {
            "manifest": public_manifest,
            "methodology": BENCHMARK_METHODOLOGY,
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
            "methodology": BENCHMARK_METHODOLOGY,
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
    return transform_contract(
        {
            "methodology": manifest.get("methodology")
            or manifest.get("methodology_version"),
            "run_id": manifest.get("run_id"),
            "observed_at": manifest.get("observed_at"),
            "observed_date": manifest.get("observed_date"),
            "provider_scope": manifest.get("provider_scope"),
            "row_counts": manifest.get("row_counts"),
            "source_run_ids": manifest.get("source_run_ids"),
            "dashboard_exported_at": dashboard_exported_at,
        },
        contract=GOLD_MARKET_CONTRACT,
    )
