"""Official published GPU rate-card provider adapter.

These rows are not live marketplace inventory. They are provider-published
price observations that help benchmark construction when live marketplace
coverage is thin.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer


DEFAULT_RATE_CARD_PROVIDER = "published_rate_cards"
RATE_CARD_SOURCE_VERSION = "2026-07-23"


@dataclass(frozen=True)
class RateCardEntry:
    provider: str
    source_offer_id: str
    gpu_name: str
    price_usd_gpu_hr: float
    vram_gb: float
    gpu_count: int = 1
    country: str | None = None
    region: str | None = None
    source_url: str | None = None
    price_basis: str = "published_on_demand"
    availability_status: str = "published_rate"
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source_offer_id": self.source_offer_id,
            "gpu_name": self.gpu_name,
            "gpu_count": self.gpu_count,
            "vram_gb": self.vram_gb,
            "price_usd_gpu_hr": self.price_usd_gpu_hr,
            "price_usd_hr": self.price_usd_gpu_hr * self.gpu_count,
            "country": self.country,
            "region": self.region,
            "source_url": self.source_url,
            "price_basis": self.price_basis,
            "availability_status": self.availability_status,
            "notes": self.notes,
            "source_version": RATE_CARD_SOURCE_VERSION,
        }


PUBLISHED_RATE_CARDS: tuple[RateCardEntry, ...] = (
    RateCardEntry(
        provider="runpod",
        source_offer_id="runpod-pods-b300-288gb-1x",
        gpu_name="NVIDIA B300",
        vram_gb=288,
        price_usd_gpu_hr=7.39,
        source_url="https://www.runpod.io/pricing",
        notes="Pods secure/community cloud published price.",
    ),
    RateCardEntry(
        provider="runpod",
        source_offer_id="runpod-pods-h200-141gb-1x",
        gpu_name="NVIDIA H200",
        vram_gb=141,
        price_usd_gpu_hr=4.39,
        source_url="https://www.runpod.io/pricing",
        notes="Pods secure/community cloud published price.",
    ),
    RateCardEntry(
        provider="runpod",
        source_offer_id="runpod-pods-b200-180gb-1x",
        gpu_name="NVIDIA B200",
        vram_gb=180,
        price_usd_gpu_hr=5.89,
        source_url="https://www.runpod.io/pricing",
        notes="Pods secure/community cloud published price.",
    ),
    RateCardEntry(
        provider="runpod",
        source_offer_id="runpod-pods-h100-pcie-80gb-1x",
        gpu_name="NVIDIA H100 PCIe",
        vram_gb=80,
        price_usd_gpu_hr=2.89,
        source_url="https://www.runpod.io/pricing",
        notes="Pods published H100 PCIe price.",
    ),
    RateCardEntry(
        provider="runpod",
        source_offer_id="runpod-pods-h100-sxm-80gb-1x",
        gpu_name="NVIDIA H100 SXM",
        vram_gb=80,
        price_usd_gpu_hr=2.99,
        source_url="https://www.runpod.io/pricing",
        notes="Pods published H100 SXM price.",
    ),
    RateCardEntry(
        provider="lambda",
        source_offer_id="lambda-b200-sxm6-180gb-8x",
        gpu_name="NVIDIA B200 SXM6",
        gpu_count=8,
        vram_gb=180,
        price_usd_gpu_hr=6.69,
        country="US",
        source_url="https://lambda.ai/instances",
        notes="8x instance published price per GPU hour.",
    ),
    RateCardEntry(
        provider="lambda",
        source_offer_id="lambda-b200-sxm6-180gb-1x",
        gpu_name="NVIDIA B200 SXM6",
        vram_gb=180,
        price_usd_gpu_hr=6.99,
        country="US",
        source_url="https://lambda.ai/instances",
        notes="1x instance published price per GPU hour.",
    ),
    RateCardEntry(
        provider="lambda",
        source_offer_id="lambda-h100-sxm-80gb-8x",
        gpu_name="NVIDIA H100 SXM",
        gpu_count=8,
        vram_gb=80,
        price_usd_gpu_hr=3.99,
        country="US",
        source_url="https://lambda.ai/instances",
        notes="8x instance published price per GPU hour.",
    ),
    RateCardEntry(
        provider="lambda",
        source_offer_id="lambda-h100-pcie-80gb-1x",
        gpu_name="NVIDIA H100 PCIe",
        vram_gb=80,
        price_usd_gpu_hr=3.29,
        country="US",
        source_url="https://lambda.ai/instances",
        notes="1x PCIe instance published price per GPU hour.",
    ),
    RateCardEntry(
        provider="hyperstack",
        source_offer_id="hyperstack-b300-288gb-1x",
        gpu_name="NVIDIA B300",
        vram_gb=288,
        price_usd_gpu_hr=7.40,
        source_url="https://www.hyperstack.cloud/gpu-pricing",
        notes="On-demand GPU pricing.",
    ),
    RateCardEntry(
        provider="hyperstack",
        source_offer_id="hyperstack-b200-192gb-1x",
        gpu_name="NVIDIA B200",
        vram_gb=192,
        price_usd_gpu_hr=6.00,
        source_url="https://www.hyperstack.cloud/gpu-pricing",
        notes="On-demand GPU pricing.",
    ),
    RateCardEntry(
        provider="hyperstack",
        source_offer_id="hyperstack-h200-sxm-141gb-1x",
        gpu_name="NVIDIA H200 SXM",
        vram_gb=141,
        price_usd_gpu_hr=3.99,
        source_url="https://www.hyperstack.cloud/gpu-pricing",
        notes="On-demand GPU pricing.",
    ),
    RateCardEntry(
        provider="hyperstack",
        source_offer_id="hyperstack-h100-80gb-1x",
        gpu_name="NVIDIA H100",
        vram_gb=80,
        price_usd_gpu_hr=2.50,
        source_url="https://www.hyperstack.cloud/gpu-pricing",
        notes="On-demand GPU pricing.",
    ),
    RateCardEntry(
        provider="nebius",
        source_offer_id="nebius-b300-nvlink-288gb-1x",
        gpu_name="NVIDIA B300 NVLink",
        vram_gb=288,
        price_usd_gpu_hr=6.10,
        region="uk-south1",
        source_url="https://docs.nebius.com/compute/resources/pricing",
        notes="On-demand unified GPU hour price.",
    ),
    RateCardEntry(
        provider="nebius",
        source_offer_id="nebius-b200-nvlink-180gb-1x",
        gpu_name="NVIDIA B200 NVLink",
        vram_gb=180,
        price_usd_gpu_hr=5.50,
        region="us-central1",
        source_url="https://docs.nebius.com/compute/resources/pricing",
        notes="On-demand unified GPU hour price.",
    ),
    RateCardEntry(
        provider="nebius",
        source_offer_id="nebius-h200-nvlink-141gb-1x",
        gpu_name="NVIDIA H200 NVLink",
        vram_gb=141,
        price_usd_gpu_hr=3.50,
        source_url="https://docs.nebius.com/compute/resources/pricing",
        notes="On-demand unified GPU hour price.",
    ),
    RateCardEntry(
        provider="nebius",
        source_offer_id="nebius-h100-nvlink-80gb-1x",
        gpu_name="NVIDIA H100 NVLink",
        vram_gb=80,
        price_usd_gpu_hr=2.95,
        region="eu-north1",
        source_url="https://docs.nebius.com/compute/resources/pricing",
        notes="On-demand unified GPU hour price.",
    ),
    RateCardEntry(
        provider="crusoe",
        source_offer_id="crusoe-h200-hgx-141gb-1x",
        gpu_name="NVIDIA H200 HGX",
        vram_gb=141,
        price_usd_gpu_hr=4.29,
        source_url="https://www.crusoe.ai/cloud/pricing",
        notes="On-demand GPU instances pricing.",
    ),
    RateCardEntry(
        provider="crusoe",
        source_offer_id="crusoe-h100-hgx-80gb-1x",
        gpu_name="NVIDIA H100 HGX",
        vram_gb=80,
        price_usd_gpu_hr=3.90,
        source_url="https://www.crusoe.ai/cloud/pricing",
        notes="On-demand GPU instances pricing.",
    ),
    RateCardEntry(
        provider="tensordock",
        source_offer_id="tensordock-h100-sxm5-80gb-from",
        gpu_name="NVIDIA H100 SXM5",
        vram_gb=80,
        price_usd_gpu_hr=2.25,
        source_url="https://marketplace.tensordock.com/",
        notes="Public website 'from' price.",
    ),
)


def rate_card_providers() -> list[str]:
    return sorted({entry.provider for entry in PUBLISHED_RATE_CARDS})


def rate_card_entries(provider: str | None = None) -> list[RateCardEntry]:
    if provider in {None, DEFAULT_RATE_CARD_PROVIDER}:
        return list(PUBLISHED_RATE_CARDS)
    return [entry for entry in PUBLISHED_RATE_CARDS if entry.provider == provider]


def rate_card_raw_payload(provider: str | None = None) -> dict[str, Any]:
    entries = rate_card_entries(provider)
    return {
        "source_type": "published_provider_rate_cards",
        "source_version": RATE_CARD_SOURCE_VERSION,
        "provider": provider or DEFAULT_RATE_CARD_PROVIDER,
        "entry_count": len(entries),
        "providers": sorted({entry.provider for entry in entries}),
        "entries": [entry.to_dict() for entry in entries],
    }


def normalize_rate_card_entries(
    entries: Iterable[RateCardEntry | Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []
    for entry in entries:
        offer = normalize_rate_card_entry(entry, observed_at=observed_at, raw_ref=raw_ref)
        if offer is None:
            name = str(_entry_value(entry, "gpu_name") or "")
            if name:
                unknown_gpu_names.append(name)
            continue
        normalized.append(offer)
    return normalized, sorted(set(unknown_gpu_names))


def normalize_rate_card_entry(
    entry: RateCardEntry | Mapping[str, Any],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> GpuOffer | None:
    provider = str(_entry_value(entry, "provider") or "").strip()
    gpu_name = str(_entry_value(entry, "gpu_name") or "").strip()
    if not provider or not gpu_name:
        return None
    vram_gb = _float_or_none(_entry_value(entry, "vram_gb"))
    gpu_model = canonical_gpu_model(gpu_name, (vram_gb * 1024) if vram_gb else None)
    if not gpu_model:
        return None
    gpu_count = int(_entry_value(entry, "gpu_count") or 1)
    if gpu_count > 1:
        gpu_model = f"{gpu_model}_x{gpu_count}"
    price_usd_gpu_hr = _float_or_none(_entry_value(entry, "price_usd_gpu_hr"))
    if price_usd_gpu_hr is None or price_usd_gpu_hr <= 0:
        return None

    return GpuOffer(
        provider=provider,
        source_offer_id=str(_entry_value(entry, "source_offer_id") or f"{provider}:{gpu_name}:{price_usd_gpu_hr}"),
        observed_at=observed_at,
        gpu_raw_name=gpu_name,
        gpu_model=gpu_model,
        gpu_count=gpu_count,
        vram_gb=vram_gb,
        price_usd_hr=price_usd_gpu_hr * gpu_count,
        currency="USD",
        country=_string_or_none(_entry_value(entry, "country")),
        region=_string_or_none(_entry_value(entry, "region")),
        is_spot=False,
        is_secure=True,
        availability_status=str(_entry_value(entry, "availability_status") or "published_rate"),
        raw_ref=raw_ref,
        metadata={
            "source_kind": "published_rate_card",
            "price_basis": _entry_value(entry, "price_basis") or "published_on_demand",
            "source_url": _entry_value(entry, "source_url"),
            "source_version": RATE_CARD_SOURCE_VERSION,
            "notes": _entry_value(entry, "notes"),
        },
    )


def _entry_value(entry: RateCardEntry | Mapping[str, Any], key: str) -> Any:
    if isinstance(entry, RateCardEntry):
        return getattr(entry, key)
    return entry.get(key)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
