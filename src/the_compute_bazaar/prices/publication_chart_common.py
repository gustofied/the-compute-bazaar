"""Shared data preparation and formatting for publication charts."""

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


def _shape_preserving_curve(
    dates: list[datetime],
    values: list[float],
    *,
    samples_per_segment: int = 10,
) -> tuple[list[datetime], list[float]]:
    """Interpolate observations without overshooting local highs or lows."""
    if len(dates) != len(values):
        raise ValueError("Curve dates and values must have the same length")
    if len(dates) < 3:
        return dates, values

    seconds = [(date - dates[0]).total_seconds() for date in dates]
    intervals = [right - left for left, right in zip(seconds, seconds[1:])]
    if any(interval <= 0 for interval in intervals):
        return dates, values
    slopes = [
        (right - left) / interval
        for left, right, interval in zip(values, values[1:], intervals)
    ]

    def endpoint_derivative(
        first_interval: float,
        second_interval: float,
        first_slope: float,
        second_slope: float,
    ) -> float:
        derivative = (
            (2 * first_interval + second_interval) * first_slope
            - first_interval * second_slope
        ) / (first_interval + second_interval)
        if derivative * first_slope <= 0:
            return 0.0
        if first_slope * second_slope < 0 and abs(derivative) > 3 * abs(first_slope):
            return 3 * first_slope
        return derivative

    derivatives = [
        endpoint_derivative(intervals[0], intervals[1], slopes[0], slopes[1])
    ]
    for index in range(1, len(values) - 1):
        previous_slope = slopes[index - 1]
        next_slope = slopes[index]
        if previous_slope == 0 or next_slope == 0 or previous_slope * next_slope < 0:
            derivatives.append(0.0)
            continue
        previous_interval = intervals[index - 1]
        next_interval = intervals[index]
        first_weight = 2 * next_interval + previous_interval
        second_weight = next_interval + 2 * previous_interval
        derivatives.append(
            (first_weight + second_weight)
            / (
                first_weight / previous_slope
                + second_weight / next_slope
            )
        )
    derivatives.append(
        endpoint_derivative(
            intervals[-1],
            intervals[-2],
            slopes[-1],
            slopes[-2],
        )
    )

    smooth_dates: list[datetime] = []
    smooth_values: list[float] = []
    resolution = max(2, samples_per_segment)
    for index, interval in enumerate(intervals):
        for sample in range(resolution):
            progress = sample / resolution
            progress_squared = progress * progress
            progress_cubed = progress_squared * progress
            start_weight = 2 * progress_cubed - 3 * progress_squared + 1
            start_tangent_weight = progress_cubed - 2 * progress_squared + progress
            end_weight = -2 * progress_cubed + 3 * progress_squared
            end_tangent_weight = progress_cubed - progress_squared
            smooth_dates.append(dates[index] + timedelta(seconds=interval * progress))
            smooth_values.append(
                start_weight * values[index]
                + start_tangent_weight * interval * derivatives[index]
                + end_weight * values[index + 1]
                + end_tangent_weight * interval * derivatives[index + 1]
            )
    smooth_dates.append(dates[-1])
    smooth_values.append(values[-1])
    return smooth_dates, smooth_values


def _smooth_observation_values(
    values: list[float],
    *,
    radius: int = 4,
) -> list[float]:
    """Soften isolated hourly jumps while preserving the observed endpoints."""
    if len(values) < 3 or radius < 1:
        return list(values)
    radius = min(radius, 4)
    weights = [1, 4, 7, 10, 12, 10, 7, 4, 1]
    center = len(weights) // 2
    smoothed: list[float] = []
    for index in range(len(values)):
        weighted_total = 0.0
        weight_total = 0
        for offset in range(-radius, radius + 1):
            candidate = index + offset
            if candidate < 0 or candidate >= len(values):
                continue
            weight_index = center + offset
            weight = weights[weight_index] if 0 <= weight_index < len(weights) else 1
            weighted_total += values[candidate] * weight
            weight_total += weight
        smoothed.append(weighted_total / weight_total)
    smoothed[-1] = values[-1]
    return smoothed


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
                "benchmark": _finite_number(row.get("market_benchmark_usd_gpu_hr")),
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
        interval for interval in intervals if interval["end"] > interval["start"]
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


def _format_axis_usd(value: float) -> str:
    if value == 0:
        return "$0"
    if value < 1:
        return f"${value:.2f}"
    return f"${value:.1f}"


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
