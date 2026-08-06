"""Render immutable StarSling workload-cost publication images."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .publication_chart_common import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    _finite_number,
    _format_cents,
    _format_observed,
    _publication_png,
    _workload_observed_at,
)


def render_sandbox_workload_publication(
    card: Mapping[str, Any],
) -> bytes:
    """Render the latest StarSling workload-cost comparison."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle

    workload = (card.get("data") or {}).get("workload") or {}
    summaries = [
        dict(row)
        for row in workload.get("service_summary") or []
        if isinstance(row, Mapping)
    ]
    fields = (
        "median_estimated_cost_usd",
        "p25_estimated_cost_usd",
        "p75_estimated_cost_usd",
    )
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
    headline_value = _finite_number(headline.get("median_estimated_cost_usd"))
    observed_at = _workload_observed_at(card)
    figure.text(
        0.052,
        0.915,
        "MEASURED WORKLOAD COST",
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
        "LATEST STARSLING RUN",
        color=accent,
        fontsize=11,
        fontweight=700,
        family="sans-serif",
    )
    value_label = _format_cents(headline_value)
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
        axes.xaxis.set_major_formatter(lambda value, _position: f"{value * 100:.1f}c")
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
        "ESTIMATED COST PER COMPLETED JOB",
        color=muted,
        fontsize=11,
        family="sans-serif",
        horizontalalignment="right",
    )
    return _publication_png(canvas)
