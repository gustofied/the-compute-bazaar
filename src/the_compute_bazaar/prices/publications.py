"""Frozen, crawler-readable publication links for public market cards."""

from __future__ import annotations

import io
import json
import math
import os
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import escape
from typing import Any
from urllib.parse import urlencode

from ..publication_contract import (
    PUBLICATION_ROUTE_SCHEMA_VERSION,
    PublicationRoute,
)
from .storage import write_bytes, write_json


PUBLICATION_SCHEMA_VERSION = "compute_bazaar_publication_v5"
PUBLICATION_RENDER_PROFILE = "social_png_rgb_1200x630"
DEFAULT_PUBLIC_DATA_BASE_URL = "https://bazaar.adamsioud.com"
DEFAULT_ARTICLE_URL = (
    "https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html"
)
GPU_FAMILIES = ("H100", "H200", "B200", "B300")
GPU_RANGES: dict[str, timedelta | None] = {
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "all": None,
}
GPU_RANGE_PRESENTATION = {
    "1d": {"path": "1-day", "label": "1 day", "short_label": "1D"},
    "7d": {"path": "7-day", "label": "7 days", "short_label": "7D"},
    "all": {
        "path": "full-history",
        "label": "full retained history",
        "short_label": "ALL",
    },
}
IMAGE_WIDTH = 1200
IMAGE_HEIGHT = 630


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


def render_gpu_benchmark_publication(
    *,
    cards: Mapping[str, Mapping[str, Any]],
    selected_family: str,
    range_id: str,
) -> bytes:
    """Render the selected benchmark with the other families as context."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle

    if selected_family not in cards:
        raise ValueError(f"Unknown GPU publication family: {selected_family}")
    if range_id not in GPU_RANGES:
        raise ValueError(f"Unknown GPU publication range: {range_id}")

    series = _visible_gpu_series(cards, range_id)
    selected_rows = series.get(selected_family, [])
    paper = "#f8f5eb"
    ink = "#142027"
    muted = "#5f6f76"
    selected_color = "#315f82"
    band_color = "#91aecb"
    coral = "#a96552"
    rule = "#a7b1b3"
    family_colors = {
        "H100": "#587383",
        "H200": "#708690",
        "B200": "#899ba2",
        "B300": "#a0afb4",
    }

    figure = Figure(
        figsize=(IMAGE_WIDTH / 100, IMAGE_HEIGHT / 100),
        dpi=100,
        facecolor=paper,
    )
    canvas = FigureCanvasAgg(figure)
    figure.patches.append(
        Rectangle(
            (0.02, 0.035),
            0.96,
            0.93,
            transform=figure.transFigure,
            fill=False,
            edgecolor=rule,
            linewidth=1.5,
        )
    )
    figure.text(
        0.052,
        0.915,
        "GPU PRICE INDEX",
        color=muted,
        fontsize=13,
        fontweight=700,
        family="sans-serif",
    )
    observed_at = _latest_observed_at(selected_rows)
    figure.text(
        0.948,
        0.915,
        _format_observed(observed_at).upper(),
        color=muted,
        fontsize=11,
        family="sans-serif",
        horizontalalignment="right",
    )

    selected_latest = selected_rows[-1] if selected_rows else None
    change = _range_change(selected_rows, range_id)
    figure.text(
        0.052,
        0.825,
        selected_family,
        color=selected_color,
        fontsize=11,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.052,
        0.748,
        _format_usd(selected_latest["value"]) if selected_latest else "PENDING",
        color=ink,
        fontsize=36,
        family="serif",
    )
    figure.text(
        0.178,
        0.755,
        "USD / GPU-HOUR",
        color=muted,
        fontsize=8,
        family="sans-serif",
    )
    figure.text(
        0.948,
        0.755,
        str(change["label"]).upper(),
        color=coral,
        fontsize=9,
        fontweight=700,
        family="sans-serif",
        horizontalalignment="right",
    )

    axes = figure.add_axes((0.052, 0.19, 0.896, 0.47), facecolor=paper)
    axes.grid(axis="y", color=rule, alpha=0.28, linewidth=0.8)
    axes.set_axisbelow(True)
    all_rows = [row for rows in series.values() for row in rows]
    if all_rows:
        maximum = max(max(row["value"], row["upper"]) for row in all_rows)
        axes.set_ylim(0, max(maximum * 1.08, 1))
        for family in GPU_FAMILIES:
            rows = series.get(family, [])
            if not rows:
                continue
            dates = [row["date"] for row in rows]
            values = [row["value"] for row in rows]
            if family == selected_family:
                axes.fill_between(
                    dates,
                    [row["lower"] for row in rows],
                    [row["upper"] for row in rows],
                    color=band_color,
                    alpha=0.2,
                    linewidth=0,
                )
            axes.plot(
                dates,
                values,
                color=(
                    selected_color
                    if family == selected_family
                    else family_colors[family]
                ),
                linewidth=3.2 if family == selected_family else 1.7,
                alpha=1 if family == selected_family else 0.48,
                solid_capstyle="round",
                solid_joinstyle="round",
                zorder=4 if family == selected_family else 2,
            )
        locator = AutoDateLocator(minticks=4, maxticks=6)
        axes.xaxis.set_major_locator(locator)
        axes.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        axes.xaxis.get_offset_text().set_visible(False)
    else:
        axes.text(
            0.5,
            0.5,
            "HISTORY IS STILL BEING COLLECTED",
            transform=axes.transAxes,
            color=muted,
            fontsize=14,
            horizontalalignment="center",
            verticalalignment="center",
        )
        axes.set_ylim(0, 1)
        axes.set_xticks([])

    axes.yaxis.tick_right()
    axes.tick_params(
        axis="both",
        colors=muted,
        labelsize=8,
        length=0,
        pad=7,
    )
    axes.yaxis.set_major_formatter(lambda value, _position: _format_axis_usd(value))
    for spine in axes.spines.values():
        spine.set_visible(False)

    figure.text(
        0.052,
        0.105,
        selected_family,
        color=selected_color,
        fontsize=11,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.5,
        0.105,
        "OBSERVED PUBLIC MARKET PRICES",
        color=muted,
        fontsize=10,
        family="sans-serif",
        horizontalalignment="center",
    )
    figure.text(
        0.948,
        0.105,
        f"{GPU_RANGE_PRESENTATION[range_id]['short_label']} VIEW / HOURLY",
        color=muted,
        fontsize=11,
        family="sans-serif",
        horizontalalignment="right",
    )

    rgba_buffer = io.BytesIO()
    canvas.print_png(rgba_buffer)
    rgba_buffer.seek(0)

    from PIL import Image

    rgb_buffer = io.BytesIO()
    with Image.open(rgba_buffer) as source:
        source.convert("RGB").save(
            rgb_buffer,
            format="PNG",
            optimize=True,
        )
    return rgb_buffer.getvalue()


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
        "revision": route.revision,
        "publication_id": route.publication_id,
        "route": route.as_dict(),
    }


def _publication_html(metadata: Mapping[str, Any]) -> str:
    title = escape(str(metadata["title"]))
    description = escape(str(metadata["description"]))
    page_url = escape(str(metadata["page_url"]), quote=True)
    image_url = escape(str(metadata["image_url"]), quote=True)
    live_url = escape(str(metadata["live_url"]), quote=True)
    data_url = escape(str(metadata["data_url"]), quote=True)
    image_alt = escape(str(metadata["image_alt"]), quote=True)
    observed_label = escape(str(metadata["observed_label"]))
    family_id = escape(str(metadata["family_id"]))
    range_label = escape(str(metadata["range_label"]))
    change_label = escape(str(metadata["change_label"]))
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
      <p>{family_id} / {range_label} / {change_label.lower()} / {observed_label.lower()}</p>
      <nav aria-label="Publication links">
        <a href="{live_url}">Open interactive card</a>
        <a href="{data_url}">Open data</a>
      </nav>
    </footer>
  </main>
</body>
</html>
"""


def _visible_gpu_series(
    cards: Mapping[str, Mapping[str, Any]],
    range_id: str,
) -> dict[str, list[dict[str, Any]]]:
    if range_id not in GPU_RANGES:
        raise ValueError(f"Unknown GPU publication range: {range_id}")
    parsed: dict[str, list[dict[str, Any]]] = {}
    for family in GPU_FAMILIES:
        card = cards.get(family) or {}
        rows = []
        for row in card.get("series") or []:
            if not isinstance(row, Mapping):
                continue
            observed_at = _parse_datetime(row.get("observed_at"))
            value = _finite_number(row.get("value"))
            if observed_at is None or value is None:
                continue
            lower = _finite_number(row.get("lower"))
            upper = _finite_number(row.get("upper"))
            rows.append(
                {
                    "date": observed_at,
                    "value": value,
                    "lower": value if lower is None else lower,
                    "upper": value if upper is None else upper,
                    "run_id": row.get("run_id"),
                }
            )
        rows.sort(key=lambda item: item["date"])
        parsed[family] = rows

    all_rows = [row for rows in parsed.values() for row in rows]
    duration = GPU_RANGES[range_id]
    if not duration or not all_rows:
        return parsed
    cutoff = max(row["date"] for row in all_rows) - duration
    return {
        family: [row for row in rows if row["date"] >= cutoff]
        for family, rows in parsed.items()
    }


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


def _latest_observed_at(rows: list[Mapping[str, Any]]) -> datetime | None:
    return rows[-1]["date"] if rows else None


def _range_change(
    rows: list[Mapping[str, Any]],
    range_id: str,
) -> dict[str, float | str | None]:
    if len(rows) < 2 or not rows[0]["value"]:
        return {
            "value": None,
            "label": "First retained observation",
            "direction": "unknown",
        }
    change = ((rows[-1]["value"] - rows[0]["value"]) / rows[0]["value"]) * 100
    rounded_change = round(change, 1)
    direction = "flat"
    direction_label = "Unchanged"
    if rounded_change > 0:
        direction = "up"
        direction_label = f"Up {abs(rounded_change):.1f}%"
    elif rounded_change < 0:
        direction = "down"
        direction_label = f"Down {abs(rounded_change):.1f}%"
    if range_id == "all":
        label = f"{direction_label} since {rows[0]['date'].strftime('%d %b %Y')}"
    else:
        label = f"{direction_label} over {GPU_RANGE_PRESENTATION[range_id]['label']}"
    return {
        "value": round(change, 6),
        "label": label,
        "direction": direction,
    }


def _format_observed(value: datetime | None) -> str:
    if value is None:
        return "Observation pending"
    return f"Observed {value.strftime('%d %b %Y, %H:%M UTC')}"


def _format_observed_date(value: datetime | None) -> str:
    if value is None:
        return "the latest retained observation"
    return value.strftime("%d %b %Y at %H:%M UTC")


def _format_usd(value: float) -> str:
    if value < 1:
        return f"${value:.3f}"
    if value < 10:
        return f"${value:.2f}"
    return f"${value:.1f}"


def _format_axis_usd(value: float) -> str:
    if value == 0:
        return "$0"
    if value < 1:
        return f"${value:.2f}"
    return f"${value:.1f}"


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _join(root: str, path: str) -> str:
    return "/".join([root.rstrip("/"), path.lstrip("/")])
