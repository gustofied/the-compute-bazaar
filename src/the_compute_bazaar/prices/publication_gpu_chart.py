"""Render immutable GPU benchmark publication images."""

from __future__ import annotations

import io
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .publication_chart_common import (
    GPU_RANGES,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    _format_axis_usd,
    _format_usd,
    _visible_gpu_series,
)


def _date_labels(start: datetime, end: datetime) -> tuple[str, str, str]:
    """Return the same compact start, middle, and end labels as the live card."""
    middle = start + ((end - start) / 2)
    formatter = "%d %b" if (end - start).total_seconds() > 36 * 60 * 60 else "%H:%M"
    return tuple(point.strftime(formatter) for point in (start, middle, end))


def render_gpu_benchmark_publication(
    *,
    cards: Mapping[str, Mapping[str, Any]],
    selected_family: str,
    range_id: str,
) -> bytes:
    """Render a social preview that matches the live GPU index share card."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

    if selected_family not in cards:
        raise ValueError(f"Unknown GPU publication family: {selected_family}")
    if range_id not in GPU_RANGES:
        raise ValueError(f"Unknown GPU publication range: {range_id}")

    selected_rows = _visible_gpu_series(cards, range_id).get(selected_family, [])
    frame = "#dbe5e9"
    paper = "#ffffff"
    ink = "#142027"
    muted = "#5f6f76"
    selected_color = "#315f82"
    rule = "#a7b1b3"

    figure = Figure(
        figsize=(IMAGE_WIDTH / 100, IMAGE_HEIGHT / 100),
        dpi=100,
        facecolor=frame,
    )
    canvas = FigureCanvasAgg(figure)
    figure.patches.append(
        Rectangle(
            (0.01, 0.02),
            0.98,
            0.96,
            transform=figure.transFigure,
            facecolor=paper,
            edgecolor="#8ea1a9",
            linewidth=1,
            zorder=-10,
        )
    )

    latest = selected_rows[-1] if selected_rows else None
    figure.text(
        0.043,
        0.895,
        selected_family,
        color=ink,
        fontsize=17,
        fontweight="bold",
        family="DejaVu Sans",
    )
    figure.text(
        0.043,
        0.755,
        _format_usd(latest["value"]) if latest else "PENDING",
        color=ink,
        fontsize=52,
        fontweight="normal",
        family="DejaVu Sans",
        parse_math=False,
    )

    axes = figure.add_axes((0.01, 0.205, 0.98, 0.44), facecolor=paper)
    if selected_rows:
        dates = [row["date"] for row in selected_rows]
        values = [row["value"] for row in selected_rows]
        start, end = dates[0], dates[-1]
        if start == end:
            start -= timedelta(minutes=30)
            end += timedelta(minutes=30)

        minimum = min(values)
        maximum = max(values)
        spread = max(maximum - minimum, maximum * 0.025, 0.12)
        domain_minimum = max(0, minimum - spread * 0.2)
        domain_maximum = maximum + spread * 0.2
        ticks = (
            domain_minimum,
            (domain_minimum + domain_maximum) / 2,
            domain_maximum,
        )

        axes.set_xlim(start, end)
        axes.set_ylim(domain_minimum, domain_maximum)
        axes.set_yticks(ticks)
        axes.grid(axis="y", color=rule, alpha=0.44, linewidth=1)
        axes.set_axisbelow(True)
        axes.fill_between(
            dates,
            values,
            domain_minimum,
            step="post",
            color=selected_color,
            alpha=0.055,
            linewidth=0,
            zorder=1,
        )
        axes.plot(
            dates,
            values,
            color=selected_color,
            linewidth=3.5,
            drawstyle="steps-post",
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=3,
        )

        for tick in ticks:
            axes.text(
                0.98,
                (tick - domain_minimum) / (domain_maximum - domain_minimum),
                _format_axis_usd(tick),
                transform=axes.transAxes,
                color=ink,
                alpha=0.76,
                fontsize=11,
                fontweight="normal",
                family="DejaVu Sans Mono",
                horizontalalignment="right",
                verticalalignment="center",
                zorder=4,
            )

        labels = _date_labels(start, end)
        for x, label, alignment in (
            (0.03, labels[0], "left"),
            (0.5, labels[1], "center"),
            (0.97, labels[2], "right"),
        ):
            figure.text(
                x,
                0.075,
                label,
                color=ink,
                fontsize=11,
                fontweight="normal",
                family="DejaVu Sans Mono",
                horizontalalignment=alignment,
            )
    else:
        axes.text(
            0.5,
            0.5,
            "History is still being collected",
            transform=axes.transAxes,
            color=muted,
            fontsize=14,
            family="DejaVu Sans",
            horizontalalignment="center",
            verticalalignment="center",
        )
        axes.set_ylim(0, 1)

    axes.set_xticks([])
    axes.tick_params(axis="y", length=0, labelleft=False, labelright=False)
    for spine in axes.spines.values():
        spine.set_visible(False)

    figure.lines.append(
        Line2D(
            (0.03, 0.97),
            (0.13, 0.13),
            transform=figure.transFigure,
            color=rule,
            alpha=0.44,
            linewidth=1,
        )
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
