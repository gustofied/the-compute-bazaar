"""Sesterce GPU Cloud offers."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..contracts import (
    GpuOffer,
    NormalizedOffers,
    RejectedOffer,
    SourceRead,
    stable_id,
)


API_BASE = "https://api.cloud.sesterce.com"
USER_AGENT = "compute-bazaar/1.0 (+https://github.com/gustofied/the-compute-bazaar)"
GPU_ALIASES = {
    "H100": "H100_80GB",
    "H200": "H200_141GB",
    "B200": "B200_192GB",
    "B300": "B300_288GB",
    "A10080G": "A100_80GB",
    "A10080GB": "A100_80GB",
    "V10032G": "V100_32GB",
    "V10032GB": "V100_32GB",
    "RTXPRO6000": "RTX_PRO_6000_96GB",
    "RTX6000ADA": "RTX_6000_ADA_48GB",
    "RTX4000ADA": "RTX_4000_ADA_20GB",
}


class SesterceSource:
    name = "sesterce"

    def __init__(self, api_key: str, *, api_base: str = API_BASE) -> None:
        if not api_key:
            raise ValueError("Sesterce API key is required")
        self.api_key = api_key
        self.instances_endpoint = f"{api_base.rstrip('/')}/gpu-cloud/instances"
        self.endpoint = f"{self.instances_endpoint}/offers"

    def read(self, *, observed_at: datetime | None = None) -> SourceRead:
        observed_at = observed_at or datetime.now(UTC)
        request = Request(
            self.endpoint,
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "x-api-key": self.api_key,
            },
        )
        started = time.monotonic()
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310
                status = response.status
                payload = _decode(response.read())
            error = (
                None
                if isinstance(payload, list)
                else "Sesterce returned an invalid offers response"
            )
        except HTTPError as exc:
            status = exc.code
            payload = _decode(exc.read())
            error = f"Sesterce returned HTTP {status}"
        except (URLError, OSError) as exc:
            status = 0
            payload = None
            error = f"Sesterce request failed: {getattr(exc, 'reason', exc)}"
        return SourceRead(
            source=self.name,
            endpoint=self.endpoint,
            parameters={},
            observed_at=observed_at,
            status_code=status,
            payload=payload,
            elapsed_ms=round((time.monotonic() - started) * 1000, 3),
            authentication="x-api-key",
            error=error,
        )

    def create_instance(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        request = Request(
            self.instances_endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "x-api-key": self.api_key,
            },
        )
        try:
            with urlopen(request, timeout=120) as response:  # noqa: S310
                result = _decode(response.read())
                status = response.status
        except HTTPError as exc:
            detail = _decode(exc.read())
            raise RuntimeError(f"Sesterce returned HTTP {exc.code}: {detail}") from exc
        except (URLError, OSError) as exc:
            raise RuntimeError(
                f"Sesterce request failed: {getattr(exc, 'reason', exc)}"
            ) from exc
        if status != 201 or not isinstance(result, Mapping):
            raise RuntimeError(
                f"Sesterce returned an invalid create response ({status})"
            )
        return result

    def get_instance(self, instance_id: str) -> Mapping[str, Any]:
        request = Request(
            f"{self.instances_endpoint}/{instance_id}",
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "x-api-key": self.api_key,
            },
        )
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310
                result = _decode(response.read())
        except HTTPError as exc:
            detail = _decode(exc.read())
            raise RuntimeError(f"Sesterce returned HTTP {exc.code}: {detail}") from exc
        except (URLError, OSError) as exc:
            raise RuntimeError(
                f"Sesterce request failed: {getattr(exc, 'reason', exc)}"
            ) from exc
        if not isinstance(result, Mapping):
            raise RuntimeError("Sesterce returned an invalid instance response")
        return result

    def delete_instance(self, instance_id: str) -> None:
        request = Request(
            f"{self.instances_endpoint}/{instance_id}",
            method="DELETE",
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "x-api-key": self.api_key,
            },
        )
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310
                status = response.status
        except HTTPError as exc:
            detail = _decode(exc.read())
            raise RuntimeError(f"Sesterce returned HTTP {exc.code}: {detail}") from exc
        except (URLError, OSError) as exc:
            raise RuntimeError(
                f"Sesterce request failed: {getattr(exc, 'reason', exc)}"
            ) from exc
        if status != 204:
            raise RuntimeError(
                f"Sesterce returned an invalid delete response ({status})"
            )

    def normalize(
        self,
        read: SourceRead,
        *,
        source_run_id: str,
    ) -> NormalizedOffers:
        if not read.complete:
            return NormalizedOffers(())
        entries = read.payload if isinstance(read.payload, list) else []
        offers: list[GpuOffer] = []
        rejected: list[RejectedOffer] = []
        for index, value in enumerate(entries):
            if not isinstance(value, Mapping):
                rejected.append(RejectedOffer(index, "offer is not an object"))
                continue
            offer_id = _text(value.get("instanceId"))
            gpu_name = _text(value.get("gpuName"))
            gpu_count = _integer(value.get("gpuCount"))
            price = _number(value.get("hourlyPrice"))
            if gpu_name.upper() == "CPU":
                rejected.append(RejectedOffer(index, "not a GPU offer", offer_id))
                continue
            if not offer_id or not gpu_name or not gpu_count or gpu_count < 1:
                rejected.append(
                    RejectedOffer(index, "missing offer identity", offer_id)
                )
                continue
            if price is None or price <= 0:
                rejected.append(RejectedOffer(index, "invalid hourly price", offer_id))
                continue
            if _text(value.get("deploymentType")).lower() != "vm":
                rejected.append(RejectedOffer(index, "not a VM offer", offer_id))
                continue
            cloud = (
                value.get("cloud") if isinstance(value.get("cloud"), Mapping) else {}
            )
            config = (
                value.get("configuration")
                if isinstance(value.get("configuration"), Mapping)
                else {}
            )
            locations = value.get("availability")
            if not isinstance(locations, list) or not locations:
                rejected.append(RejectedOffer(index, "no regions", offer_id))
                continue
            total_vram = _number(config.get("vRamGB"))
            for location in locations:
                if not isinstance(location, Mapping) or not _text(
                    location.get("region")
                ):
                    rejected.append(RejectedOffer(index, "invalid region", offer_id))
                    continue
                offers.append(
                    GpuOffer(
                        observation_id="obs-"
                        + stable_id(
                            source_run_id,
                            _text(cloud.get("_id")),
                            offer_id,
                            _text(location.get("region")),
                        ),
                        source_run_id=source_run_id,
                        observed_at=read.observed_at,
                        source=self.name,
                        intermediary=self.name,
                        operator_id=_optional_text(cloud.get("_id")),
                        operator=_optional_text(cloud.get("name")),
                        offer_id=offer_id,
                        gpu_model=canonical_gpu(gpu_name, total_vram, gpu_count),
                        gpu_count=gpu_count,
                        country_code=_optional_text(location.get("countryCode")),
                        region=_text(location.get("region")),
                        ask_usd_hr=price / gpu_count,
                        available=_boolean(location.get("available")),
                    )
                )
        return NormalizedOffers(tuple(offers), tuple(rejected))


def canonical_gpu(name: str, total_vram: float | None, count: int) -> str | None:
    compact = "".join(character for character in name.upper() if character.isalnum())
    if compact in GPU_ALIASES:
        return GPU_ALIASES[compact]
    known = {
        "A10",
        "A16",
        "A30",
        "A40",
        "A4000",
        "A5000",
        "A6000",
        "GAUDI2",
        "L4",
        "L40",
        "L40S",
        "RTX4090",
        "RTX5090",
        "V100",
    }
    if compact not in known:
        return None
    per_gpu = total_vram / count if total_vram and count else None
    return f"{compact}_{round(per_gpu)}GB" if per_gpu else compact


def _decode(body: bytes) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body.decode("utf-8", errors="replace")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    return _text(value) or None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
