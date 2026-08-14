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
    from matplotlib.patches import FancyBboxPatch, Polygon

    rows = _prime_publication_series(card)
    family = str((card.get("data") or {}).get("family_id") or "GPU").upper()
    outside = "#ffffff"
    paper = "#f8f5eb"
    ink = "#142027"
    blue = "#7c5231"
    lower_band = "#b7d07b"
    middle_band = "#91aecb"
    upper_band = "#f3c888"

    figure = Figure(
        figsize=(IMAGE_WIDTH / 100, IMAGE_HEIGHT / 100),
        dpi=100,
        facecolor=outside,
    )
    canvas = FigureCanvasAgg(figure)
    price_font = FontProperties(fname=_GEIST_MEDIUM, size=64)
    family_font = FontProperties(fname=_GEIST_SEMIBOLD, size=24)
    figure.patches.extend(
        (
            FancyBboxPatch(
                (0.020, 0.038),
                0.960,
                0.924,
                boxstyle="round,pad=0,rounding_size=0.008",
                transform=figure.transFigure,
                facecolor=paper,
                edgecolor="#9cabb0",
                linewidth=0.9,
                zorder=-20,
            ),
        )
    )
    latest = rows[-1] if rows else None
    figure.text(
        0.060,
        0.885,
        family,
        color=ink,
        fontproperties=family_font,
    )
    figure.text(
        0.060,
        0.700,
        _format_usd(latest["price"]) if latest else "PENDING",
        color=ink,
        fontproperties=price_font,
        parse_math=False,
    )
    price_axes = figure.add_axes((0.020, 0.315, 0.960, 0.315), facecolor="none")
    offer_axes = figure.add_axes((0.020, 0.038, 0.960, 0.259), facecolor="none")
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
        smooth_dates, smooth_prices = _shape_preserving_curve(
            dates,
            display_prices,
        )
        duration = max((end - start).total_seconds(), 1)
        price_span = max(price_maximum - price_minimum, 1e-9)
        price_fill_points = [
            (0.020, 0.038),
            *(
                (
                    0.020
                    + ((date - start).total_seconds() / duration) * 0.960,
                    0.315
                    + ((price - price_minimum) / price_span) * 0.315,
                )
                for date, price in zip(smooth_dates, smooth_prices, strict=True)
            ),
            (0.980, 0.038),
        ]
        figure.patches.append(
            Polygon(
                price_fill_points,
                closed=True,
                transform=figure.transFigure,
                facecolor=blue,
                edgecolor="none",
                alpha=0.035,
                zorder=-10,
            )
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
            color=lower_band,
            alpha=0.78,
            linewidth=0,
        )
        offer_axes.fill_between(
            dates,
            lower,
            lower_middle,
            step="post",
            color=middle_band,
            alpha=0.78,
            linewidth=0,
        )
        offer_axes.fill_between(
            dates,
            lower_middle,
            totals,
            step="post",
            color=upper_band,
            alpha=0.78,
            linewidth=0,
        )
        offer_axes.step(
            dates,
            totals,
            where="post",
            color=blue,
            linewidth=1.2,
            alpha=0.46,
        )
    price_axes.set_axis_off()
    offer_axes.set_axis_off()
    return _publication_png(canvas)
