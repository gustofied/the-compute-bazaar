"""Publish immutable Prime offer-market cards."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from ..contracts import (
    PUBLICATION_CONTRACT,
    PUBLICATION_ROUTE_CONTRACT,
)
from ..publication_contract import PublicationRoute
from .publication_chart_common import (
    PRIME_OFFER_FAMILIES,
)
from .publication_metadata import (
    prime_offer_publication_metadata,
)
from .publication_profiles import PRIME_PUBLICATION_RENDER_PROFILE
from .publication_prime_chart import render_prime_offer_shelf_publication
from .storage import write_json


from .publication_store import (
    DEFAULT_ARTICLE_URL,
    DEFAULT_PUBLIC_DATA_BASE_URL,
    _card_publication_contract,
    _join,
    _latest_card_observed_at,
    _live_prime_offer_url,
    _publication_digest,
    _publish_market_card_state,
)


def publish_prime_offer_shelf_publications(
    *,
    output_root: str,
    cards: Mapping[str, dict[str, Any]],
    public_base_url: str | None = None,
    article_url: str | None = None,
) -> dict[str, Any]:
    """Publish immutable Prime price-and-visible-availability snapshots."""
    public_base = (
        public_base_url
        or os.getenv("COMPUTE_BAZAAR_PUBLIC_BASE_URL")
        or DEFAULT_PUBLIC_DATA_BASE_URL
    ).rstrip("/")
    live_article = (
        article_url or os.getenv("COMPUTE_BAZAAR_ARTICLE_URL") or DEFAULT_ARTICLE_URL
    )
    normalized_cards = {
        family: cards[family] for family in PRIME_OFFER_FAMILIES if family in cards
    }
    content_digest = _publication_digest(
        normalized_cards,
        public_base_url=public_base,
        article_url=live_article,
        render_profile=PRIME_PUBLICATION_RENDER_PROFILE,
    )
    publication_rows: list[dict[str, Any]] = []

    for family, card in normalized_cards.items():
        observed_at = _latest_card_observed_at({family: card})
        live_url = _live_prime_offer_url(
            article_url=live_article,
            family=family,
        )
        link = _publish_market_card_state(
            output_root=output_root,
            public_base_url=public_base,
            card_id="prime-gpu-market",
            subject_id=family,
            view_id="offer-shelf",
            observed_at=observed_at,
            content_digest=content_digest,
            live_url=live_url,
            data_url=f"{public_base}/prime-frontier-offer-shelf.json",
            image=render_prime_offer_shelf_publication(card=card),
            metadata=prime_offer_publication_metadata(
                card=card,
                family=family,
                observed_at=observed_at,
            ),
            render_profile=PRIME_PUBLICATION_RENDER_PROFILE,
        )
        card["publication"] = _card_publication_contract(
            card_id="prime-offer-shelf",
            default_state=family,
            states={family: link},
            render_profile=PRIME_PUBLICATION_RENDER_PROFILE,
        )
        publication_rows.append({"family_id": family, **link})

    latest_observed_at = _latest_card_observed_at(normalized_cards)
    revision = PublicationRoute.create(
        card_id="prime-gpu-market",
        subject_id="market",
        view_id="offer-shelf",
        observed_at=latest_observed_at,
        content_digest=content_digest,
    ).revision
    manifest_ref = _join(
        output_root,
        "publications/prime-gpu-market/manifest.json",
    )
    manifest = {
        "contract": PUBLICATION_CONTRACT,
        "route_contract": PUBLICATION_ROUTE_CONTRACT,
        "publication_type": "prime_offer_market",
        "render_profile": PRIME_PUBLICATION_RENDER_PROFILE,
        "renderer_revision": publication_rows[0]["renderer_revision"]
        if publication_rows
        else "unknown",
        "revision": revision,
        "publication_count": len(publication_rows),
        "rows": publication_rows,
    }
    write_json(manifest_ref, manifest)
    return {
        "manifest_ref": manifest_ref,
        "revision": revision,
        "render_profile": PRIME_PUBLICATION_RENDER_PROFILE,
        "renderer_revision": manifest["renderer_revision"],
        "publication_count": len(publication_rows),
        "rows": publication_rows,
    }
