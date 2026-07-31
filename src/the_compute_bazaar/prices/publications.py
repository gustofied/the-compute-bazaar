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


PUBLICATION_SCHEMA_VERSION = "compute_bazaar_publication_v6"
PUBLICATION_RENDER_PROFILE = "social_png_rgb_1200x630_selected_series_v2"
DEFAULT_PUBLIC_DATA_BASE_URL = "https://bazaar.adamsioud.com"
DEFAULT_ARTICLE_URL = (
    "https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html"
)
GPU_FAMILIES = ("H100", "H200", "B200", "B300")
PRIME_OFFER_FAMILIES = ("H100", "H200")
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
RELATIVE_SERIES = ("gpu", "vm", "sandbox")
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
        "publication_type": "prime_visible_offer_market",
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


def publish_sandbox_market_publications(
    *,
    output_root: str,
    rates_card: dict[str, Any],
    workload_card: dict[str, Any],
    relative_card: dict[str, Any],
    public_base_url: str | None = None,
    article_url: str | None = None,
) -> dict[str, Any]:
    """Publish immutable preview wrappers for the sandbox and relative cards."""
    public_base = (
        public_base_url
        or os.getenv("COMPUTE_BAZAAR_PUBLIC_BASE_URL")
        or DEFAULT_PUBLIC_DATA_BASE_URL
    ).rstrip("/")
    live_article = (
        article_url or os.getenv("COMPUTE_BAZAAR_ARTICLE_URL") or DEFAULT_ARTICLE_URL
    )
    source_cards = {
        "rates": rates_card,
        "workload": workload_card,
        "relative": relative_card,
    }
    content_digest = _market_card_publication_digest(
        source_cards,
        public_base_url=public_base,
        article_url=live_article,
    )
    publication_rows: list[dict[str, Any]] = []

    rate_rows = _sandbox_rate_rows(rates_card)
    rate_observed_at = _latest_observed_at(rate_rows) or _parse_datetime(
        rates_card.get("as_of")
    )
    rate_link = _publish_market_card_state(
        output_root=output_root,
        public_base_url=public_base,
        card_id="sandbox-cost",
        subject_id="rates",
        view_id="hourly-rate",
        observed_at=rate_observed_at,
        content_digest=content_digest,
        live_url=_live_market_card_url(
            article_url=live_article,
            card_id="sandbox-cost",
            state={"sandbox": "rates"},
            anchor="sandbox-benchmark-card",
        ),
        data_url=f"{public_base}/sandbox/rates.json",
        image=render_sandbox_rate_publication(rates_card),
        metadata=_sandbox_rate_publication_metadata(
            card=rates_card,
            rows=rate_rows,
            observed_at=rate_observed_at,
        ),
    )
    rates_card["publication"] = _card_publication_contract(
        card_id="sandbox-cost",
        default_state="rates",
        states={"rates": rate_link},
    )
    publication_rows.append({"state_id": "rates", **rate_link})

    workload_states: dict[str, dict[str, Any]] = {}
    for metric in ("cost", "runtime"):
        observed_at = _workload_observed_at(workload_card)
        link = _publish_market_card_state(
            output_root=output_root,
            public_base_url=public_base,
            card_id="sandbox-cost",
            subject_id="workload",
            view_id=("estimated-cost" if metric == "cost" else "measured-runtime"),
            observed_at=observed_at,
            content_digest=content_digest,
            live_url=_live_market_card_url(
                article_url=live_article,
                card_id="sandbox-cost",
                state={"sandbox": "workload", "measure": metric},
                anchor="sandbox-benchmark-card",
            ),
            data_url=f"{public_base}/sandbox/workload.json",
            image=render_sandbox_workload_publication(
                workload_card,
                metric=metric,
            ),
            metadata=_sandbox_workload_publication_metadata(
                card=workload_card,
                metric=metric,
                observed_at=observed_at,
            ),
        )
        workload_states[metric] = link
        publication_rows.append({"state_id": metric, **link})
    workload_card["publication"] = _card_publication_contract(
        card_id="sandbox-cost",
        default_state="cost",
        states=workload_states,
    )

    relative_states: dict[str, dict[str, Any]] = {}
    relative_rows = _relative_price_rows(relative_card)
    for band in RELATIVE_SERIES:
        for range_id in GPU_RANGES:
            state_id = f"{band}:{range_id}"
            visible_rows = _visible_relative_rows(relative_rows, range_id)
            if not visible_rows:
                continue
            observed_at = _latest_observed_at(visible_rows) or _parse_datetime(
                relative_card.get("as_of")
            )
            link = _publish_market_card_state(
                output_root=output_root,
                public_base_url=public_base,
                card_id="relative-prices",
                subject_id=band,
                view_id=GPU_RANGE_PRESENTATION[range_id]["path"],
                observed_at=observed_at,
                content_digest=content_digest,
                live_url=_live_market_card_url(
                    article_url=live_article,
                    card_id="relative-prices",
                    state={
                        "relativeRange": range_id,
                        "relativeBand": band,
                    },
                    anchor="relative-market-card",
                ),
                data_url=f"{public_base}/sandbox/relative.json",
                image=render_relative_price_publication(
                    relative_card,
                    band=band,
                    range_id=range_id,
                ),
                metadata=_relative_price_publication_metadata(
                    card=relative_card,
                    rows=visible_rows,
                    band=band,
                    range_id=range_id,
                    observed_at=observed_at,
                ),
            )
            relative_states[state_id] = link
            publication_rows.append({"state_id": state_id, **link})
    relative_card["publication"] = _card_publication_contract(
        card_id="relative-prices",
        default_state="gpu:all",
        states=relative_states,
    )

    latest_observed_at = max(
        (
            observed_at
            for observed_at in (
                rate_observed_at,
                _workload_observed_at(workload_card),
                _latest_observed_at(relative_rows),
            )
            if observed_at is not None
        ),
        default=None,
    )
    revision = PublicationRoute.create(
        card_id="market-cards",
        subject_id="sandbox-and-relative",
        view_id="all-views",
        observed_at=latest_observed_at,
        content_digest=content_digest,
    ).revision
    manifest_ref = _join(
        output_root,
        "publications/market-cards/manifest.json",
    )
    manifest = {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "route_schema_version": PUBLICATION_ROUTE_SCHEMA_VERSION,
        "publication_type": "sandbox_and_relative_market_cards",
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
    """Render a legible social preview for one selected GPU benchmark."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import (
        AutoDateLocator,
        ConciseDateFormatter,
        HourLocator,
    )
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import MaxNLocator

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

    figure = Figure(
        figsize=(IMAGE_WIDTH / 100, IMAGE_HEIGHT / 100),
        dpi=100,
        facecolor=paper,
    )
    canvas = FigureCanvasAgg(figure)
    figure.patches.append(
        Rectangle(
            (0.024, 0.04),
            0.952,
            0.92,
            transform=figure.transFigure,
            fill=False,
            edgecolor=rule,
            linewidth=1.2,
        )
    )
    figure.text(
        0.052,
        0.91,
        "GPU PRICE INDEX",
        color=muted,
        fontsize=12,
        fontweight=700,
        family="sans-serif",
        linespacing=1,
    )
    observed_at = _latest_observed_at(selected_rows)
    figure.text(
        0.948,
        0.91,
        _format_observed(observed_at).upper(),
        color=muted,
        fontsize=10,
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
        fontsize=12,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.052,
        0.715,
        _format_usd(selected_latest["value"]) if selected_latest else "PENDING",
        color=ink,
        fontsize=50,
        family="serif",
        parse_math=False,
    )
    figure.text(
        0.225,
        0.725,
        "USD / GPU-HOUR",
        color=muted,
        fontsize=9,
        family="sans-serif",
    )
    figure.text(
        0.948,
        0.765,
        str(change["label"]).upper(),
        color=coral,
        fontsize=10,
        fontweight=700,
        family="sans-serif",
        horizontalalignment="right",
    )
    if selected_latest:
        figure.text(
            0.948,
            0.72,
            (
                f"QUOTED RANGE {_format_usd(selected_latest['lower'])}"
                f"–{_format_usd(selected_latest['upper'])}"
            ),
            color=muted,
            fontsize=9,
            family="sans-serif",
            horizontalalignment="right",
            parse_math=False,
        )

    axes = figure.add_axes((0.052, 0.165, 0.896, 0.44), facecolor=paper)
    axes.grid(axis="y", color=rule, alpha=0.28, linewidth=0.8)
    axes.set_axisbelow(True)
    if selected_rows:
        dates = [row["date"] for row in selected_rows]
        values = [row["value"] for row in selected_rows]
        lower_values = [row["lower"] for row in selected_rows]
        upper_values = [row["upper"] for row in selected_rows]
        minimum = min([*values, *lower_values])
        maximum = max([*values, *upper_values])
        center = selected_latest["value"] if selected_latest else maximum
        minimum_span = max(abs(center) * 0.12, 0.2)
        spread = max(maximum - minimum, minimum_span)
        axes.set_ylim(
            max(0, minimum - spread * 0.12),
            maximum + spread * 0.12,
        )
        axes.fill_between(
            dates,
            lower_values,
            upper_values,
            color=band_color,
            alpha=0.24,
            linewidth=0,
            zorder=1,
        )
        axes.plot(
            dates,
            values,
            color=selected_color,
            linewidth=3.6,
            alpha=1,
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=3,
        )
        axes.annotate(
            _format_usd(values[-1]),
            xy=(dates[-1], values[-1]),
            xytext=(-8, 10),
            textcoords="offset points",
            color=selected_color,
            fontsize=9,
            fontweight=700,
            family="sans-serif",
            horizontalalignment="right",
            verticalalignment="bottom",
            zorder=4,
            parse_math=False,
        )
        span_hours = max((dates[-1] - dates[0]).total_seconds() / 3600, 1)
        locator = (
            HourLocator(interval=max(1, math.ceil(span_hours / 5)))
            if span_hours <= 48
            else AutoDateLocator(minticks=4, maxticks=6)
        )
        axes.xaxis.set_major_locator(locator)
        axes.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        axes.xaxis.get_offset_text().set_visible(False)
        axes.yaxis.set_major_locator(MaxNLocator(nbins=4))
        axes.margins(x=0)
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
        0.09,
        f"{selected_family} · {GPU_RANGE_PRESENTATION[range_id]['label']}".upper(),
        color=selected_color,
        fontsize=10,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.5,
        0.09,
        "OBSERVED ADVERTISED PRICES",
        color=muted,
        fontsize=9,
        family="sans-serif",
        horizontalalignment="center",
    )
    coverage = cards[selected_family].get("coverage") or {}
    provider_count = int(coverage.get("provider_count") or 0)
    figure.text(
        0.948,
        0.09,
        (
            f"{provider_count} PROVIDERS · HOURLY"
            if provider_count
            else "HOURLY OBSERVATIONS"
        ),
        color=muted,
        fontsize=9,
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


def render_prime_offer_shelf_publication(
    *,
    card: Mapping[str, Any],
) -> bytes:
    """Render Prime price and visible-offer history on separate measures."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import (
        AutoDateLocator,
        ConciseDateFormatter,
        HourLocator,
    )
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import MaxNLocator

    rows = _prime_publication_series(card)
    family = str((card.get("data") or {}).get("family_id") or "GPU").upper()
    paper = "#f8f5eb"
    ink = "#142027"
    muted = "#5f6f76"
    price_color = "#315f82"
    offer_color = "#91aecb"
    offer_line = "#587383"
    coral = "#a96552"
    rule = "#a7b1b3"

    figure = Figure(
        figsize=(IMAGE_WIDTH / 100, IMAGE_HEIGHT / 100),
        dpi=100,
        facecolor=paper,
    )
    canvas = FigureCanvasAgg(figure)
    figure.patches.append(
        Rectangle(
            (0.024, 0.04),
            0.952,
            0.92,
            transform=figure.transFigure,
            fill=False,
            edgecolor=rule,
            linewidth=1.2,
        )
    )
    latest = rows[-1] if rows else None
    observed_at = latest["date"] if latest else _parse_datetime(card.get("as_of"))
    change = _series_change(rows)
    figure.text(
        0.052,
        0.91,
        "PRIME GPU MARKET",
        color=muted,
        fontsize=12,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.948,
        0.91,
        _format_observed(observed_at).upper(),
        color=muted,
        fontsize=10,
        family="sans-serif",
        horizontalalignment="right",
    )
    figure.text(
        0.052,
        0.825,
        family,
        color=price_color,
        fontsize=12,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.052,
        0.72,
        _format_usd(latest["price"]) if latest else "PENDING",
        color=ink,
        fontsize=48,
        family="serif",
        parse_math=False,
    )
    figure.text(
        0.225,
        0.73,
        "USD / GPU-HOUR",
        color=muted,
        fontsize=9,
        family="sans-serif",
    )
    figure.text(
        0.948,
        0.765,
        str(change["label"]).upper(),
        color=coral,
        fontsize=10,
        fontweight=700,
        family="sans-serif",
        horizontalalignment="right",
    )
    figure.text(
        0.948,
        0.72,
        (
            f"{latest['offers']} VISIBLE "
            f"{'OFFER' if latest and latest['offers'] == 1 else 'OFFERS'}"
            if latest
            else "VISIBLE OFFERS PENDING"
        ),
        color=muted,
        fontsize=9,
        family="sans-serif",
        horizontalalignment="right",
    )

    price_axes = figure.add_axes((0.052, 0.34, 0.896, 0.28), facecolor=paper)
    offer_axes = figure.add_axes((0.052, 0.16, 0.896, 0.105), facecolor=paper)
    for axes in (price_axes, offer_axes):
        axes.grid(axis="y", color=rule, alpha=0.25, linewidth=0.8)
        axes.set_axisbelow(True)
        axes.yaxis.tick_right()
        axes.tick_params(
            axis="both",
            colors=muted,
            labelsize=8,
            length=0,
            pad=7,
        )
        for spine in axes.spines.values():
            spine.set_visible(False)

    if rows:
        dates = [row["date"] for row in rows]
        prices = [row["price"] for row in rows]
        offers = [row["offers"] for row in rows]
        minimum, maximum = min(prices), max(prices)
        spread = max(maximum - minimum, abs(prices[-1]) * 0.12, 0.2)
        price_axes.set_ylim(max(0, minimum - spread * 0.14), maximum + spread * 0.14)
        price_axes.plot(
            dates,
            prices,
            color=price_color,
            linewidth=3.4,
            solid_capstyle="round",
            solid_joinstyle="round",
        )
        price_axes.annotate(
            _format_usd(prices[-1]),
            xy=(dates[-1], prices[-1]),
            xytext=(-8, 9),
            textcoords="offset points",
            color=price_color,
            fontsize=9,
            fontweight=700,
            family="sans-serif",
            horizontalalignment="right",
            verticalalignment="bottom",
            parse_math=False,
        )
        offer_axes.fill_between(
            dates,
            offers,
            step="post",
            color=offer_color,
            alpha=0.38,
            linewidth=0,
        )
        offer_axes.step(
            dates,
            offers,
            where="post",
            color=offer_line,
            linewidth=1.8,
        )
        offer_axes.set_ylim(0, max(max(offers) * 1.18, 1))
        offer_axes.yaxis.set_major_locator(MaxNLocator(nbins=3, integer=True))
        span_hours = max((dates[-1] - dates[0]).total_seconds() / 3600, 1)
        locator = (
            HourLocator(interval=max(1, math.ceil(span_hours / 5)))
            if span_hours <= 48
            else AutoDateLocator(minticks=4, maxticks=6)
        )
        offer_axes.xaxis.set_major_locator(locator)
        offer_axes.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        offer_axes.xaxis.get_offset_text().set_visible(False)
        price_axes.set_xlim(dates[0], dates[-1])
        offer_axes.set_xlim(dates[0], dates[-1])
        price_axes.set_xticks([])
        price_axes.yaxis.set_major_locator(MaxNLocator(nbins=4))
        price_axes.yaxis.set_major_formatter(
            lambda value, _position: _format_axis_usd(value)
        )
    else:
        price_axes.text(
            0.5,
            0.5,
            "HISTORY IS STILL BEING COLLECTED",
            transform=price_axes.transAxes,
            color=muted,
            fontsize=14,
            horizontalalignment="center",
            verticalalignment="center",
        )
        price_axes.set_xticks([])
        offer_axes.set_xticks([])

    figure.text(
        0.052,
        0.285,
        "MARKET PRICE",
        color=muted,
        fontsize=8,
        family="sans-serif",
    )
    figure.text(
        0.052,
        0.115,
        "VISIBLE OFFERS",
        color=muted,
        fontsize=8,
        family="sans-serif",
    )
    figure.text(
        0.5,
        0.09,
        "OBSERVED PUBLIC PRICE AND AVAILABILITY",
        color=muted,
        fontsize=9,
        family="sans-serif",
        horizontalalignment="center",
    )
    figure.text(
        0.948,
        0.09,
        f"{len(rows)} HOURLY OBSERVATIONS",
        color=muted,
        fontsize=9,
        family="sans-serif",
        horizontalalignment="right",
    )
    return _publication_png(canvas)


def render_sandbox_rate_publication(card: Mapping[str, Any]) -> bytes:
    """Render the retained fixed-cohort sandbox rate history."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle

    rows = _sandbox_rate_rows(card)
    paper = "#f8f5eb"
    ink = "#142027"
    muted = "#5f6f76"
    line_color = "#526c28"
    band_color = "#b7d07b"
    rule = "#a7b1b3"
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
    latest = rows[-1] if rows else None
    figure.text(
        0.052,
        0.915,
        "PUBLIC HOURLY SANDBOX RATE",
        color=muted,
        fontsize=13,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.948,
        0.915,
        _format_effective(latest["date"] if latest else None).upper(),
        color=muted,
        fontsize=11,
        family="sans-serif",
        horizontalalignment="right",
    )
    figure.text(
        0.052,
        0.825,
        "FIXED COHORT",
        color=line_color,
        fontsize=11,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.052,
        0.748,
        _format_usd(latest["value"]) if latest else "PENDING",
        color=ink,
        fontsize=36,
        family="serif",
    )
    figure.text(
        0.178,
        0.755,
        "USD / HOUR",
        color=muted,
        fontsize=8,
        family="sans-serif",
    )
    figure.text(
        0.948,
        0.755,
        "4 PROCESSORS / 8 GIB MEMORY",
        color=line_color,
        fontsize=9,
        fontweight=700,
        family="sans-serif",
        horizontalalignment="right",
    )

    axes = figure.add_axes((0.052, 0.19, 0.896, 0.47), facecolor=paper)
    axes.grid(axis="y", color=rule, alpha=0.28, linewidth=0.8)
    axes.set_axisbelow(True)
    if rows:
        dates = [row["date"] for row in rows]
        values = [row["value"] for row in rows]
        lower = [row["lower"] for row in rows]
        upper = [row["upper"] for row in rows]
        minimum = min(lower)
        maximum = max(upper)
        spread = max(maximum - minimum, maximum * 0.08, 0.001)
        axes.set_ylim(max(0, minimum - spread * 0.22), maximum + spread * 0.22)
        axes.fill_between(
            dates,
            lower,
            upper,
            step="post",
            color=band_color,
            alpha=0.28,
            linewidth=0,
        )
        axes.step(
            dates,
            values,
            where="post",
            color=line_color,
            linewidth=3.2,
        )
        locator = AutoDateLocator(minticks=4, maxticks=6)
        axes.xaxis.set_major_locator(locator)
        axes.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        axes.xaxis.get_offset_text().set_visible(False)
    else:
        axes.text(
            0.5,
            0.5,
            "RATE HISTORY IS STILL BEING COLLECTED",
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
        "SANDBOX",
        color=line_color,
        fontsize=11,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.5,
        0.105,
        "RETAINED PUBLIC RATE CARDS",
        color=muted,
        fontsize=10,
        family="sans-serif",
        horizontalalignment="center",
    )
    figure.text(
        0.948,
        0.105,
        "FIXED MEMBERSHIP / STEP SERIES",
        color=muted,
        fontsize=11,
        family="sans-serif",
        horizontalalignment="right",
    )
    return _publication_png(canvas)


def render_sandbox_workload_publication(
    card: Mapping[str, Any],
    *,
    metric: str,
) -> bytes:
    """Render one comparable software job across the retained services."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle

    if metric not in {"cost", "runtime"}:
        raise ValueError(f"Unknown sandbox workload metric: {metric}")
    workload = (card.get("data") or {}).get("workload") or {}
    summaries = [
        dict(row)
        for row in workload.get("service_summary") or []
        if isinstance(row, Mapping)
    ]
    fields = {
        "cost": (
            "median_estimated_cost_usd",
            "p25_estimated_cost_usd",
            "p75_estimated_cost_usd",
        ),
        "runtime": (
            "median_runtime_seconds",
            "p25_runtime_seconds",
            "p75_runtime_seconds",
        ),
    }[metric]
    rows: list[dict[str, Any]] = []
    for row in summaries:
        median = _finite_number(row.get(fields[0]))
        if median is None:
            continue
        lower = _finite_number(row.get(fields[1]))
        upper = _finite_number(row.get(fields[2]))
        rows.append(
            {
                "label": str(
                    row.get("service_label")
                    or row.get("series_label")
                    or row.get("series_id")
                    or "Service"
                ),
                "median": median,
                "lower": median if lower is None else lower,
                "upper": median if upper is None else upper,
            }
        )
    rows.sort(key=lambda row: row["median"])
    paper = "#f8f5eb"
    ink = "#142027"
    muted = "#5f6f76"
    accent = "#855e27"
    band = "#e3c888"
    rule = "#a7b1b3"
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
    headline = card.get("headline") or {}
    headline_value = _finite_number(
        headline.get(
            "median_estimated_cost_usd"
            if metric == "cost"
            else "median_runtime_seconds"
        )
    )
    observed_at = _workload_observed_at(card)
    figure.text(
        0.052,
        0.915,
        "SAME MEASURED SOFTWARE JOB",
        color=muted,
        fontsize=13,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.948,
        0.915,
        _format_observed(observed_at).upper(),
        color=muted,
        fontsize=11,
        family="sans-serif",
        horizontalalignment="right",
    )
    figure.text(
        0.052,
        0.825,
        "ESTIMATED COST" if metric == "cost" else "MEASURED RUNTIME",
        color=accent,
        fontsize=11,
        fontweight=700,
        family="sans-serif",
    )
    value_label = (
        _format_cents(headline_value)
        if metric == "cost"
        else _format_seconds(headline_value)
    )
    figure.text(
        0.052,
        0.748,
        value_label,
        color=ink,
        fontsize=36,
        family="serif",
    )
    figure.text(
        0.948,
        0.755,
        f"{len(rows)} COMPARABLE SERVICES",
        color=accent,
        fontsize=9,
        fontweight=700,
        family="sans-serif",
        horizontalalignment="right",
    )
    axes = figure.add_axes((0.18, 0.19, 0.768, 0.47), facecolor=paper)
    if rows:
        maximum = max(row["upper"] for row in rows)
        axes.set_xlim(0, maximum * 1.12 if maximum else 1)
        positions = list(range(len(rows)))
        for position, row in zip(positions, rows, strict=True):
            axes.plot(
                [row["lower"], row["upper"]],
                [position, position],
                color=band,
                linewidth=7,
                solid_capstyle="round",
            )
            axes.scatter(
                [row["median"]],
                [position],
                s=64,
                facecolor=accent,
                edgecolor=paper,
                linewidth=1.5,
                zorder=3,
            )
        axes.set_yticks(positions, [row["label"] for row in rows])
        axes.set_ylim(-0.7, len(rows) - 0.3)
        axes.grid(axis="x", color=rule, alpha=0.28, linewidth=0.8)
        if metric == "cost":
            axes.xaxis.set_major_formatter(
                lambda value, _position: f"{value * 100:.1f}c"
            )
        else:
            axes.xaxis.set_major_formatter(
                lambda value, _position: _format_axis_seconds(value)
            )
    else:
        axes.text(
            0.5,
            0.5,
            "COMPARABLE RUNS ARE STILL BEING COLLECTED",
            transform=axes.transAxes,
            color=muted,
            fontsize=14,
            horizontalalignment="center",
            verticalalignment="center",
        )
        axes.set_xlim(0, 1)
        axes.set_yticks([])
    axes.tick_params(
        axis="both",
        colors=muted,
        labelsize=8,
        length=0,
        pad=7,
    )
    for spine in axes.spines.values():
        spine.set_visible(False)
    figure.text(
        0.052,
        0.105,
        "STARSLING HPC SANDBOX BENCHMARK",
        color=accent,
        fontsize=11,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.948,
        0.105,
        (
            "PROCESSOR AND MEMORY ESTIMATE"
            if metric == "cost"
            else "COMPLETE ALIGNED RUNS"
        ),
        color=muted,
        fontsize=11,
        family="sans-serif",
        horizontalalignment="right",
    )
    return _publication_png(canvas)


def render_relative_price_publication(
    card: Mapping[str, Any],
    *,
    band: str,
    range_id: str,
) -> bytes:
    """Render H100, VM, and sandbox rates from a common starting point."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle

    if band not in RELATIVE_SERIES:
        raise ValueError(f"Unknown relative price band: {band}")
    if range_id not in GPU_RANGES:
        raise ValueError(f"Unknown relative price range: {range_id}")
    rows = _visible_relative_rows(_relative_price_rows(card), range_id)
    paper = "#f8f5eb"
    ink = "#142027"
    muted = "#5f6f76"
    rule = "#a7b1b3"
    colors = {
        "gpu": "#315f82",
        "vm": "#526c28",
        "sandbox": "#855e27",
    }
    labels = {"gpu": "H100", "vm": "VM", "sandbox": "SANDBOX"}
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
    latest = rows[-1] if rows else None
    change = _relative_change(rows, band, range_id)
    figure.text(
        0.052,
        0.915,
        "RELATIVE ADVERTISED RATES",
        color=muted,
        fontsize=13,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.948,
        0.915,
        _format_observed(latest["date"] if latest else None).upper(),
        color=muted,
        fontsize=11,
        family="sans-serif",
        horizontalalignment="right",
    )
    figure.text(
        0.052,
        0.825,
        labels[band],
        color=colors[band],
        fontsize=11,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.052,
        0.748,
        f"{latest[band]:.1f}" if latest else "PENDING",
        color=ink,
        fontsize=36,
        family="serif",
    )
    figure.text(
        0.168,
        0.755,
        "100 AT COMMON START",
        color=muted,
        fontsize=8,
        family="sans-serif",
    )
    figure.text(
        0.948,
        0.755,
        str(change["label"]).upper(),
        color=colors[band],
        fontsize=9,
        fontweight=700,
        family="sans-serif",
        horizontalalignment="right",
    )
    axes = figure.add_axes((0.052, 0.19, 0.896, 0.47), facecolor=paper)
    axes.grid(axis="y", color=rule, alpha=0.28, linewidth=0.8)
    axes.set_axisbelow(True)
    if rows:
        lower_field = f"{band}_lower"
        upper_field = f"{band}_upper"
        all_values = [
            row[field]
            for row in rows
            for field in (
                "gpu",
                "vm",
                "sandbox",
                lower_field,
                upper_field,
            )
        ]
        minimum = min(all_values)
        maximum = max(all_values)
        spread = max(maximum - minimum, 2)
        axes.set_ylim(minimum - spread * 0.14, maximum + spread * 0.14)
        dates = [row["date"] for row in rows]
        axes.fill_between(
            dates,
            [row[lower_field] for row in rows],
            [row[upper_field] for row in rows],
            color=colors[band],
            alpha=0.12,
            linewidth=0,
        )
        axes.axhline(100, color=rule, linewidth=1, alpha=0.65)
        for series_id in RELATIVE_SERIES:
            axes.plot(
                dates,
                [row[series_id] for row in rows],
                color=colors[series_id],
                linewidth=3 if series_id == band else 1.8,
                alpha=1 if series_id == band else 0.48,
                solid_capstyle="round",
                solid_joinstyle="round",
            )
        locator = AutoDateLocator(minticks=4, maxticks=6)
        axes.xaxis.set_major_locator(locator)
        axes.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        axes.xaxis.get_offset_text().set_visible(False)
    else:
        axes.text(
            0.5,
            0.5,
            "ALIGNED HISTORY IS STILL BEING COLLECTED",
            transform=axes.transAxes,
            color=muted,
            fontsize=14,
            horizontalalignment="center",
            verticalalignment="center",
        )
        axes.set_ylim(99, 101)
        axes.set_xticks([])
    axes.yaxis.tick_right()
    axes.tick_params(
        axis="both",
        colors=muted,
        labelsize=8,
        length=0,
        pad=7,
    )
    for spine in axes.spines.values():
        spine.set_visible(False)
    figure.text(
        0.052,
        0.105,
        labels[band],
        color=colors[band],
        fontsize=11,
        fontweight=700,
        family="sans-serif",
    )
    figure.text(
        0.5,
        0.105,
        "H100 / VM / MANAGED SANDBOX",
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
    return _publication_png(canvas)


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
        f"{family} / {value} per GPU-hour / {offers} visible "
        f"{'offer' if offers == 1 else 'offers'} / observed "
        f"{observed_label.replace(' at ', ', ')}"
    )
    return {
        "title": (
            f"Prime {family} GPU market | {value}/GPU-hour | "
            f"{offers} visible {'offer' if offers == 1 else 'offers'}"
        ),
        "description": (
            f"Prime {family} observed public market price at {value} per "
            f"GPU-hour with {offers} visible "
            f"{'offer' if offers == 1 else 'offers'}. "
            f"{change['label']}. Observed {observed_label}."
        ),
        "image_alt": (
            f"Prime {family} market price at {value} per GPU-hour with "
            f"{offers} visible {'offer' if offers == 1 else 'offers'}"
        ),
        "subject_label": f"Prime {family} GPU market",
        "view_label": "Price and visible availability",
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


def _sandbox_rate_publication_metadata(
    *,
    card: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
    observed_at: datetime | None,
) -> dict[str, Any]:
    latest = rows[-1] if rows else None
    value = _format_usd(latest["value"]) if latest else "pending"
    effective_label = _format_effective_date(observed_at)
    display_line = (
        f"Sandbox / public hourly rate / {value} per hour / effective {effective_label}"
    )
    return {
        "title": f"Sandbox public hourly rate | {value}/hour",
        "description": (
            "Fixed-cohort public sandbox rate for four processors and "
            f"8 GiB of memory, at {value} per hour. Effective {effective_label}."
        ),
        "image_alt": (
            f"Sandbox public hourly rate at {value} for four processors "
            "and 8 GiB of memory"
        ),
        "subject_label": "Managed sandbox",
        "view_label": "Public hourly rate",
        "value": value,
        "observed_at": observed_at.isoformat() if observed_at else "",
        "observed_label": _format_effective(observed_at),
        "footer_label": display_line,
        "display_line": display_line,
        "change_pct": None,
        "change_label": None,
        "change_direction": "unknown",
    }


def _sandbox_workload_publication_metadata(
    *,
    card: Mapping[str, Any],
    metric: str,
    observed_at: datetime | None,
) -> dict[str, Any]:
    headline = card.get("headline") or {}
    if metric == "cost":
        raw_value = _finite_number(
            headline.get("median_estimated_cost_usd")
            or headline.get("median_service_cost")
        )
        value = _format_cents(raw_value)
        subject_label = "Sandbox workload cost"
        view_label = "Estimated cost"
        measure = "estimated processor-and-memory cost"
    else:
        raw_value = _finite_number(headline.get("median_runtime_seconds"))
        value = _format_seconds(raw_value)
        subject_label = "Sandbox workload runtime"
        view_label = "Measured runtime"
        measure = "measured runtime"
    observed_label = _format_observed_date(observed_at)
    display_line = (
        f"Sandbox / {view_label.lower()} / {value} median / "
        f"observed {observed_label.replace(' at ', ', ')}"
    )
    return {
        "title": f"Same measured software job | {view_label} | {value}",
        "description": (
            f"Median {measure} for the same aligned software job across "
            f"the retained comparable sandbox services. Observed {observed_label}."
        ),
        "image_alt": (f"Same measured software job with median {measure} of {value}"),
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


def _relative_price_publication_metadata(
    *,
    card: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
    band: str,
    range_id: str,
    observed_at: datetime | None,
) -> dict[str, Any]:
    labels = {"gpu": "H100", "vm": "VM", "sandbox": "Sandbox"}
    latest = rows[-1] if rows else None
    value = f"{latest[band]:.1f}" if latest else "pending"
    change = _relative_change(rows, band, range_id)
    range_label = GPU_RANGE_PRESENTATION[range_id]["label"]
    observed_label = _format_observed_date(observed_at).replace(" at ", ", ")
    display_line = (
        f"{labels[band]} / {range_label} / {str(change['label']).lower()} / "
        f"observed {observed_label}"
    )
    return {
        "title": (
            f"{labels[band]} relative advertised rate | {value} | {change['label']}"
        ),
        "description": (
            f"{labels[band]} advertised-rate movement from the common starting "
            f"observation, at {value}. {change['label']}. "
            f"Observed {observed_label}."
        ),
        "image_alt": (
            f"{labels[band]} relative advertised rate at {value}, "
            f"{str(change['label']).lower()}"
        ),
        "subject_label": labels[band],
        "view_label": range_label,
        "value": value,
        "observed_at": observed_at.isoformat() if observed_at else "",
        "observed_label": _format_observed(observed_at),
        "footer_label": display_line,
        "display_line": display_line,
        "change_pct": change["value"],
        "change_label": change["label"],
        "change_direction": change["direction"],
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


def _prime_publication_series(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in card.get("series") or []:
        if not isinstance(row, Mapping):
            continue
        observed_at = _parse_datetime(row.get("observed_at"))
        price = _finite_number(row.get("value"))
        if observed_at is None or price is None:
            continue
        rows.append(
            {
                "date": observed_at,
                "price": price,
                "offers": max(
                    0,
                    int(row.get("configuration_count") or row.get("offer_count") or 0),
                ),
            }
        )
    rows.sort(key=lambda row: row["date"])
    return rows


def _series_change(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if len(rows) < 2:
        return {
            "value": None,
            "label": "Tracking has just begun",
            "direction": "unknown",
        }
    first = _finite_number(rows[0].get("price"))
    latest = _finite_number(rows[-1].get("price"))
    if first in {None, 0} or latest is None:
        return {
            "value": None,
            "label": "Change unavailable",
            "direction": "unknown",
        }
    value = ((latest - first) / first) * 100
    if abs(value) < 0.05:
        return {
            "value": 0.0,
            "label": "Unchanged since tracking began",
            "direction": "flat",
        }
    direction = "up" if value > 0 else "down"
    return {
        "value": round(value, 6),
        "label": f"{direction.title()} {abs(value):.1f}% since tracking began",
        "direction": direction,
    }


def _sandbox_rate_rows(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    series = card.get("series") or {}
    raw_rows = series.get("sandbox") if isinstance(series, Mapping) else []
    rows: list[dict[str, Any]] = []
    for row in raw_rows or []:
        if not isinstance(row, Mapping):
            continue
        observed_at = _parse_datetime(
            row.get("observed_at") or row.get("observed_date")
        )
        value = _finite_number(row.get("median_usd_per_hour"))
        if observed_at is None or value is None:
            continue
        lower = _finite_number(row.get("p25_usd_per_hour"))
        upper = _finite_number(row.get("p75_usd_per_hour"))
        rows.append(
            {
                "date": observed_at,
                "value": value,
                "lower": value if lower is None else lower,
                "upper": value if upper is None else upper,
            }
        )
    rows.sort(key=lambda row: row["date"])
    return rows


def _relative_price_rows(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    field_names = {
        "gpu": (
            "gpu_base_100",
            "gpu_p25_base_100",
            "gpu_p75_base_100",
        ),
        "vm": (
            "vm_base_100",
            "vm_p25_base_100",
            "vm_p75_base_100",
        ),
        "sandbox": (
            "sandbox_base_100",
            "sandbox_p25_base_100",
            "sandbox_p75_base_100",
        ),
    }
    for row in card.get("series") or []:
        if not isinstance(row, Mapping):
            continue
        observed_at = _parse_datetime(row.get("observed_at"))
        if observed_at is None:
            continue
        parsed_row: dict[str, Any] = {
            "date": observed_at,
            "common_start_at": row.get("common_start_at"),
        }
        valid = True
        for series_id, fields in field_names.items():
            value = _finite_number(row.get(fields[0]))
            lower = _finite_number(row.get(fields[1]))
            upper = _finite_number(row.get(fields[2]))
            if value is None or lower is None or upper is None:
                valid = False
                break
            parsed_row[series_id] = value
            parsed_row[f"{series_id}_lower"] = lower
            parsed_row[f"{series_id}_upper"] = upper
        if valid:
            rows.append(parsed_row)
    rows.sort(key=lambda row: row["date"])
    return rows


def _visible_relative_rows(
    rows: list[Mapping[str, Any]],
    range_id: str,
) -> list[Mapping[str, Any]]:
    if range_id not in GPU_RANGES:
        raise ValueError(f"Unknown relative price range: {range_id}")
    duration = GPU_RANGES[range_id]
    if duration is None or not rows:
        return list(rows)
    cutoff = rows[-1]["date"] - duration
    return [row for row in rows if row["date"] >= cutoff]


def _workload_observed_at(card: Mapping[str, Any]) -> datetime | None:
    headline = card.get("headline") or {}
    return _parse_datetime(headline.get("observed_at")) or _parse_datetime(
        card.get("as_of")
    )


def _relative_change(
    rows: list[Mapping[str, Any]],
    band: str,
    range_id: str,
) -> dict[str, float | str | None]:
    if len(rows) < 2 or not rows[0].get(band):
        return {
            "value": None,
            "label": "First retained observation",
            "direction": "unknown",
        }
    change = (
        (float(rows[-1][band]) - float(rows[0][band])) / float(rows[0][band])
    ) * 100
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


def _publication_png(canvas: Any) -> bytes:
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


def _format_effective(value: datetime | None) -> str:
    if value is None:
        return "Effective date pending"
    return f"Effective {value.strftime('%d %b %Y')}"


def _format_effective_date(value: datetime | None) -> str:
    if value is None:
        return "the latest retained effective date"
    return value.strftime("%d %b %Y")


def _format_usd(value: float) -> str:
    if value < 1:
        return f"${value:.3f}"
    if value < 10:
        return f"${value:.2f}"
    return f"${value:.1f}"


def _format_cents(value: float | None) -> str:
    if value is None:
        return "pending"
    return f"{value * 100:.2f}c"


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "pending"
    if value >= 120:
        return f"{value / 60:.1f} min"
    return f"{value:.0f} sec"


def _format_axis_usd(value: float) -> str:
    if value == 0:
        return "$0"
    if value < 1:
        return f"${value:.2f}"
    return f"${value:.1f}"


def _format_axis_seconds(value: float) -> str:
    if value >= 120:
        return f"{value / 60:.0f}m"
    return f"{value:.0f}s"


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
