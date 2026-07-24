"""GridStackHub public external GPU price-reference adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_GRIDSTACKHUB_API_URL = "https://gridstackhub.ai/api/gpu-pricing"
FRONTIER_VRAM_GB = {
    "H100": 80.0,
    "H200": 141.0,
    "B200": 180.0,
    "B300": 288.0,
}
PROVIDER_ALIASES = {
    "amazon_web_services": "aws",
    "aws": "aws",
    "google_cloud": "gcp",
    "google_cloud_platform": "gcp",
    "lambda_labs": "lambda",
    "lambdalabs": "lambda",
    "massed_compute": "massed_compute",
    "massedcompute": "massed_compute",
    "ovh_cloud": "ovhcloud",
}


@dataclass(frozen=True)
class GridStackHubFetch:
    raw_payload: dict[str, Any]
    rows: list[dict[str, Any]]
    as_of: str | None


class GridStackHubClient:
    def __init__(
        self,
        *,
        api_url: str = DEFAULT_GRIDSTACKHUB_API_URL,
        session: requests.Session | None = None,
    ) -> None:
        self.api_url = api_url
        self.session = session or retrying_session()

    def fetch_prices(self) -> GridStackHubFetch:
        response = self.session.get(
            self.api_url,
            params={},
            headers={
                "Accept": "application/json",
                "User-Agent": "the-compute-bazaar/0.1",
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        rows = _extract_rows(payload)
        return GridStackHubFetch(
            raw_payload={
                "mode": "external_gpu_price_reference",
                "source_url": self.api_url,
                "payload": payload,
                "item_count": len(rows),
            },
            rows=rows,
            as_of=(
                str(payload.get("as_of"))
                if isinstance(payload, Mapping) and payload.get("as_of")
                else None
            ),
        )


def normalize_reference_prices(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: str | None,
    fetched_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for entry in _latest_unique_rows(rows):
        if entry.get("active") is False:
            continue
        provider_name = str(entry.get("provider") or "").strip()
        provider = _provider_id(provider_name)
        source_offer_id = str(entry.get("id") or "").strip()
        gpu_name = str(entry.get("gpu_model") or "").strip()
        gpu_count = _int_or_none(entry.get("gpu_count")) or 1
        hourly_rate = _float_or_none(entry.get("hourly_rate"))
        if (
            not provider
            or not source_offer_id
            or not gpu_name
            or gpu_count <= 0
            or hourly_rate is None
            or hourly_rate <= 0
        ):
            continue

        expected_vram_gb = FRONTIER_VRAM_GB.get(gpu_name.upper())
        source_vram_gb = _float_or_none(entry.get("gpu_vram_gb"))
        vram_gb = expected_vram_gb or source_vram_gb
        gpu_model = canonical_gpu_model(
            gpu_name,
            vram_gb * 1024 if vram_gb is not None else None,
        )
        if not gpu_model:
            unknown_gpu_names.append(gpu_name)
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        pricing_type = str(entry.get("pricing_type") or "").strip().lower()
        observed_at = _parse_datetime(entry.get("last_updated")) or fetched_at
        normalized.append(
            GpuOffer(
                provider=provider,
                source_connector="gridstackhub",
                source_offer_id=f"gridstackhub:{source_offer_id}",
                observed_at=observed_at,
                gpu_raw_name=gpu_name,
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                vram_gb=vram_gb,
                price_usd_hr=hourly_rate,
                currency="USD",
                country=None,
                region=_string_or_none(entry.get("region")),
                is_spot=pricing_type in {"spot", "preemptible"},
                availability_status="external_reference",
                raw_ref=raw_ref,
                metadata={
                    "upstream_provider": provider_name,
                    "provider_url": entry.get("provider_url"),
                    "instance_type": entry.get("instance_type"),
                    "pricing_type": pricing_type,
                    "source_url": entry.get("source_url"),
                    "source_last_updated": entry.get("last_updated"),
                    "external_as_of": as_of,
                    "scrape_source": entry.get("scrape_source"),
                    "source_vram_gb": source_vram_gb,
                    "per_gpu_hourly": entry.get("per_gpu_hourly"),
                    "minimum_commitment": entry.get("minimum_commitment"),
                    "interconnect": entry.get("interconnect"),
                    "notes": entry.get("notes"),
                    "price_basis": "external_aggregator_reference",
                    "capacity_basis": None,
                    "benchmark_eligible": False,
                },
            )
        )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        return []
    return [dict(row) for row in payload["data"] if isinstance(row, Mapping)]


def _latest_unique_rows(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        clean = dict(row)
        key = (
            _provider_id(str(clean.get("provider") or "")),
            str(clean.get("gpu_model") or "").upper(),
            _int_or_none(clean.get("gpu_count")) or 1,
            str(clean.get("instance_type") or "").strip().lower(),
            str(clean.get("pricing_type") or "").strip().lower(),
            str(clean.get("region") or "").strip().lower(),
            _float_or_none(clean.get("hourly_rate")),
        )
        current = latest.get(key)
        if current is None or str(clean.get("last_updated") or "") > str(
            current.get("last_updated") or ""
        ):
            latest[key] = clean
    return [latest[key] for key in sorted(latest, key=lambda value: str(value))]


def _provider_id(value: str) -> str:
    normalized = (
        value.strip()
        .lower()
        .replace(".", "_")
        .replace("-", "_")
        .replace(" ", "_")
    )
    return PROVIDER_ALIASES.get(normalized, normalized).strip("_")


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
