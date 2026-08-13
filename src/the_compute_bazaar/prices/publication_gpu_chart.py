"""Render immutable GPU benchmark publication images."""

from __future__ import annotations

import io
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from .publication_chart_common import (
    GPU_RANGES,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    _format_usd,
    _shape_preserving_curve,
    _visible_gpu_series,
)

_FONT_ROOT = Path(__file__).with_name("assets") / "fonts"
_GEIST_REGULAR = _FONT_ROOT / "Geist-Regular.ttf"
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
    from matplotlib.patches import FancyBboxPatch

    if selected_family not in cards:
        raise ValueError(f"Unknown GPU publication family: {selected_family}")
    if range_id not in GPU_RANGES:
        raise ValueError(f"Unknown GPU publication range: {range_id}")

    selected_rows = _visible_gpu_series(cards, range_id).get(selected_family, [])
    outside = "#efede4"
    sleeve = "#91aecb"
    paper = "#ffffff"
    ink = "#142027"
    blue = "#315f82"
    rule = "#a7b1b3"

    figure = Figure(
        figsize=(IMAGE_WIDTH / _OUTPUT_DPI, IMAGE_HEIGHT / _OUTPUT_DPI),
        dpi=_RENDER_DPI,
        facecolor=outside,
    )
    canvas = FigureCanvasAgg(figure)
    price_font = FontProperties(fname=_GEIST_MEDIUM, size=56)
    family_font = FontProperties(fname=_GEIST_SEMIBOLD, size=24)
    figure.patches.extend(
        (
            FancyBboxPatch(
                (0.018, 0.034),
                0.964,
                0.932,
                boxstyle="round,pad=0,rounding_size=0.008",
                transform=figure.transFigure,
                facecolor=sleeve,
                edgecolor=blue,
                linewidth=1.35,
                zorder=-20,
            ),
            FancyBboxPatch(
                (0.034, 0.064),
                0.932,
                0.872,
                boxstyle="round,pad=0,rounding_size=0.006",
                transform=figure.transFigure,
                facecolor=paper,
                edgecolor="#315f82",
                linewidth=0.8,
                zorder=-10,
            ),
        )
    )
    latest = selected_rows[-1] if selected_rows else None

    figure.text(
        0.060,
        0.855,
        selected_family,
        color=blue,
        fontproperties=family_font,
    )
    figure.text(
        0.060,
        0.710,
        _format_usd(latest["value"]) if latest else "PENDING",
        color=ink,
        fontproperties=price_font,
        parse_math=False,
    )

    axes = figure.add_axes((0.034, 0.064, 0.932, 0.586), facecolor=paper)
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
        for tick in (
            domain_minimum,
            (domain_minimum + domain_maximum) / 2,
            domain_maximum,
        ):
            axes.axhline(
                tick,
                color=rule,
                alpha=0.42,
                linewidth=1,
                zorder=0,
            )
        axes.fill_between(
            smooth_dates,
            smooth_values,
            domain_minimum,
            color=blue,
            alpha=0.055,
            linewidth=0,
            zorder=1,
        )
        axes.plot(
            smooth_dates,
            smooth_values,
            color=blue,
            linewidth=3.5,
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=2,
        )
        axes.plot(
            dates[-1],
            values[-1],
            marker="o",
            markersize=7.5,
            markerfacecolor=paper,
            markeredgecolor=blue,
            markeredgewidth=2.2,
            linestyle="none",
            clip_on=False,
            zorder=3,
        )

    axes.set_axis_off()

    rgba_buffer = io.BytesIO()
    canvas.print_png(rgba_buffer)
    rgba_buffer.seek(0)

    from PIL import Image

    rgb_buffer = io.BytesIO()
    with Image.open(rgba_buffer) as source:
        rgb = source.convert("RGB")
        if rgb.size != (IMAGE_WIDTH, IMAGE_HEIGHT):
            rgb = rgb.resize(
                (IMAGE_WIDTH, IMAGE_HEIGHT),
                resample=Image.Resampling.LANCZOS,
            )
        rgb.save(
            rgb_buffer,
            format="PNG",
            optimize=True,
        )
    return rgb_buffer.getvalue()
