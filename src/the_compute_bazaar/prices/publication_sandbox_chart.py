"""Render immutable Sandbox cost publication images."""

from __future__ import annotations

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
    from matplotlib import dates as mdates
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import FancyBboxPatch

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
                "value": value * 100,
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
    paper = "#f8f5eb"
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
    value_font = FontProperties(
        fname=_GEIST_MEDIUM,
        size=48 * 72 / _OUTPUT_DPI,
    )
    label_font = FontProperties(
        fname=_GEIST_MEDIUM,
        size=13 * 72 / _OUTPUT_DPI,
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
        1 - (122 / IMAGE_HEIGHT),
        value,
        color=green,
        fontproperties=value_font,
        parse_math=False,
    )
    figure.text(
        0.965,
        1 - (80 / IMAGE_HEIGHT),
        f"{presentation['label']} history",
        color=green,
        fontproperties=title_font,
        horizontalalignment="right",
    )

    axis = figure.add_axes((0.075, 0.14, 0.86, 0.61), facecolor=paper)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["id"], []).append(row)
    ordered = sorted(
        grouped.values(),
        key=lambda values: (
            values[0]["order"],
            values[0]["label"],
        ),
    )
    for values in ordered:
        color = series_colors[
            max(0, min(len(series_colors) - 1, values[0]["order"] - 1))
        ]
        axis.plot(
            [row["date"] for row in values],
            [row["value"] for row in values],
            color=color,
            linewidth=2.2,
            marker="o",
            markersize=3.2,
            label=values[0]["label"],
        )

    axis.spines[:].set_visible(False)
    axis.grid(axis="y", color=rule, linewidth=0.8)
    axis.tick_params(axis="both", colors=green, labelsize=10, length=0, pad=7)
    axis.yaxis.set_major_formatter(lambda value, _position: f"{value:.0f}c")
    axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    if rows:
        start = min(row["date"] for row in rows)
        end = max(row["date"] for row in rows)
        if start == end:
            start -= timedelta(hours=12)
            end += timedelta(hours=12)
        axis.set_xlim(start, end)
    axis.legend(
        loc="upper left",
        bbox_to_anchor=(0, 1.13),
        ncol=3,
        frameon=False,
        prop=label_font,
        labelcolor=green,
        handlelength=1.6,
        columnspacing=1.4,
    )
    return _publication_png(canvas)


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
