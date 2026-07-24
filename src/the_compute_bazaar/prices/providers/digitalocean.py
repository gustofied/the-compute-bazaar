"""DigitalOcean live GPU Droplet sizes, prices, and launchable regions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_DIGITALOCEAN_API_BASE = "https://api.digitalocean.com/v2"


@dataclass(frozen=True)
class DigitalOceanSizesFetch:
    raw_payload: dict[str, Any]
    sizes: list[dict[str, Any]]


class DigitalOceanClient:
    def __init__(
        self,
        *,
        api_token: str,
        api_base: str = DEFAULT_DIGITALOCEAN_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        if not api_token:
            raise ValueError("DigitalOcean API token is required")
        self.api_token = api_token
        self.api_base = api_base.rstrip("/")
        self.session = session or retrying_session()

    def fetch_sizes(self, *, max_pages: int = 10) -> DigitalOceanSizesFetch:
        pages: list[dict[str, Any]] = []
        sizes: list[dict[str, Any]] = []
        url: str | None = f"{self.api_base}/sizes"
        params: dict[str, Any] = {"page": 1, "per_page": 200}

        for page_number in range(1, max(1, max_pages) + 1):
            assert url is not None
            response = self.session.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.api_token}",
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            page_sizes = _extract_sizes(payload)
            sizes.extend(page_sizes)
            pages.append(
                {
                    "page": page_number,
                    "request_url": url,
                    "payload": payload,
                    "item_count": len(page_sizes),
                }
            )
            next_page = _next_page(payload)
            if not next_page:
                break
            url = next_page
            params = {}

        return DigitalOceanSizesFetch(
            raw_payload={
                "mode": "authenticated_live_sizes",
                "source_url": f"{self.api_base}/sizes",
                "page_count": len(pages),
                "item_count": len(sizes),
                "pages": pages,
            },
            sizes=sizes,
        )


def normalize_sizes(
    sizes: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for entry in sizes:
        gpu_info = (
            entry.get("gpu_info") if isinstance(entry.get("gpu_info"), Mapping) else {}
        )
        if not gpu_info:
            continue
        gpu_name = str(gpu_info.get("model") or "")
        vram = gpu_info.get("vram") if isinstance(gpu_info.get("vram"), Mapping) else {}
        gpu_count = _int_or_none(gpu_info.get("count")) or 1
        total_vram_gb = _float_or_none(vram.get("amount"))
        vram_gb = (
            total_vram_gb / gpu_count
            if total_vram_gb is not None and gpu_count > 1
            else total_vram_gb
        )
        gpu_model = canonical_gpu_model(
            gpu_name,
            vram_gb * 1024 if vram_gb is not None else None,
        )
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"
        price = _float_or_none(entry.get("price_hourly"))
        if price is None or price <= 0:
            continue

        available = entry.get("available") is True
        regions = entry.get("regions") if isinstance(entry.get("regions"), list) else []
        if not regions:
            regions = [None]
        for region_value in regions:
            region = str(region_value or "").strip() or None
            normalized.append(
                GpuOffer(
                    provider="digitalocean",
                    source_offer_id=f"{entry.get('slug')}:{region or 'global'}",
                    observed_at=observed_at,
                    gpu_raw_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    vram_gb=vram_gb,
                    price_usd_hr=price,
                    available_gpu_count=gpu_count if available and region else None,
                    country=None,
                    region=region,
                    is_spot=False,
                    is_secure=True,
                    availability_status="available" if available else "unavailable",
                    raw_ref=raw_ref,
                    metadata={
                        "slug": entry.get("slug"),
                        "description": entry.get("description"),
                        "vcpus": entry.get("vcpus"),
                        "memory_mb": entry.get("memory"),
                        "disk_gb": entry.get("disk"),
                        "monthly_price_usd": entry.get("price_monthly"),
                        "price_basis": "digitalocean_gpu_droplet_hour",
                        "capacity_basis": (
                            "launchable_region_bundle_lower_bound"
                            if available and region
                            else None
                        ),
                    },
                )
            )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_sizes(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("sizes"), list):
        return []
    return [dict(row) for row in payload["sizes"] if isinstance(row, Mapping)]


def _next_page(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    links = payload.get("links")
    if not isinstance(links, Mapping):
        return None
    pages = links.get("pages")
    if not isinstance(pages, Mapping):
        return None
    value = pages.get("next")
    return str(value) if value else None


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
