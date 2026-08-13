"""Render immutable Prime offer-market publication images."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from .publication_chart_common import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    _format_usd,
    _prime_offer_band_series,
    _prime_publication_series,
    _publication_png,
    _shape_preserving_curve,
    _smooth_observation_values,
)

_FONT_ROOT = Path(__file__).with_name("assets") / "fonts"
_GEIST_MEDIUM = _FONT_ROOT / "Geist-Medium.ttf"
_GEIST_SEMIBOLD = _FONT_ROOT / "Geist-SemiBold.ttf"


def render_prime_offer_shelf_publication(
    *,
    card: Mapping[str, Any],
) -> bytes:
    """Render Prime price above its changing public offer shelf."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties
    from matplotlib.lines import Line2D
    from matplotlib.patches import FancyBboxPatch

    rows = _prime_publication_series(card)
    family = str((card.get("data") or {}).get("family_id") or "GPU").upper()
    outside = "#ffffff"
    sleeve = "#dbe5e9"
    paper = "#ffffff"
    ink = "#142027"
    blue = "#315f82"
    azure = "#91aecb"
    green = "#526c28"
    coral = "#a96552"
    rule = "#a7b1b3"

    figure = Figure(
        figsize=(IMAGE_WIDTH / 100, IMAGE_HEIGHT / 100),
        dpi=100,
        facecolor=outside,
    )
    canvas = FigureCanvasAgg(figure)
    price_font = FontProperties(fname=_GEIST_MEDIUM, size=64)
    family_font = FontProperties(fname=_GEIST_SEMIBOLD, size=24)
    availability_font = FontProperties(fname=_GEIST_MEDIUM, size=16)
    label_font = FontProperties(fname=_GEIST_SEMIBOLD, size=12)
    figure.patches.extend(
        (
            FancyBboxPatch(
                (0.020, 0.038),
                0.960,
                0.924,
                boxstyle="round,pad=0,rounding_size=0.008",
                transform=figure.transFigure,
                facecolor=sleeve,
                edgecolor="#9cabb0",
                linewidth=0.9,
                zorder=-20,
            ),
            FancyBboxPatch(
                (0.030, 0.057),
                0.940,
                0.886,
                boxstyle="round,pad=0,rounding_size=0.006",
                transform=figure.transFigure,
                facecolor=paper,
                edgecolor="#c3ccce",
                linewidth=0.75,
                zorder=-10,
            ),
        )
    )
    latest = rows[-1] if rows else None
    available = int(latest["offers"]) if latest else 0
    figure.text(
        0.060,
        0.918,
        "PRIME AVAILABILITY",
        color=blue,
        fontproperties=label_font,
    )
    figure.text(
        0.060,
        0.835,
        family,
        color=ink,
        fontproperties=family_font,
    )
    figure.text(
        0.060,
        0.665,
        _format_usd(latest["price"]) if latest else "PENDING",
        color=ink,
        fontproperties=price_font,
        parse_math=False,
    )
    figure.text(
        0.940,
        0.835,
        f"{available} AVAILABLE",
        color=ink,
        fontproperties=availability_font,
        horizontalalignment="right",
    )
    figure.add_artist(
        Line2D(
            (0.030, 0.970),
            (0.315, 0.315),
            transform=figure.transFigure,
            color=rule,
            alpha=0.44,
            linewidth=1,
            zorder=0,
        )
    )

    price_axes = figure.add_axes((0.030, 0.345, 0.940, 0.255), facecolor=paper)
    offer_axes = figure.add_axes((0.030, 0.095, 0.940, 0.185), facecolor=paper)
    if rows:
        dates = [row["date"] for row in rows]
        prices = [row["price"] for row in rows]
        display_prices = _smooth_observation_values(prices)
        start, end = dates[0], dates[-1]
        if start == end:
            start -= timedelta(minutes=30)
            end += timedelta(minutes=30)

        minimum = min(prices)
        maximum = max(prices)
        spread = max(maximum - minimum, maximum * 0.025, 0.12)
        price_minimum = max(0, minimum - spread * 0.20)
        price_maximum = maximum + spread * 0.20
        price_axes.set_xlim(start, end)
        price_axes.set_ylim(price_minimum, price_maximum)
        for tick in (
            price_minimum,
            (price_minimum + price_maximum) / 2,
            price_maximum,
        ):
            price_axes.axhline(
                tick,
                color=rule,
                alpha=0.42,
                linewidth=1,
                zorder=0,
            )

        smooth_dates, smooth_prices = _shape_preserving_curve(
            dates,
            display_prices,
        )
        price_axes.fill_between(
            smooth_dates,
            smooth_prices,
            price_minimum,
            color=blue,
            alpha=0.055,
            linewidth=0,
            zorder=1,
        )
        price_axes.plot(
            smooth_dates,
            smooth_prices,
            color=blue,
            linewidth=3.5,
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=2,
        )
        price_axes.plot(
            dates[-1],
            prices[-1],
            marker="o",
            markersize=7.5,
            markerfacecolor=paper,
            markeredgecolor=blue,
            markeredgewidth=2.2,
            linestyle="none",
            clip_on=False,
            zorder=3,
        )

        offer_bands = _prime_offer_band_series(card, rows)
        lower = [row["lower"] for row in offer_bands]
        lower_middle = [row["lower"] + row["middle"] for row in offer_bands]
        totals = [row["total"] for row in offer_bands]
        offer_axes.set_xlim(start, end)
        offer_axes.set_ylim(0, max(max(totals) * 1.10, 1))
        offer_axes.fill_between(
            dates,
            0,
            lower,
            step="post",
            color=green,
            alpha=0.58,
            linewidth=0,
        )
        offer_axes.fill_between(
            dates,
            lower,
            lower_middle,
            step="post",
            color=azure,
            alpha=0.58,
            linewidth=0,
        )
        offer_axes.fill_between(
            dates,
            lower_middle,
            totals,
            step="post",
            color=coral,
            alpha=0.58,
            linewidth=0,
        )
        offer_axes.step(
            dates,
            totals,
            where="post",
            color=blue,
            linewidth=1.4,
            alpha=0.68,
        )
        for tick in (0, max(max(totals), 1)):
            offer_axes.axhline(
                tick,
                color=rule,
                alpha=0.30,
                linewidth=1,
                zorder=0,
            )

    price_axes.set_axis_off()
    offer_axes.set_axis_off()
    return _publication_png(canvas)
