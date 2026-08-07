"""Shape Gold tables into public, static market-card snapshots."""

from __future__ import annotations

from typing import Any

from ..contracts import CARD_CONTRACT, GOLD_MARKET_CONTRACT
from .gold_manifest import read_latest_gold_manifest
from .gold_queries import (
    query_gold_gpu_price_index,
    query_gold_gpu_price_index_constituents,
    query_gold_gpu_price_index_history,
    query_gold_prime_frontier_offer_market,
)
from .gold_models import BENCHMARK_METHODOLOGY
from .offer_reference import (
    PRIME_FRONTIER_API_DOCS_URL,
    PRIME_FRONTIER_METHODOLOGY,
    PRIME_FRONTIER_PROVISION_DOCS_URL,
    PRIME_FRONTIER_SCOPE,
    PRIME_FRONTIER_SOURCE_URL,
)
from .prime_public_data import public_prime_frontier_products
from .gpu_publications import publish_gpu_benchmark_publications
from .prime_publications import publish_prime_offer_shelf_publications
from .public_view_gpu import GPU_FAMILIES, gpu_benchmark_view
from .public_view_prime import prime_frontier_view
from .public_series import (
    has_benchmark_value,
    public_benchmark_constituent,
    public_benchmark_history_value,
    public_benchmark_value,
)
from .schemas import utc_now
from .storage import write_json


def export_public_cards(
    *,
    lake_root: str,
    output_root: str,
) -> dict[str, Any]:
    """Export public JSON snapshots for static D3/blog consumers."""
    manifest = read_latest_gold_manifest(lake_root)
    public_manifest = _public_gold_manifest(
        manifest,
        exported_at=utc_now().isoformat(),
    )
    benchmark_values_payload = query_gold_gpu_price_index(
        lake_root=lake_root,
        manifest=manifest,
    )
    benchmark_values = benchmark_values_payload["rows"]
    # Benchmark evidence is a complete audit surface, not a sampled dashboard table.
    benchmark_constituents = query_gold_gpu_price_index_constituents(
        lake_root=lake_root,
        manifest=manifest,
    )["rows"]
    public_benchmark_values = [public_benchmark_value(row) for row in benchmark_values]
    public_benchmark_constituents = [
        public_benchmark_constituent(row) for row in benchmark_constituents
    ]
    benchmark_history_payload = query_gold_gpu_price_index_history(
        lake_root=lake_root,
        manifest=manifest,
    )
    public_benchmark_history = [
        public_benchmark_history_value(row)
        for row in benchmark_history_payload["rows"]
        if has_benchmark_value(row)
    ]
    prime_frontier_payload = query_gold_prime_frontier_offer_market(
        lake_root=lake_root,
        manifest=manifest,
    )
    output_refs = {
        "manifest": "/".join([output_root.rstrip("/"), "manifest.json"]),
        "prime_frontier_offer_shelf": "/".join(
            [output_root.rstrip("/"), "prime-frontier-offer-shelf.json"]
        ),
    }
    prime_frontier_products = public_prime_frontier_products(
        payload=prime_frontier_payload,
        benchmark_values=public_benchmark_values,
        benchmark_history=public_benchmark_history,
    )
    prime_source = {
        "name": "Prime Intellect GPU availability",
        "market_url": PRIME_FRONTIER_SOURCE_URL,
        "api_documentation_url": PRIME_FRONTIER_API_DOCS_URL,
        "provisioning_documentation_url": PRIME_FRONTIER_PROVISION_DOCS_URL,
    }
    prime_measurement_notes = [
        "Each family reference is the median of one lowest eligible base rate per upstream provider.",
        "Availability events record configuration entry, exit, and repricing.",
    ]
    prime_frontier_shelf_public = {
        "contract": CARD_CONTRACT,
        "card_type": "prime_frontier_offer_shelf_collection",
        "manifest": public_manifest,
        "methodology": PRIME_FRONTIER_METHODOLOGY,
        "reference_scope": PRIME_FRONTIER_SCOPE,
        "source": prime_source,
        "measurement_notes": prime_measurement_notes,
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
            source=prime_source,
            measurement_notes=prime_measurement_notes,
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
    write_json(output_refs["manifest"], public_manifest)
    write_json(
        output_refs["prime_frontier_offer_shelf"],
        prime_frontier_shelf_public,
    )
    for family, card in benchmark_cards.items():
        write_json(output_refs[f"gpu_benchmark_{family.lower()}"], card)
    for family, card in prime_cards.items():
        write_json(output_refs[f"prime_frontier_{family.lower()}"], card)
    return {
        "output_refs": output_refs,
        "row_counts": {
            "gpu_price_index": len(benchmark_values),
            "benchmark_history": len(public_benchmark_history),
            "benchmark_constituents": len(benchmark_constituents),
            "prime_frontier_reference_history": len(
                prime_frontier_payload.get("history", [])
            ),
            "prime_frontier_ladder": len(prime_frontier_payload.get("ladder", [])),
            "prime_frontier_events": len(prime_frontier_payload.get("events", [])),
            "prime_frontier_offers": len(prime_frontier_payload.get("offers", [])),
            "gpu_benchmark_cards": len(benchmark_cards),
            "gpu_publications": gpu_publications["publication_count"],
            "prime_frontier_cards": len(prime_cards),
        },
        "source_gold_manifest_ref": manifest.get("manifest_ref"),
    }


def _public_gold_manifest(
    manifest: dict[str, Any],
    *,
    exported_at: str | None = None,
) -> dict[str, Any]:
    return {
        "contract": GOLD_MARKET_CONTRACT,
        "methodology": manifest.get("methodology"),
        "run_id": manifest.get("run_id"),
        "observed_at": manifest.get("observed_at"),
        "observed_date": manifest.get("observed_date"),
        "provider_scope": manifest.get("provider_scope"),
        "row_counts": manifest.get("row_counts"),
        "source_run_ids": manifest.get("source_run_ids"),
        "exported_at": exported_at,
    }
