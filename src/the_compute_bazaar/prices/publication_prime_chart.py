"""Render immutable Prime offer-market publication images."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .publication_chart_common import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    _format_axis_usd,
    _format_observed,
    _format_usd,
    _parse_datetime,
    _prime_offer_band_series,
    _prime_publication_series,
    _publication_png,
    _shape_preserving_curve,
    _series_change,
)


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
    green = "#526c28"
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
            f"{latest['offers']} "
            f"{'OFFER' if latest and latest['offers'] == 1 else 'OFFERS'}"
            if latest
            else "OFFERS PENDING"
        ),
        color=muted,
        fontsize=9,
        family="sans-serif",
        horizontalalignment="right",
    )

    price_axes = figure.add_axes((0.052, 0.345, 0.896, 0.275), facecolor=paper)
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
        benchmarks = [
            row["benchmark"] for row in rows if row.get("benchmark") is not None
        ]
        price_domain = [*prices, *benchmarks]
        minimum, maximum = min(price_domain), max(price_domain)
        spread = max(maximum - minimum, abs(prices[-1]) * 0.12, 0.2)
        price_axes.set_ylim(max(0, minimum - spread * 0.14), maximum + spread * 0.14)
        benchmark_dates = [
            row["date"] for row in rows if row.get("benchmark") is not None
        ]
        if benchmark_dates:
            smooth_benchmark_dates, smooth_benchmarks = _shape_preserving_curve(
                benchmark_dates,
                benchmarks,
            )
            price_axes.plot(
                smooth_benchmark_dates,
                smooth_benchmarks,
                color=green,
                linewidth=1.6,
                linestyle=(0, (3, 4)),
                alpha=0.72,
                solid_capstyle="round",
                solid_joinstyle="round",
            )
        smooth_dates, smooth_prices = _shape_preserving_curve(dates, prices)
        price_axes.plot(
            smooth_dates,
            smooth_prices,
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
        offer_bands = _prime_offer_band_series(card, rows)
        lower = [row["lower"] for row in offer_bands]
        lower_middle = [row["lower"] + row["middle"] for row in offer_bands]
        totals = [row["total"] for row in offer_bands]
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
            color=offer_color,
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
            color=offer_line,
            linewidth=1.2,
            alpha=0.78,
        )
        offer_axes.set_ylim(0, max(max(totals) * 1.18, 1))
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
        "PRICE",
        color=muted,
        fontsize=8,
        family="sans-serif",
    )
    figure.text(
        0.052,
        0.115,
        "OFFERS",
        color=muted,
        fontsize=8,
        family="sans-serif",
    )
    figure.text(
        0.5,
        0.09,
        "PRICE AND OFFERS",
        color=muted,
        fontsize=9,
        family="sans-serif",
        horizontalalignment="center",
    )
    figure.text(
        0.948,
        0.09,
        "HOURLY",
        color=muted,
        fontsize=9,
        family="sans-serif",
        horizontalalignment="right",
    )
    return _publication_png(canvas)
