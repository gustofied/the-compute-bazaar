"""Build the public Akash GPU and CPU capacity history."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import CARD_CONTRACT
from .public_view_common import number, observation_window


AKASH_PROVIDERS_URL = "https://console-api.akash.network/v1/providers"


def akash_capacity_view(
    *,
    manifest: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Shape Akash capacity rows without mixing them into Prime availability."""
    resources = [
        _resource_view(
            rows=rows,
            resource_type="ALL_GPU",
            resource_id="GPU",
            label="GPU capacity",
            unit="GPU units",
            scale=1.0,
        ),
        _resource_view(
            rows=rows,
            resource_type="ALL_CPU",
            resource_id="CPU",
            label="CPU capacity",
            unit="vCPU",
            scale=1_000.0,
        ),
    ]
    resources = [resource for resource in resources if resource["history"]]
    as_of = max(
        (
            str(resource["current"].get("observed_at") or "")
            for resource in resources
            if resource.get("current")
        ),
        default=str(manifest.get("observed_at") or ""),
    )
    return {
        "contract": CARD_CONTRACT,
        "card_type": "akash_capacity_history",
        "card_id": "akash-capacity",
        "as_of": as_of or None,
        "status": "frozen" if resources else "unavailable",
        "manifest": dict(manifest),
        "source": {
            "name": "Akash Network capacity",
            "providers_url": AKASH_PROVIDERS_URL,
        },
        "measurement_notes": [
            "Capacity is aggregated across online Akash providers.",
            "Used means capacity reported active and consumed by deployments.",
            "CPU values are converted from Akash millicpu to vCPU.",
        ],
        "resources": resources,
    }


def _resource_view(
    *,
    rows: list[Mapping[str, Any]],
    resource_type: str,
    resource_id: str,
    label: str,
    unit: str,
    scale: float,
) -> dict[str, Any]:
    history = [
        _series_row(row, scale=scale)
        for row in rows
        if str(row.get("resource_type") or "").upper() == resource_type
        and number(row.get("total_units")) is not None
    ]
    history.sort(key=lambda row: str(row.get("observed_at") or ""))
    return {
        "resource_id": resource_id,
        "label": label,
        "unit": unit,
        "current": history[-1] if history else None,
        "observation_window": observation_window(history),
        "history": history,
    }


def _series_row(row: Mapping[str, Any], *, scale: float) -> dict[str, Any]:
    return {
        "observed_at": row.get("observed_at"),
        "total": _scaled(row.get("total_units"), scale=scale),
        "used": _scaled(row.get("rented_units"), scale=scale),
        "available": _scaled(row.get("available_units"), scale=scale),
        "pending": _scaled(row.get("pending_units"), scale=scale),
        "used_share": number(row.get("rented_share")),
        "available_share": number(row.get("available_share")),
        "source_run_id": row.get("source_run_id"),
        "gold_run_id": row.get("gold_run_id"),
    }


def _scaled(value: Any, *, scale: float) -> float | None:
    parsed = number(value)
    return parsed / scale if parsed is not None else None
