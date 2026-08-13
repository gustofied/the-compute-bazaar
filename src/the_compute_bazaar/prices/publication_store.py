"""Store immutable publication pages, images, metadata, and pointers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode

from ..contracts import (
    PUBLICATION_CONTRACT,
    PUBLICATION_ROUTE_CONTRACT,
)
from ..publication_contract import PublicationRoute
from .publication_chart_common import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    _parse_datetime,
)
from .publication_page import publication_html
from .storage import write_bytes


# Immutable publication URLs include a render profile in their content digest.
# Bump the relevant profile when its renderer changes so old previews stay
# frozen while newly generated links receive the current visual treatment.
PUBLICATION_RENDER_PROFILE = "social_png_rgb_1200x630_market_cards"
GPU_PUBLICATION_RENDER_PROFILE = "social_png_rgb_1200x630_gpu_index_v8"

DEFAULT_PUBLIC_DATA_BASE_URL = "https://bazaar.adamsioud.com"

DEFAULT_ARTICLE_URL = (
    "https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html"
)


def _publish_market_card_state(
    *,
    output_root: str,
    public_base_url: str,
    card_id: str,
    subject_id: str,
    view_id: str,
    observed_at: datetime | None,
    content_digest: str,
    live_url: str,
    data_url: str,
    image: bytes,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    route = PublicationRoute.create(
        card_id=card_id,
        subject_id=subject_id,
        view_id=view_id,
        observed_at=observed_at,
        content_digest=content_digest,
    )
    page_url = f"{public_base_url}/{route.public_path}"
    image_url = f"{public_base_url}/{route.image_path}"
    full_metadata = {
        **dict(metadata),
        "page_url": page_url,
        "image_url": image_url,
        "live_url": live_url,
        "data_url": data_url,
        "revision": route.revision,
        "publication_id": route.publication_id,
        "route": route.as_dict(),
    }
    write_bytes(
        _join(output_root, route.image_path),
        image,
        content_type="image/png",
        cache_control="public, max-age=31536000, immutable",
    )
    write_bytes(
        _join(output_root, route.page_path),
        publication_html(full_metadata).encode("utf-8"),
        content_type="text/html; charset=utf-8",
        cache_control="public, max-age=31536000, immutable",
    )
    return {
        "publication_id": route.publication_id,
        "card_id": card_id,
        "subject": {
            "id": subject_id,
            "label": metadata["subject_label"],
        },
        "view": {
            "id": view_id,
            "label": metadata["view_label"],
        },
        "url": page_url,
        "image_url": image_url,
        "live_url": live_url,
        "revision": route.revision,
        "observed_at": metadata["observed_at"],
        "title": metadata["title"],
        "description": metadata["description"],
        "value": metadata.get("value"),
        "change_pct": metadata.get("change_pct"),
        "change_label": metadata.get("change_label"),
        "change_direction": metadata.get("change_direction"),
        "display_line": metadata["display_line"],
    }


def _card_publication_contract(
    *,
    card_id: str,
    default_state: str,
    states: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "contract": PUBLICATION_CONTRACT,
        "route_contract": PUBLICATION_ROUTE_CONTRACT,
        "kind": "crawler_preview_live_handoff",
        "card_id": card_id,
        "default_state": default_state,
        "states": {key: dict(value) for key, value in states.items()},
    }


def _market_card_publication_digest(
    cards: Mapping[str, Mapping[str, Any]],
    *,
    public_base_url: str,
    article_url: str,
) -> str:
    canonical_cards = {
        card_id: {key: value for key, value in card.items() if key != "publication"}
        for card_id, card in cards.items()
    }
    publication_material = {
        "contract": PUBLICATION_CONTRACT,
        "route_contract": PUBLICATION_ROUTE_CONTRACT,
        "render_profile": PUBLICATION_RENDER_PROFILE,
        "image_width": IMAGE_WIDTH,
        "image_height": IMAGE_HEIGHT,
        "public_base_url": public_base_url,
        "article_url": article_url,
        "cards": canonical_cards,
    }
    canonical = json.dumps(
        publication_material,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()[:10]


def _live_market_card_url(
    *,
    article_url: str,
    card_id: str,
    state: Mapping[str, str],
    anchor: str,
) -> str:
    query = urlencode(
        {
            "card": card_id,
            "view": "detail",
            **dict(state),
        }
    )
    return f"{article_url.split('?', 1)[0]}?{query}#{anchor}"


def _publication_digest(
    cards: Mapping[str, Mapping[str, Any]],
    *,
    public_base_url: str,
    article_url: str,
    render_profile: str = PUBLICATION_RENDER_PROFILE,
) -> str:
    canonical_cards = {
        family: {key: value for key, value in card.items() if key != "publication"}
        for family, card in cards.items()
    }
    publication_material = {
        "contract": PUBLICATION_CONTRACT,
        "route_contract": PUBLICATION_ROUTE_CONTRACT,
        "render_profile": render_profile,
        "image_width": IMAGE_WIDTH,
        "image_height": IMAGE_HEIGHT,
        "public_base_url": public_base_url,
        "article_url": article_url,
        "cards": canonical_cards,
    }
    canonical = json.dumps(
        publication_material,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()[:10]


def _latest_card_observed_at(
    cards: Mapping[str, Mapping[str, Any]],
) -> datetime | None:
    observations: list[datetime] = []
    for card in cards.values():
        parsed_as_of = _parse_datetime(card.get("as_of"))
        if parsed_as_of:
            observations.append(parsed_as_of)
        for row in card.get("series") or []:
            if not isinstance(row, Mapping):
                continue
            parsed_row = _parse_datetime(row.get("observed_at"))
            if parsed_row:
                observations.append(parsed_row)
    return max(observations, default=None)


def _live_gpu_url(*, article_url: str, family: str, range_id: str) -> str:
    query = urlencode(
        {
            "card": "gpu-index",
            "view": "detail",
            "gpu": family,
            "range": range_id,
        }
    )
    return f"{article_url.split('?', 1)[0]}?{query}#gpu-benchmark-card"


def _live_prime_offer_url(*, article_url: str, family: str) -> str:
    query = urlencode(
        {
            "card": "prime-offer-shelf",
            "view": "detail",
            "primeGpu": family,
        }
    )
    return f"{article_url.split('?', 1)[0]}?{query}#prime-offer-shelf-card"


def _join(root: str, path: str) -> str:
    return "/".join([root.rstrip("/"), path.lstrip("/")])
