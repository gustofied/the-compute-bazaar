"""Render immutable GPU benchmark publication images."""

from __future__ import annotations

import io
import math
from collections.abc import Mapping
from typing import Any

from .publication_chart_common import (
    GPU_RANGES,
    GPU_RANGE_PRESENTATION,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    _format_axis_usd,
    _format_observed,
    _format_usd,
    _latest_observed_at,
    _range_change,
    _visible_gpu_series,
)


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
