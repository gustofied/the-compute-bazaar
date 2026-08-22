"""Render immutable GPU benchmark publication images."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from .publication_chart_common import (
    GPU_RANGES,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    _format_usd,
    _publication_png,
    _shape_preserving_curve,
    _visible_gpu_series,
)

_FONT_ROOT = Path(__file__).with_name("assets") / "fonts"
_GEIST_MEDIUM = _FONT_ROOT / "Geist-Medium.ttf"
_GEIST_SEMIBOLD = _FONT_ROOT / "Geist-SemiBold.ttf"
_RENDER_DPI = 200
_OUTPUT_DPI = 100


def render_gpu_benchmark_publication(
    *,
    cards: Mapping[str, Mapping[str, Any]],
    selected_family: str,
    range_id: str,
) -> bytes:
    """Render a minimal GPU price image for small social-link previews."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import FancyBboxPatch, Polygon

    if selected_family not in cards:
        raise ValueError(f"Unknown GPU publication family: {selected_family}")
    if range_id not in GPU_RANGES:
        raise ValueError(f"Unknown GPU publication range: {range_id}")

    selected_rows = _visible_gpu_series(cards, range_id).get(selected_family, [])
    outside = "#dbe5e9"
    paper = "#ffffff"
    blue = "#315f82"

    figure = Figure(
        figsize=(IMAGE_WIDTH / _OUTPUT_DPI, IMAGE_HEIGHT / _OUTPUT_DPI),
        dpi=_RENDER_DPI,
        facecolor=outside,
    )
    canvas = FigureCanvasAgg(figure)
    # Use the same title block as the Availability share card: 24 px GPU name,
    # 64 px price, and identical 40 / 54 / 138 px alignment.
    price_font = FontProperties(
        fname=_GEIST_MEDIUM,
        size=64 * 72 / _OUTPUT_DPI,
    )
    family_font = FontProperties(
        fname=_GEIST_SEMIBOLD,
        size=24 * 72 / _OUTPUT_DPI,
    )
    figure.patches.extend(
        (
            FancyBboxPatch(
                (0.008, 0.016),
                0.984,
                0.968,
                boxstyle="round,pad=0,rounding_size=0.012",
                transform=figure.transFigure,
                facecolor=outside,
                edgecolor=blue,
                linewidth=1.15,
                zorder=-30,
            ),
            FancyBboxPatch(
                (0.020, 0.038),
                0.960,
                0.924,
                boxstyle="round,pad=0,rounding_size=0.006",
                transform=figure.transFigure,
                facecolor=paper,
                edgecolor="#7f9199",
                linewidth=0.75,
                zorder=-20,
            ),
        )
    )
    latest = selected_rows[-1] if selected_rows else None

    figure.text(
        40 / IMAGE_WIDTH,
        1 - (54 / IMAGE_HEIGHT),
        selected_family,
        color=blue,
        fontproperties=family_font,
    )
    figure.text(
        40 / IMAGE_WIDTH,
        1 - (138 / IMAGE_HEIGHT),
        _format_usd(latest["value"]) if latest else "PENDING",
        color=blue,
        fontproperties=price_font,
        parse_math=False,
    )

    axes = figure.add_axes((0.020, 0.165, 0.960, 0.559), facecolor="none")
    if selected_rows:
        dates = [row["date"] for row in selected_rows]
        values = [row["value"] for row in selected_rows]
        start, end = dates[0], dates[-1]
        if start == end:
            start -= timedelta(minutes=30)
            end += timedelta(minutes=30)
        smooth_dates, smooth_values = _shape_preserving_curve(dates, values)

        minimum = min(values)
        maximum = max(values)
        spread = max(maximum - minimum, maximum * 0.025, 0.12)
        domain_minimum = max(0, minimum - spread * 0.2)
        domain_maximum = maximum + spread * 0.2
        axes.set_xlim(start, end)
        axes.set_ylim(domain_minimum, domain_maximum)
        duration = max((end - start).total_seconds(), 1)
        value_span = max(domain_maximum - domain_minimum, 1e-9)
        fill_points = [
            (0.020, 0.038),
            *(
                (
                    0.020 + ((date - start).total_seconds() / duration) * 0.960,
                    0.165 + ((value - domain_minimum) / value_span) * 0.551,
                )
                for date, value in zip(smooth_dates, smooth_values, strict=True)
            ),
            (0.980, 0.038),
        ]
        figure.patches.append(
            Polygon(
                fill_points,
                closed=True,
                transform=figure.transFigure,
                facecolor=blue,
                edgecolor="none",
                alpha=0.055,
                zorder=-10,
            )
        )
        axes.plot(
            smooth_dates,
            smooth_values,
            color=blue,
            linewidth=2.5,
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=2,
        )
    axes.set_axis_off()
    return _publication_png(canvas)
