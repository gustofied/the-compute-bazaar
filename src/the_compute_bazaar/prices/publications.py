"""Frozen, crawler-readable publication links for public market cards."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from html import escape
from typing import Any
from urllib.parse import urlencode

from ..publication_contract import (
    PUBLICATION_ROUTE_SCHEMA_VERSION,
    PublicationRoute,
)
from .publication_charts import (
    GPU_FAMILIES,
    GPU_RANGES,
    GPU_RANGE_PRESENTATION,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    PRIME_OFFER_FAMILIES,
    _finite_number,
    _format_cents,
    _format_observed,
    _format_observed_date,
    _format_usd,
    _latest_observed_at,
    _parse_datetime,
    _prime_publication_series,
    _range_change,
    _series_change,
    _visible_gpu_series,
    _workload_observed_at,
    render_gpu_benchmark_publication,
    render_prime_offer_shelf_publication,
    render_sandbox_workload_publication,
)
from .storage import write_bytes, write_json


PUBLICATION_SCHEMA_VERSION = "compute_bazaar_publication_v7"
PUBLICATION_RENDER_PROFILE = "social_png_rgb_1200x630_market_cards_v3"
DEFAULT_PUBLIC_DATA_BASE_URL = "https://bazaar.adamsioud.com"
DEFAULT_ARTICLE_URL = (
    "https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html"
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
            metadata = _gpu_publication_metadata(
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
                _publication_html(metadata).encode("utf-8"),
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
            metadata=_prime_offer_publication_metadata(
                card=card,
                family=family,
                observed_at=observed_at,
            ),
        )
        card["publication"] = _card_publication_contract(
            card_id="prime-offer-shelf",
            default_state=family,
            states={family: link},
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
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "route_schema_version": PUBLICATION_ROUTE_SCHEMA_VERSION,
        "publication_type": "prime_offer_market",
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


def publish_sandbox_workload_publication(
    *,
    output_root: str,
    workload_card: dict[str, Any],
    public_base_url: str | None = None,
    article_url: str | None = None,
) -> dict[str, Any]:
    """Publish the latest measured StarSling workload-cost card."""
    public_base = (
        public_base_url
        or os.getenv("COMPUTE_BAZAAR_PUBLIC_BASE_URL")
        or DEFAULT_PUBLIC_DATA_BASE_URL
    ).rstrip("/")
    live_article = (
        article_url or os.getenv("COMPUTE_BAZAAR_ARTICLE_URL") or DEFAULT_ARTICLE_URL
    )
    content_digest = _market_card_publication_digest(
        {"workload": workload_card},
        public_base_url=public_base,
        article_url=live_article,
    )
    observed_at = _workload_observed_at(workload_card)
    link = _publish_market_card_state(
        output_root=output_root,
        public_base_url=public_base,
        card_id="sandbox-cost",
        subject_id="workload",
        view_id="estimated-cost",
        observed_at=observed_at,
        content_digest=content_digest,
        live_url=_live_market_card_url(
            article_url=live_article,
            card_id="sandbox-cost",
            state={},
            anchor="sandbox-benchmark-card",
        ),
        data_url=f"{public_base}/sandbox/workload.json",
        image=render_sandbox_workload_publication(workload_card),
        metadata=_sandbox_workload_publication_metadata(
            card=workload_card,
            observed_at=observed_at,
        ),
    )
    workload_card["publication"] = _card_publication_contract(
        card_id="sandbox-cost",
        default_state="cost",
        states={"cost": link},
    )
    revision = PublicationRoute.create(
        card_id="sandbox-cost",
        subject_id="workload",
        view_id="estimated-cost",
        observed_at=observed_at,
        content_digest=content_digest,
    ).revision
    manifest_ref = _join(
        output_root,
        "publications/sandbox-cost/manifest.json",
    )
    publication_rows = [{"state_id": "cost", **link}]
    manifest = {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "route_schema_version": PUBLICATION_ROUTE_SCHEMA_VERSION,
        "publication_type": "sandbox_workload_cost",
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


def _gpu_publication_metadata(
    *,
    cards: Mapping[str, Mapping[str, Any]],
    selected_family: str,
    range_id: str,
    page_url: str,
    image_url: str,
    live_url: str,
    route: PublicationRoute,
) -> dict[str, Any]:
    series = _visible_gpu_series(cards, range_id)
    rows = series.get(selected_family, [])
    latest = rows[-1] if rows else None
    card = cards[selected_family]
    coverage = card.get("coverage") or {}
    value = _format_usd(latest["value"]) if latest else "pending"
    observed_at = latest["date"].isoformat() if latest else str(card.get("as_of") or "")
    provider_count = int(coverage.get("provider_count") or 0)
    change = _range_change(rows, range_id)
    title_parts = [f"{selected_family} GPU Price Index", f"{value}/GPU-hour"]
    if change["value"] is not None:
        title_parts.append(change["label"])
    title = " | ".join(title_parts)
    description = (
        f"{selected_family} observed GPU benchmark at {value} per GPU-hour, "
        f"{change['label'].lower()}. "
        f"Observed through {_format_observed_date(latest['date'] if latest else None)}"
    )
    if provider_count:
        description += f" across {provider_count} providers"
    description += "."
    display_line = (
        f"{selected_family} / {GPU_RANGE_PRESENTATION[range_id]['label']} / "
        f"{str(change['label']).lower()} / observed "
        f"{_format_observed_date(latest['date'] if latest else None).replace(' at ', ', ')}"
    )
    return {
        "title": title,
        "description": description,
        "page_url": page_url,
        "image_url": image_url,
        "live_url": live_url,
        "data_url": (
            f"{page_url.split('/publications/', 1)[0]}/gpu-benchmark/"
            f"{selected_family.lower()}.json"
        ),
        "image_alt": (
            f"{selected_family} GPU price index at {value} per GPU-hour, "
            f"{change['label'].lower()}"
        ),
        "family_id": selected_family,
        "range": range_id,
        "range_label": GPU_RANGE_PRESENTATION[range_id]["label"],
        "value": value,
        "change_pct": change["value"],
        "change_label": change["label"],
        "change_direction": change["direction"],
        "observed_at": observed_at,
        "observed_label": _format_observed(
            latest["date"] if latest else _parse_datetime(card.get("as_of"))
        ),
        "footer_label": display_line,
        "display_line": display_line,
        "revision": route.revision,
        "publication_id": route.publication_id,
        "route": route.as_dict(),
    }


def _prime_offer_publication_metadata(
    *,
    card: Mapping[str, Any],
    family: str,
    observed_at: datetime | None,
) -> dict[str, Any]:
    rows = _prime_publication_series(card)
    latest = rows[-1] if rows else None
    value = _format_usd(latest["price"]) if latest else "pending"
    offers = int(latest["offers"]) if latest else 0
    change = _series_change(rows)
    observed_label = _format_observed_date(observed_at)
    display_line = (
        f"{family} / {value} per GPU-hour / {offers} "
        f"{'offer' if offers == 1 else 'offers'} / observed "
        f"{observed_label.replace(' at ', ', ')}"
    )
    return {
        "title": (
            f"Prime {family} GPU market | {value}/GPU-hour | "
            f"{offers} {'offer' if offers == 1 else 'offers'}"
        ),
        "description": (
            f"Prime {family} observed public market price at {value} per "
            f"GPU-hour with {offers} "
            f"{'offer' if offers == 1 else 'offers'}. "
            f"{change['label']}. Observed {observed_label}."
        ),
        "image_alt": (
            f"Prime {family} market price at {value} per GPU-hour with "
            f"{offers} {'offer' if offers == 1 else 'offers'}"
        ),
        "subject_label": f"Prime {family} GPU market",
        "view_label": "Price and offers",
        "value": value,
        "observed_at": observed_at.isoformat() if observed_at else "",
        "observed_label": _format_observed(observed_at),
        "footer_label": display_line,
        "display_line": display_line,
        "change_pct": change["value"],
        "change_label": change["label"],
        "change_direction": change["direction"],
    }


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
        _publication_html(full_metadata).encode("utf-8"),
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
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "route_schema_version": PUBLICATION_ROUTE_SCHEMA_VERSION,
        "kind": "crawler_preview_live_handoff",
        "card_id": card_id,
        "default_state": default_state,
        "states": {key: dict(value) for key, value in states.items()},
    }


def _sandbox_workload_publication_metadata(
    *,
    card: Mapping[str, Any],
    observed_at: datetime | None,
) -> dict[str, Any]:
    headline = card.get("headline") or {}
    raw_value = _finite_number(
        headline.get("median_estimated_cost_usd")
    )
    value = _format_cents(raw_value)
    subject_label = "Measured workload cost"
    view_label = "Latest measured run"
    measure = "estimated processor-and-memory cost"
    observed_label = _format_observed_date(observed_at)
    display_line = (
        f"StarSling / {value} median cost per job / "
        f"observed {observed_label.replace(' at ', ', ')}"
    )
    return {
        "title": f"Measured workload cost | {value} median per job",
        "description": (
            f"Median {measure} for the latest compatible StarSling HPC Sandbox "
            f"Benchmark run. Observed {observed_label}."
        ),
        "image_alt": (
            f"Latest StarSling HPC Sandbox Benchmark run with median estimated "
            f"job cost of {value}"
        ),
        "subject_label": subject_label,
        "view_label": view_label,
        "value": value,
        "observed_at": observed_at.isoformat() if observed_at else "",
        "observed_label": _format_observed(observed_at),
        "footer_label": display_line,
        "display_line": display_line,
        "change_pct": None,
        "change_label": None,
        "change_direction": "unknown",
    }


def _publication_html(metadata: Mapping[str, Any]) -> str:
    title = escape(str(metadata["title"]))
    description = escape(str(metadata["description"]))
    page_url = escape(str(metadata["page_url"]), quote=True)
    image_url = escape(str(metadata["image_url"]), quote=True)
    live_url = escape(str(metadata["live_url"]), quote=True)
    data_url = escape(str(metadata["data_url"]), quote=True)
    image_alt = escape(str(metadata["image_alt"]), quote=True)
    footer_label = escape(
        str(
            metadata.get("footer_label")
            or " / ".join(
                (
                    str(metadata.get("family_id") or ""),
                    str(metadata.get("range_label") or ""),
                    str(metadata.get("change_label") or "").lower(),
                    str(metadata.get("observed_label") or "").lower(),
                )
            ).strip(" /")
        )
    )
    redirect_url = json.dumps(str(metadata["live_url"])).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <link rel="canonical" href="{page_url}">
  <meta property="og:title" content="{title}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="Compute Bazaar">
  <meta property="og:url" content="{page_url}">
  <meta property="og:description" content="{description}">
  <meta property="og:image" content="{image_url}">
  <meta property="og:image:secure_url" content="{image_url}">
  <meta property="og:image:type" content="image/png">
  <meta property="og:image:width" content="{IMAGE_WIDTH}">
  <meta property="og:image:height" content="{IMAGE_HEIGHT}">
  <meta property="og:image:alt" content="{image_alt}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="{page_url}">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{image_url}">
  <meta name="twitter:image:alt" content="{image_alt}">
  <script>
    window.location.replace({redirect_url});
  </script>
  <style>
    :root {{
      color-scheme: light;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      background: #efede4;
      color: #142027;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      min-height: 100vh;
      margin: 0;
      display: grid;
      place-items: center;
      padding: clamp(18px, 5vw, 72px);
      background: #efede4;
    }}
    main {{ width: min(1200px, 100%); }}
    a.preview {{
      display: block;
      border: 1px solid #a7b1b3;
      background: #f8f5eb;
      box-shadow: 0 24px 70px rgb(20 32 39 / 12%);
    }}
    img {{ display: block; width: 100%; height: auto; }}
    footer {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      padding-top: 14px;
      font-size: 13px;
    }}
    footer p {{ margin: 0; color: #5f6f76; }}
    footer nav {{ display: flex; gap: 16px; }}
    footer a {{ color: #315f82; text-underline-offset: 3px; }}
    @media (max-width: 620px) {{
      body {{ padding: 12px; }}
      footer {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <main>
    <a class="preview" href="{live_url}" aria-label="Open the interactive card">
      <img src="{image_url}" width="{IMAGE_WIDTH}" height="{IMAGE_HEIGHT}" alt="{image_alt}">
    </a>
    <footer>
      <p>{footer_label}</p>
      <nav aria-label="Publication links">
        <a href="{live_url}">Open interactive card</a>
        <a href="{data_url}">Open data</a>
      </nav>
    </footer>
  </main>
</body>
</html>
"""


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
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "route_schema_version": PUBLICATION_ROUTE_SCHEMA_VERSION,
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
            "view": "share",
            "present": "card",
            **dict(state),
        }
    )
    return f"{article_url.split('?', 1)[0]}?{query}#{anchor}"


def _publication_digest(
    cards: Mapping[str, Mapping[str, Any]],
    *,
    public_base_url: str,
    article_url: str,
) -> str:
    canonical_cards = {
        family: {key: value for key, value in card.items() if key != "publication"}
        for family, card in cards.items()
    }
    publication_material = {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "route_schema_version": PUBLICATION_ROUTE_SCHEMA_VERSION,
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
            "view": "share",
            "present": "card",
            "gpu": family,
            "range": range_id,
        }
    )
    return f"{article_url.split('?', 1)[0]}?{query}#gpu-benchmark-card"


def _live_prime_offer_url(*, article_url: str, family: str) -> str:
    query = urlencode(
        {
            "card": "prime-offer-shelf",
            "view": "share",
            "present": "card",
            "primeGpu": family,
        }
    )
    return f"{article_url.split('?', 1)[0]}?{query}#prime-offer-shelf-card"


def _join(root: str, path: str) -> str:
    return "/".join([root.rstrip("/"), path.lstrip("/")])
