"""Render immutable Sandbox cost publication images."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from .publication_chart_common import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    SANDBOX_RANGE_PRESENTATION,
    _finite_number,
    _format_cents,
    _parse_datetime,
    _publication_png,
    _shape_preserving_curve,
)

_FONT_ROOT = Path(__file__).with_name("assets") / "fonts"
_GEIST_MEDIUM = _FONT_ROOT / "Geist-Medium.ttf"
_GEIST_SEMIBOLD = _FONT_ROOT / "Geist-SemiBold.ttf"
_RENDER_DPI = 200
_OUTPUT_DPI = 100


def render_sandbox_workload_publication(
    card: Mapping[str, Any],
    *,
    range_id: str = "latest",
) -> bytes:
    """Render one workload's current cost or retained cost history."""
    if range_id not in SANDBOX_RANGE_PRESENTATION:
        raise ValueError(f"Unknown Sandbox publication range: {range_id}")
    if range_id != "latest":
        return _render_sandbox_history(card, range_id=range_id)

    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import FancyBboxPatch

    workload = (card.get("data") or {}).get("workload") or {}
    rows: list[dict[str, Any]] = []
    for source in workload.get("service_summary") or []:
        if not isinstance(source, Mapping):
            continue
        median = _finite_number(source.get("median_estimated_cost_usd"))
        if median is None:
            continue
        lower = _finite_number(source.get("p25_estimated_cost_usd"))
        upper = _finite_number(source.get("p75_estimated_cost_usd"))
        rows.append(
            {
                "label": str(
                    source.get("service_label")
                    or source.get("series_label")
                    or source.get("series_id")
                    or "Service"
                ),
                "order": int(source.get("series_order") or 0),
                "median": median,
                "lower": median if lower is None else lower,
                "upper": median if upper is None else upper,
            }
        )
    rows.sort(key=lambda row: row["order"])

    outside = "#e5ecd4"
    paper = "#f8f5eb"
    green = "#526c28"
    band = "#b7d07b"
    rule = "#dfe6cf"
    frame = "#889b64"
    figure = Figure(
        figsize=(IMAGE_WIDTH / _OUTPUT_DPI, IMAGE_HEIGHT / _OUTPUT_DPI),
        dpi=_RENDER_DPI,
        facecolor=outside,
    )
    canvas = FigureCanvasAgg(figure)
    title_font = FontProperties(
        fname=_GEIST_SEMIBOLD,
        size=24 * 72 / _OUTPUT_DPI,
    )
    value_font = FontProperties(
        fname=_GEIST_MEDIUM,
        size=64 * 72 / _OUTPUT_DPI,
    )
    label_font = FontProperties(
        fname=_GEIST_SEMIBOLD,
        size=15 * 72 / _OUTPUT_DPI,
    )
    row_value_font = FontProperties(
        fname=_GEIST_MEDIUM,
        size=15 * 72 / _OUTPUT_DPI,
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
                edgecolor=green,
                linewidth=1.05,
                zorder=-30,
            ),
            FancyBboxPatch(
                (0.020, 0.038),
                0.960,
                0.924,
                boxstyle="round,pad=0,rounding_size=0.006",
                transform=figure.transFigure,
                facecolor=paper,
                edgecolor=frame,
                linewidth=0.75,
                zorder=-20,
            ),
        )
    )

    headline = card.get("headline") or {}
    value = _format_cents(_finite_number(headline.get("median_estimated_cost_usd")))
    figure.text(
        40 / IMAGE_WIDTH,
        1 - (54 / IMAGE_HEIGHT),
        "Sandbox cost",
        color=green,
        fontproperties=title_font,
    )
    figure.text(
        40 / IMAGE_WIDTH,
        1 - (138 / IMAGE_HEIGHT),
        value,
        color=green,
        fontproperties=value_font,
        parse_math=False,
    )

    maximum = max((row["upper"] for row in rows), default=1.0)
    maximum = maximum * 1.06 if maximum else 1.0
    row_top = 0.704
    row_bottom = 0.085
    row_step = (row_top - row_bottom) / max(len(rows), 1)
    for index, row in enumerate(rows):
        center = row_top - (index + 0.5) * row_step
        figure.add_artist(
            _figure_line(
                figure,
                x=(0.020, 0.980),
                y=(center, center),
                color=rule,
                width=0.8,
            )
        )
        figure.text(
            0.04,
            center + row_step * 0.20,
            row["label"],
            color=green,
            fontproperties=label_font,
        )
        figure.text(
            0.96,
            center + row_step * 0.20,
            _format_cents(row["median"]),
            color=green,
            fontproperties=row_value_font,
            horizontalalignment="right",
        )
        lower_x = 0.04 + (row["lower"] / maximum) * 0.92
        upper_x = 0.04 + (row["upper"] / maximum) * 0.92
        median_x = 0.04 + (row["median"] / maximum) * 0.92
        figure.add_artist(
            _figure_line(
                figure,
                x=(lower_x, upper_x),
                y=(center, center),
                color=band,
                width=8.5,
            )
        )
        figure.add_artist(
            _figure_line(
                figure,
                x=(median_x, median_x),
                y=(center - 0.012, center + 0.012),
                color=green,
                width=2.1,
            )
        )
    return _publication_png(canvas)


def _render_sandbox_history(
    card: Mapping[str, Any],
    *,
    range_id: str,
) -> bytes:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties
    from matplotlib.lines import Line2D
    from matplotlib.patches import FancyBboxPatch, PathPatch, Rectangle
    from matplotlib.path import Path as MatplotlibPath

    workload = (card.get("data") or {}).get("workload") or {}
    rows: list[dict[str, Any]] = []
    for source in workload.get("measured_history") or []:
        if not isinstance(source, Mapping):
            continue
        observed_at = _parse_datetime(
            source.get("generated_at")
            or (
                f"{source.get('observed_date')}T12:00:00Z"
                if source.get("observed_date")
                else None
            )
        )
        value = _finite_number(source.get("median_estimated_cost_usd"))
        if observed_at is None or value is None:
            continue
        rows.append(
            {
                "date": observed_at,
                "value": value,
                "id": str(source.get("series_id") or "service"),
                "label": str(
                    source.get("series_label")
                    or source.get("service_label")
                    or source.get("series_id")
                    or "Service"
                ),
                "order": int(source.get("series_order") or 0),
            }
        )
    rows.sort(key=lambda row: (row["date"], row["order"]))
    if range_id == "7d" and rows:
        cutoff = max(row["date"] for row in rows) - timedelta(days=6)
        rows = [row for row in rows if row["date"] >= cutoff]

    outside = "#e5ecd4"
    paper = "#ffffff"
    green = "#526c28"
    rule = "#dfe6cf"
    frame = "#889b64"
    series_colors = (
        "#405d22",
        "#54722c",
        "#688638",
        "#7d9b45",
        "#91af53",
        "#a6c361",
    )
    figure = Figure(
        figsize=(IMAGE_WIDTH / _OUTPUT_DPI, IMAGE_HEIGHT / _OUTPUT_DPI),
        dpi=_RENDER_DPI,
        facecolor=outside,
    )
    canvas = FigureCanvasAgg(figure)
    title_font = FontProperties(
        fname=_GEIST_SEMIBOLD,
        size=24 * 72 / _OUTPUT_DPI,
    )
    value_font = FontProperties(fname=_GEIST_MEDIUM, size=64 * 72 / _OUTPUT_DPI)
    label_font = FontProperties(fname=_GEIST_SEMIBOLD, size=20 * 72 / _OUTPUT_DPI)
    range_font = FontProperties(fname=_GEIST_SEMIBOLD, size=20 * 72 / _OUTPUT_DPI)
    figure.patches.extend(
        (
            FancyBboxPatch(
                (0.008, 0.016),
                0.984,
                0.968,
                boxstyle="round,pad=0,rounding_size=0.012",
                transform=figure.transFigure,
                facecolor=outside,
                edgecolor=green,
                linewidth=1.05,
                zorder=-30,
            ),
            FancyBboxPatch(
                (0.020, 0.038),
                0.960,
                0.924,
                boxstyle="round,pad=0,rounding_size=0.006",
                transform=figure.transFigure,
                facecolor=paper,
                edgecolor=frame,
                linewidth=0.75,
                zorder=-20,
            ),
        )
    )

    headline = card.get("headline") or {}
    value = _format_cents(_finite_number(headline.get("median_estimated_cost_usd")))
    presentation = SANDBOX_RANGE_PRESENTATION[range_id]
    figure.text(
        40 / IMAGE_WIDTH,
        1 - (54 / IMAGE_HEIGHT),
        "Sandbox cost",
        color=green,
        fontproperties=title_font,
    )
    figure.text(
        40 / IMAGE_WIDTH,
        1 - (138 / IMAGE_HEIGHT),
        value,
        color=green,
        fontproperties=value_font,
        parse_math=False,
    )
    figure.text(
        1160 / IMAGE_WIDTH,
        1 - (54 / IMAGE_HEIGHT),
        _sandbox_range_label(rows, range_id, presentation["label"]),
        color=green,
        fontproperties=range_font,
        horizontalalignment="right",
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["id"], []).append(row)
    ordered = sorted(
        grouped.values(),
        key=lambda values: (
            values[-1]["value"],
            values[0]["order"],
            values[0]["label"],
        ),
    )
    if not ordered:
        return _publication_png(canvas)

    start = min(row["date"] for row in rows)
    end = max(row["date"] for row in rows)
    if start == end:
        start -= timedelta(minutes=30)
        end += timedelta(minutes=30)
    time_span = max((end - start).total_seconds(), 1)

    chart_top = 174 / IMAGE_HEIGHT
    chart_bottom = 0.038
    chart_height = 1 - chart_top - chart_bottom
    row_height = chart_height / len(ordered)
    plot_left = 0.020
    plot_right = 0.980

    for index, values in enumerate(ordered):
        color = series_colors[
            max(0, min(len(series_colors) - 1, values[0]["order"] - 1))
        ]
        row_top = 1 - chart_top - index * row_height
        row_bottom = row_top - row_height
        if index:
            figure.patches.append(
                Rectangle(
                    (plot_left, row_bottom),
                    plot_right - plot_left,
                    row_height,
                    transform=figure.transFigure,
                    facecolor=color,
                    edgecolor="none",
                    alpha=0.08,
                    zorder=-5,
                )
            )
            figure.add_artist(
                _figure_line(
                    figure,
                    x=(plot_left, plot_right),
                    y=(row_top, row_top),
                    color=rule,
                    width=0.8,
                )
            )

        minimum = min(row["value"] for row in values)
        maximum = max(row["value"] for row in values)
        spread = max(maximum - minimum, maximum * 0.035, 0.00035)
        domain_minimum = max(0, minimum - spread * 0.24)
        domain_maximum = maximum + spread * 0.24
        value_span = max(domain_maximum - domain_minimum, 0.00035)
        line_top = row_top - (38 / IMAGE_HEIGHT)
        line_bottom = row_bottom + (10 / IMAGE_HEIGHT)

        dates = [row["date"] for row in values]
        amounts = [row["value"] for row in values]
        smooth_dates, smooth_values = _shape_preserving_curve(dates, amounts)
        points = [
            (
                plot_left
                + ((date - start).total_seconds() / time_span)
                * (plot_right - plot_left),
                line_bottom
                + ((amount - domain_minimum) / value_span)
                * (line_top - line_bottom),
            )
            for date, amount in zip(smooth_dates, smooth_values)
        ]
        if len(points) == 1:
            points = [(plot_left, points[0][1]), (plot_right, points[0][1])]

        area_vertices = [
            (points[0][0], row_bottom),
            *points,
            (points[-1][0], row_bottom),
            (points[0][0], row_bottom),
        ]
        area_codes = [
            MatplotlibPath.MOVETO,
            *([MatplotlibPath.LINETO] * len(points)),
            MatplotlibPath.LINETO,
            MatplotlibPath.CLOSEPOLY,
        ]
        figure.patches.append(
            PathPatch(
                MatplotlibPath(area_vertices, area_codes),
                transform=figure.transFigure,
                facecolor=color,
                edgecolor="none",
                alpha=0.18,
                zorder=1,
            )
        )
        figure.add_artist(
            Line2D(
                [point[0] for point in points],
                [point[1] for point in points],
                transform=figure.transFigure,
                color=green if index == 0 else color,
                linewidth=2.45,
                solid_capstyle="round",
                solid_joinstyle="round",
                zorder=3,
            )
        )

        label_y = row_top - (27 / IMAGE_HEIGHT)
        key_y = row_top - (21 / IMAGE_HEIGHT)
        figure.add_artist(
            _figure_line(
                figure,
                x=(40 / IMAGE_WIDTH, 58 / IMAGE_WIDTH),
                y=(key_y, key_y),
                color=color,
                width=2.8,
            )
        )
        figure.text(
            70 / IMAGE_WIDTH,
            label_y,
            values[0]["label"],
            color=green,
            fontproperties=label_font,
        )
        figure.text(
            1160 / IMAGE_WIDTH,
            label_y,
            _format_cents(values[-1]["value"]),
            color=green,
            fontproperties=label_font,
            horizontalalignment="right",
        )
    return _publication_png(canvas)


def _sandbox_range_label(
    rows: list[dict[str, Any]],
    range_id: str,
    fallback: str,
) -> str:
    if not rows:
        return fallback.upper()
    if range_id == "7d":
        return "7D"
    start = min(row["date"] for row in rows)
    end = max(row["date"] for row in rows)
    days = max(math.ceil((end - start).total_seconds() / (24 * 60 * 60)), 1)
    if days <= 1:
        return "TODAY"
    if days < 31:
        return f"{days}D"
    if days < 365:
        return f"{max(1, days // 30)}M+"
    return f"{max(1, days // 365)}Y+"


def _figure_line(
    figure: Any,
    *,
    x: tuple[float, float],
    y: tuple[float, float],
    color: str,
    width: float,
) -> Any:
    from matplotlib.lines import Line2D

    return Line2D(
        x,
        y,
        transform=figure.transFigure,
        color=color,
        linewidth=width,
        solid_capstyle="round",
    )
