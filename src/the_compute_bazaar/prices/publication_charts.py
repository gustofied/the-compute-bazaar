"""Publication chart rendering and chart-series preparation."""

from __future__ import annotations

import io
import math
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any


GPU_FAMILIES = ("H100", "H200", "B200", "B300")
PRIME_OFFER_FAMILIES = ("H100", "H200")
GPU_RANGES: dict[str, timedelta | None] = {
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "all": None,
}
GPU_RANGE_PRESENTATION = {
    "1d": {"path": "1-day", "label": "1 day", "short_label": "1D"},
    "7d": {"path": "7-day", "label": "7 days", "short_label": "7D"},
    "all": {
        "path": "full-history",
        "label": "full retained history",
        "short_label": "ALL",
    },
}
IMAGE_WIDTH = 1200
IMAGE_HEIGHT = 630


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
            row["benchmark"]
            for row in rows
            if row.get("benchmark") is not None
        ]
        price_domain = [*prices, *benchmarks]
        minimum, maximum = min(price_domain), max(price_domain)
        spread = max(maximum - minimum, abs(prices[-1]) * 0.12, 0.2)
        price_axes.set_ylim(max(0, minimum - spread * 0.14), maximum + spread * 0.14)
        benchmark_dates = [
            row["date"] for row in rows if row.get("benchmark") is not None
        ]
        if benchmark_dates:
            price_axes.plot(
                benchmark_dates,
                benchmarks,
                color=green,
                linewidth=1.6,
                linestyle=(0, (3, 4)),
                alpha=0.72,
                solid_capstyle="round",
                solid_joinstyle="round",
            )
        price_axes.plot(
            dates,
            prices,
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
        axes.xaxis.set_major_formatter(
            lambda value, _position: f"{value * 100:.1f}c"
        )
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


def _visible_gpu_series(
    cards: Mapping[str, Mapping[str, Any]],
    range_id: str,
) -> dict[str, list[dict[str, Any]]]:
    if range_id not in GPU_RANGES:
        raise ValueError(f"Unknown GPU publication range: {range_id}")
    parsed: dict[str, list[dict[str, Any]]] = {}
    for family in GPU_FAMILIES:
        card = cards.get(family) or {}
        rows = []
        for row in card.get("series") or []:
            if not isinstance(row, Mapping):
                continue
            observed_at = _parse_datetime(row.get("observed_at"))
            value = _finite_number(row.get("value"))
            if observed_at is None or value is None:
                continue
            lower = _finite_number(row.get("lower"))
            upper = _finite_number(row.get("upper"))
            rows.append(
                {
                    "date": observed_at,
                    "value": value,
                    "lower": value if lower is None else lower,
                    "upper": value if upper is None else upper,
                    "run_id": row.get("run_id"),
                }
            )
        rows.sort(key=lambda item: item["date"])
        parsed[family] = rows

    all_rows = [row for rows in parsed.values() for row in rows]
    duration = GPU_RANGES[range_id]
    if not duration or not all_rows:
        return parsed
    cutoff = max(row["date"] for row in all_rows) - duration
    return {
        family: [row for row in rows if row["date"] >= cutoff]
        for family, rows in parsed.items()
    }


def _prime_publication_series(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in card.get("series") or []:
        if not isinstance(row, Mapping):
            continue
        observed_at = _parse_datetime(row.get("observed_at"))
        price = _finite_number(row.get("value"))
        if observed_at is None or price is None:
            continue
        rows.append(
            {
                "date": observed_at,
                "price": price,
                "offers": max(
                    0,
                    int(row.get("configuration_count") or row.get("offer_count") or 0),
                ),
                "providers": max(0, int(row.get("provider_count") or 0)),
                "benchmark": _finite_number(
                    row.get("market_benchmark_usd_gpu_hr")
                ),
            }
        )
    rows.sort(key=lambda row: row["date"])
    return rows


def _prime_offer_band_series(
    card: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Reconstruct lower, middle, and upper asking-price shelf counts."""
    if not rows:
        return []
    data = card.get("data")
    events = data.get("event_history") if isinstance(data, Mapping) else []
    normalized_events: list[dict[str, Any]] = []
    for event in events or []:
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("event_type") or "")
        observed_at = _parse_datetime(event.get("observed_at"))
        listing_id = str(event.get("listing_id") or "")
        price = _finite_number(
            event.get("price_before_usd_gpu_hr")
            if event_type == "left_availability"
            else event.get("price_after_usd_gpu_hr")
        )
        if not listing_id or observed_at is None or price is None:
            continue
        normalized_events.append(
            {
                "type": event_type,
                "date": observed_at,
                "listing_id": listing_id,
                "price": price,
                "previous_date": _parse_datetime(event.get("previous_observed_at")),
            }
        )
    normalized_events.sort(key=lambda event: event["date"])

    final_date = rows[-1]["date"]
    active: dict[str, dict[str, Any]] = {}
    intervals: list[dict[str, Any]] = []
    for event in normalized_events:
        listing_id = event["listing_id"]
        if event["type"] == "entered":
            previous = active.get(listing_id)
            if previous:
                previous["end"] = event["date"]
                intervals.append(previous)
            active[listing_id] = {
                **event,
                "start": event["date"],
                "end": None,
            }
        elif event["type"] == "left_availability":
            previous = active.pop(listing_id, None)
            if previous:
                previous["end"] = event["date"]
                intervals.append(previous)
            elif event["previous_date"] is not None:
                intervals.append(
                    {
                        **event,
                        "start": event["previous_date"],
                        "end": event["date"],
                    }
                )
    for interval in active.values():
        interval["end"] = final_date
        interval["is_open"] = True
        intervals.append(interval)
    intervals = [
        interval
        for interval in intervals
        if interval["end"] > interval["start"]
    ]

    prices = sorted(interval["price"] for interval in intervals)
    if not prices:
        return [
            {
                "date": row["date"],
                "lower": 0,
                "middle": int(row.get("offers") or 0),
                "upper": 0,
                "total": int(row.get("offers") or 0),
            }
            for row in rows
        ]
    minimum, maximum = prices[0], prices[-1]
    step = max(0.01, (maximum - minimum) / 3)
    lower_limit = minimum + step
    upper_limit = minimum + step * 2

    result: list[dict[str, Any]] = []
    for row in rows:
        row_date = row["date"]
        current: dict[str, dict[str, Any]] = {}
        for interval in intervals:
            within = interval["start"] <= row_date and (
                row_date < interval["end"]
                or (interval.get("is_open") and row_date == interval["end"])
            )
            if not within:
                continue
            previous = current.get(interval["listing_id"])
            if previous is None or previous["start"] < interval["start"]:
                current[interval["listing_id"]] = interval
        counts = {"lower": 0, "middle": 0, "upper": 0}
        for interval in current.values():
            if interval["price"] < lower_limit:
                counts["lower"] += 1
            elif interval["price"] < upper_limit:
                counts["middle"] += 1
            else:
                counts["upper"] += 1
        expected_total = int(row.get("offers") or 0)
        total = sum(counts.values())
        if total < expected_total:
            counts["middle"] += expected_total - total
        elif total > expected_total:
            excess = total - expected_total
            for key in ("upper", "middle", "lower"):
                removed = min(excess, counts[key])
                counts[key] -= removed
                excess -= removed
        result.append(
            {
                "date": row_date,
                **counts,
                "total": expected_total,
            }
        )
    return result


def _series_change(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if len(rows) < 2:
        return {
            "value": None,
            "label": "Tracking has just begun",
            "direction": "unknown",
        }
    first = _finite_number(rows[0].get("price"))
    latest = _finite_number(rows[-1].get("price"))
    if first in {None, 0} or latest is None:
        return {
            "value": None,
            "label": "Change unavailable",
            "direction": "unknown",
        }
    value = ((latest - first) / first) * 100
    if abs(value) < 0.05:
        return {
            "value": 0.0,
            "label": "Unchanged since tracking began",
            "direction": "flat",
        }
    direction = "up" if value > 0 else "down"
    return {
        "value": round(value, 6),
        "label": f"{direction.title()} {abs(value):.1f}% since tracking began",
        "direction": direction,
    }


def _workload_observed_at(card: Mapping[str, Any]) -> datetime | None:
    headline = card.get("headline") or {}
    return _parse_datetime(headline.get("observed_at")) or _parse_datetime(
        card.get("as_of")
    )


def _publication_png(canvas: Any) -> bytes:
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


def _latest_observed_at(rows: list[Mapping[str, Any]]) -> datetime | None:
    return rows[-1]["date"] if rows else None


def _range_change(
    rows: list[Mapping[str, Any]],
    range_id: str,
) -> dict[str, float | str | None]:
    if len(rows) < 2 or not rows[0]["value"]:
        return {
            "value": None,
            "label": "First retained observation",
            "direction": "unknown",
        }
    change = ((rows[-1]["value"] - rows[0]["value"]) / rows[0]["value"]) * 100
    rounded_change = round(change, 1)
    direction = "flat"
    direction_label = "Unchanged"
    if rounded_change > 0:
        direction = "up"
        direction_label = f"Up {abs(rounded_change):.1f}%"
    elif rounded_change < 0:
        direction = "down"
        direction_label = f"Down {abs(rounded_change):.1f}%"
    if range_id == "all":
        label = f"{direction_label} since {rows[0]['date'].strftime('%d %b %Y')}"
    else:
        label = f"{direction_label} over {GPU_RANGE_PRESENTATION[range_id]['label']}"
    return {
        "value": round(change, 6),
        "label": label,
        "direction": direction,
    }


def _format_observed(value: datetime | None) -> str:
    if value is None:
        return "Observation pending"
    return f"Observed {value.strftime('%d %b %Y, %H:%M UTC')}"


def _format_observed_date(value: datetime | None) -> str:
    if value is None:
        return "the latest retained observation"
    return value.strftime("%d %b %Y at %H:%M UTC")


def _format_usd(value: float) -> str:
    if value < 1:
        return f"${value:.3f}"
    if value < 10:
        return f"${value:.2f}"
    return f"${value:.1f}"


def _format_cents(value: float | None) -> str:
    if value is None:
        return "pending"
    return f"{value * 100:.2f}c"


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "pending"
    if value >= 120:
        return f"{value / 60:.1f} min"
    return f"{value:.0f} sec"


def _format_axis_usd(value: float) -> str:
    if value == 0:
        return "$0"
    if value < 1:
        return f"${value:.2f}"
    return f"${value:.1f}"


def _format_axis_seconds(value: float) -> str:
    if value >= 120:
        return f"{value / 60:.0f}m"
    return f"{value:.0f}s"


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
