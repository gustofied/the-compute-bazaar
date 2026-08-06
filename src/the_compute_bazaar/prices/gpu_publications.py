"""Publish immutable GPU benchmark cards."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from ..publication_contract import (
    PUBLICATION_ROUTE_SCHEMA_VERSION,
    PublicationRoute,
)
from .publication_chart_common import (
    GPU_FAMILIES,
    GPU_RANGES,
    GPU_RANGE_PRESENTATION,
    _latest_observed_at,
    _parse_datetime,
    _visible_gpu_series,
)
from .publication_gpu_chart import render_gpu_benchmark_publication
from .publication_metadata import (
    gpu_publication_metadata,
)
from .publication_page import publication_html
from .storage import write_bytes, write_json


from .publication_store import (
    DEFAULT_ARTICLE_URL,
    DEFAULT_PUBLIC_DATA_BASE_URL,
    PUBLICATION_SCHEMA_VERSION,
    _join,
    _latest_card_observed_at,
    _live_gpu_url,
    _publication_digest,
)


def publish_gpu_benchmark_publications(
    *,
    output_root: str,
    cards: Mapping[str, dict[str, Any]],
    public_base_url: str | None = None,
    article_url: str | None = None,
) -> dict[str, Any]:
    """Publish immutable GPU chart pages and add their links to each card."""
    public_base = (
        public_base_url
        or os.getenv("COMPUTE_BAZAAR_PUBLIC_BASE_URL")
        or DEFAULT_PUBLIC_DATA_BASE_URL
    ).rstrip("/")
    live_article = (
        article_url or os.getenv("COMPUTE_BAZAAR_ARTICLE_URL") or DEFAULT_ARTICLE_URL
    )
    normalized_cards = {
        family: cards[family] for family in GPU_FAMILIES if family in cards
    }
    content_digest = _publication_digest(
        normalized_cards,
        public_base_url=public_base,
        article_url=live_article,
    )
    latest_observed_at = _latest_card_observed_at(normalized_cards)
    revision = PublicationRoute.create(
        card_id="gpu-index",
        subject_id="market",
        view_id="all-views",
        observed_at=latest_observed_at,
        content_digest=content_digest,
    ).revision
    publication_rows: list[dict[str, Any]] = []

    for family, card in normalized_cards.items():
        range_links: dict[str, dict[str, Any]] = {}
        for range_id in GPU_RANGES:
            range_presentation = GPU_RANGE_PRESENTATION[range_id]
            visible_series = _visible_gpu_series(normalized_cards, range_id)
            route_observed_at = (
                _latest_observed_at(visible_series.get(family, []))
                or _parse_datetime(card.get("as_of"))
                or latest_observed_at
            )
            route = PublicationRoute.create(
                card_id="gpu-index",
                subject_id=family,
                view_id=range_presentation["path"],
                observed_at=route_observed_at,
                content_digest=content_digest,
            )
            page_path = route.page_path
            image_path = route.image_path
            page_ref = _join(output_root, page_path)
            image_ref = _join(output_root, image_path)
            page_url = f"{public_base}/{route.public_path}"
            image_url = f"{public_base}/{image_path}"
            live_url = _live_gpu_url(
                article_url=live_article,
                family=family,
                range_id=range_id,
            )
            image = render_gpu_benchmark_publication(
                cards=normalized_cards,
                selected_family=family,
                range_id=range_id,
            )
            metadata = gpu_publication_metadata(
                cards=normalized_cards,
                selected_family=family,
                range_id=range_id,
                page_url=page_url,
                image_url=image_url,
                live_url=live_url,
                route=route,
            )
            write_bytes(
                image_ref,
                image,
                content_type="image/png",
                cache_control="public, max-age=31536000, immutable",
            )
            write_bytes(
                page_ref,
                publication_html(metadata).encode("utf-8"),
                content_type="text/html; charset=utf-8",
                cache_control="public, max-age=31536000, immutable",
            )
            range_links[range_id] = {
                "publication_id": route.publication_id,
                "card_id": "gpu-index",
                "subject": {
                    "id": family,
                    "label": f"{family} GPU",
                },
                "view": {
                    "id": range_id,
                    "label": range_presentation["label"],
                    "path": range_presentation["path"],
                },
                "url": page_url,
                "image_url": image_url,
                "live_url": live_url,
                "revision": route.revision,
                "observed_at": metadata["observed_at"],
                "title": metadata["title"],
                "description": metadata["description"],
                "value": metadata["value"],
                "change_pct": metadata["change_pct"],
                "change_label": metadata["change_label"],
                "change_direction": metadata["change_direction"],
                "display_line": metadata["display_line"],
            }
            publication_rows.append(
                {
                    "family_id": family,
                    "range": range_id,
                    **range_links[range_id],
                }
            )

        card["publication"] = {
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "route_schema_version": PUBLICATION_ROUTE_SCHEMA_VERSION,
            "kind": "frozen_chart_snapshot",
            "card_id": "gpu-index",
            "default_range": "1d",
            "ranges": range_links,
        }

    manifest_ref = _join(
        output_root,
        "publications/gpu-index/manifest.json",
    )
    manifest = {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "route_schema_version": PUBLICATION_ROUTE_SCHEMA_VERSION,
        "publication_type": "gpu_benchmark",
        "revision": revision,
        "publication_count": len(publication_rows),
        "rows": publication_rows,
    }
    write_json(manifest_ref, manifest)
    return {
        "manifest_ref": manifest_ref,
        "revision": revision,
        "publication_count": len(publication_rows),
        "rows": publication_rows,
    }
