"""Human-readable output for the Compute Bazaar CLI."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any


Column = tuple[str, str, int]

TABLE_TITLES = {
    "availability": "GPU AVAILABILITY",
    "describe": "TABLE COLUMNS",
    "listings": "GPU LISTINGS",
    "price-index": "GPU PRICE INDEX",
    "providers": "PROVIDER COMPARISON",
    "query": "QUERY RESULT",
    "sql": "QUERY RESULT",
    "tables": "DATAFUSION TABLES",
}

TABLE_ROWS = {
    "describe": "columns",
    "tables": "tables",
}

TABLE_COLUMNS: dict[str, tuple[Column, ...]] = {
    "price-index": (
        ("GPU", "benchmark_family_id", 8),
        ("INDEX", "benchmark_usd_gpu_hr", 12),
        ("FLOOR", "floor_usd_gpu_hr", 12),
        ("P25", "provider_floor_p25_usd_gpu_hr", 12),
        ("P75", "provider_floor_p75_usd_gpu_hr", 12),
        ("PROVIDERS", "provider_count", 10),
        ("OFFERS", "offer_count", 8),
        ("OBSERVED", "gold_observed_at|latest_observed_at", 20),
    ),
    "availability": (
        ("OBSERVED", "observed_at", 20),
        ("GPU", "resource_type", 18),
        ("PROVIDER", "provider", 18),
        ("MEASURE", "measurement_kind", 22),
        ("AVAILABLE", "available_units", 11),
        ("TOTAL", "total_units", 10),
        ("UNIT", "unit", 16),
        ("STATUS", "stock_status", 14),
    ),
    "listings": (
        ("GPU", "gpu_model", 18),
        ("PROVIDER", "provider", 18),
        ("GPU-HR", "price_usd_gpu_hr", 12),
        ("INSTANCE-HR", "price_usd_instance_hr", 14),
        ("GPUS", "gpu_count", 6),
        ("REGION", "region", 18),
        ("AVAILABLE", "is_available", 10),
        ("OBSERVED", "observed_at", 20),
    ),
    "providers": (
        ("GPU", "gpu_model", 18),
        ("PROVIDER", "provider", 18),
        ("FLOOR", "floor_usd_gpu_hr", 12),
        ("MEAN", "simple_mean_usd_gpu_hr", 12),
        ("LISTINGS", "listing_count", 10),
        ("COUNTRIES", "country_count", 10),
        ("OBSERVED", "latest_observed_at", 20),
    ),
    "tables": (
        ("LAYER", "layer", 8),
        ("TABLE", "table_name", 46),
        ("TYPE", "table_type", 10),
        ("ROWS", "row_count", 12),
    ),
    "describe": (
        ("COLUMN", "column_name", 42),
        ("TYPE", "data_type", 24),
        ("NULL", "is_nullable", 6),
        ("MEANING", "meaning", 60),
    ),
}


def render_table_payload(payload: Mapping[str, Any], *, command: str) -> str:
    row_key = TABLE_ROWS.get(command, "rows")
    raw_rows = payload.get(row_key)
    if not isinstance(raw_rows, list):
        return _render_mapping(payload)

    rows = [row for row in raw_rows if isinstance(row, Mapping)]
    columns = _columns_for(command, rows)
    lines = [TABLE_TITLES.get(command, command.upper())]
    context = _context_line(payload)
    if context:
        lines.append(context)
    lines.append("")
    lines.extend(_render_rows(rows, columns))
    return "\n".join(lines)


def _columns_for(command: str, rows: list[Mapping[str, Any]]) -> tuple[Column, ...]:
    configured = TABLE_COLUMNS.get(command)
    if configured:
        return tuple(
            column
            for column in configured
            if any(_value_for(row, column[1]) is not None for row in rows)
        )
    if not rows:
        return ()
    keys = list(rows[0])
    return tuple((key.upper(), key, 28) for key in keys[:8])


def _render_rows(rows: list[Mapping[str, Any]], columns: tuple[Column, ...]) -> list[str]:
    if not rows:
        return ["No rows."]
    if not columns:
        return ["No displayable columns."]

    rendered = [
        [_format_value(_value_for(row, key), key=key) for _, key, _ in columns]
        for row in rows
    ]
    widths = [
        min(
            maximum,
            max(len(label), *(len(row[index]) for row in rendered)),
        )
        for index, (label, _, maximum) in enumerate(columns)
    ]
    header = "  ".join(
        _fit(label, widths[index])
        for index, (label, _, _) in enumerate(columns)
    )
    rule = "  ".join("-" * width for width in widths)
    body = [
        "  ".join(_fit(value, widths[index]) for index, value in enumerate(row))
        for row in rendered
    ]
    return [header, rule, *body]


def _context_line(payload: Mapping[str, Any]) -> str:
    source = payload.get("data_source")
    run = payload.get("run")
    parts: list[str] = []
    if isinstance(source, Mapping) and source.get("label"):
        parts.append(str(source["label"]))
    if isinstance(run, Mapping):
        if run.get("run_id"):
            parts.append(str(run["run_id"]))
        if run.get("observed_at"):
            parts.append(_format_time(str(run["observed_at"])))
    return " | ".join(parts)


def _render_mapping(payload: Mapping[str, Any]) -> str:
    rows = [{"field": key, "value": value} for key, value in payload.items()]
    return "\n".join(
        _render_rows(rows, (("FIELD", "field", 32), ("VALUE", "value", 88)))
    )


def _value_for(row: Mapping[str, Any], key: str) -> Any:
    for candidate in key.split("|"):
        value = row.get(candidate)
        if value is not None:
            return value
    return None


def _format_value(value: Any, *, key: str) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        rendered = f"{value:,.4f}".rstrip("0").rstrip(".")
        if "usd" in key or "price" in key or "benchmark" in key or "floor" in key:
            return f"${rendered}"
        return rendered
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    text = str(value)
    if "observed_at" in key or text.endswith("+00:00") or text.endswith("Z"):
        return _format_time(text)
    return text


def _format_time(value: str) -> str:
    return value.replace("T", " ").replace("+00:00", " UTC").replace("Z", " UTC")


def _fit(value: str, width: int) -> str:
    if len(value) > width:
        value = value[: max(0, width - 3)] + "..."
    return value.ljust(width)


def supports_auto_table(command: str) -> bool:
    return command in TABLE_TITLES


def available_formats() -> Iterable[str]:
    return ("auto", "table", "json")
