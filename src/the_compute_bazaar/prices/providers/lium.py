"""Lium market data adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer


DEFAULT_LIUM_API_BASE = "https://lium.io/api"


@dataclass(frozen=True)
class LiumExecutorsFetch:
    raw_payload: dict[str, Any]
    executors: list[dict[str, Any]]


class LiumClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str = DEFAULT_LIUM_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.session = session or requests.Session()

    def list_executors(self, query: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return currently available Lium executors."""
        return self.fetch_executors(query=query).executors

    def fetch_executors(self, query: Mapping[str, Any] | None = None) -> LiumExecutorsFetch:
        """Return one Lium executor page and preserve the raw provider response."""
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        clean_query = {key: value for key, value in (query or {}).items() if value is not None}
        response = self.session.get(
            f"{self.api_base}/executors",
            params=clean_query,
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        executors = extract_executors(payload)
        return LiumExecutorsFetch(
            raw_payload={
                "query": clean_query,
                "payload": payload,
                "extracted_executor_count": len(executors),
            },
            executors=executors,
        )

    def fetch_executor_pages(
        self,
        query: Mapping[str, Any] | None = None,
        *,
        paginate: bool = False,
        max_pages: int = 10,
    ) -> LiumExecutorsFetch:
        """Return Lium executors, optionally walking pages until exhausted or unchanged."""
        base_query = dict(query or {})
        if not paginate:
            single_page = self.fetch_executors(query=base_query)
            return LiumExecutorsFetch(
                raw_payload={
                    "mode": "single_page",
                    "pages": [single_page.raw_payload],
                    "executors": single_page.executors,
                    "executor_count": len(single_page.executors),
                },
                executors=single_page.executors,
            )

        page_size = _int_or_none(base_query.get("size")) or 200
        start_page = _int_or_none(base_query.get("page")) or 1
        page_limit = max(1, int(max_pages))
        pages: list[dict[str, Any]] = []
        executors: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for page in range(start_page, start_page + page_limit):
            page_query = dict(base_query)
            page_query["page"] = page
            page_query["size"] = page_size
            fetched = self.fetch_executors(query=page_query)
            rows = fetched.executors
            pages.append(fetched.raw_payload)

            new_rows = []
            for row in rows:
                key = _executor_key(row)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                new_rows.append(row)
            executors.extend(new_rows)

            if not rows or not new_rows or len(rows) < page_size:
                break

        return LiumExecutorsFetch(
            raw_payload={
                "mode": "paginated",
                "page_size": page_size,
                "start_page": start_page,
                "max_pages": page_limit,
                "pages": pages,
                "executors": executors,
                "executor_count": len(executors),
            },
            executors=executors,
        )


def extract_executors(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "executors", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def normalize_executors(
    executors: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for entry in executors:
        offer = normalize_executor(entry, observed_at=observed_at, raw_ref=raw_ref)
        if offer is None:
            gpu_name = _gpu_name(entry)
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue
        normalized.append(offer)

    return normalized, sorted(set(unknown_gpu_names))


def normalize_executor(
    entry: Mapping[str, Any],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> GpuOffer | None:
    gpu_name = _gpu_name(entry)
    if not gpu_name:
        return None

    vram_mb = _gpu_vram_mb(entry)
    gpu_model = canonical_gpu_model(gpu_name, vram_mb)
    if not gpu_model:
        return None

    gpu_count = _gpu_count(entry)
    if gpu_count <= 0:
        return None
    if gpu_count > 1:
        gpu_model = f"{gpu_model}_x{gpu_count}"

    price_per_gpu = _float_or_none(entry.get("price_per_gpu"))
    if price_per_gpu is None or price_per_gpu <= 0:
        return None

    location = entry.get("location") if isinstance(entry.get("location"), Mapping) else {}
    country = _string_or_none(location.get("country"))
    region = ", ".join(
        part
        for part in [
            _string_or_none(location.get("city")),
            _string_or_none(location.get("region_name") or location.get("region")),
        ]
        if part
    ) or None

    source_offer_id = str(entry.get("id") or entry.get("executor_id") or f"{gpu_name}:{price_per_gpu}:{gpu_count}")
    specs = entry.get("specs") if isinstance(entry.get("specs"), Mapping) else {}

    return GpuOffer(
        provider="lium",
        source_offer_id=source_offer_id,
        observed_at=observed_at,
        gpu_raw_name=gpu_name,
        gpu_model=gpu_model,
        gpu_count=gpu_count,
        vram_gb=round(vram_mb / 1024, 2) if vram_mb else None,
        price_usd_hr=price_per_gpu * gpu_count,
        currency="USD",
        country=country,
        region=region,
        is_spot=_bool_or_none(_nested(specs, "is_spot")),
        is_secure=(entry.get("tier") == "secure") if entry.get("tier") else None,
        availability_status="available",
        raw_ref=raw_ref,
        metadata={
            "available_gpu_count": entry.get("available_gpu_count"),
            "collateral_deposited": entry.get("collateral_deposited"),
            "effective_download_speed_mbps": entry.get("effective_download_speed_mbps"),
            "effective_upload_speed_mbps": entry.get("effective_upload_speed_mbps"),
            "is_slow_machine": entry.get("is_slow_machine"),
            "machine_name": entry.get("machine_name"),
            "max_cuda_version": entry.get("max_cuda_version"),
            "miner_hotkey": entry.get("miner_hotkey"),
            "min_gpu_count_for_rental": entry.get("min_gpu_count_for_rental"),
            "price_per_gpu": price_per_gpu,
            "tier": entry.get("tier"),
            "uptime_in_minutes": entry.get("uptime_in_minutes"),
        },
    )


def _gpu_name(entry: Mapping[str, Any]) -> str:
    machine_name = _string_or_none(entry.get("machine_name"))
    if machine_name:
        return machine_name

    first_detail = _first_gpu_detail(entry)
    return _string_or_none(first_detail.get("name")) or ""


def _gpu_count(entry: Mapping[str, Any]) -> int:
    for value in [
        entry.get("available_gpu_count"),
        entry.get("gpu_count"),
        _nested(entry, "specs", "gpu", "count"),
    ]:
        parsed = _int_or_none(value)
        if parsed is not None and parsed > 0:
            return parsed
    return 1


def _gpu_vram_mb(entry: Mapping[str, Any]) -> float | None:
    first_detail = _first_gpu_detail(entry)
    return _float_or_none(first_detail.get("capacity"))


def _first_gpu_detail(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    details = _nested(entry, "specs", "gpu", "details")
    if isinstance(details, list) and details and isinstance(details[0], Mapping):
        return details[0]
    return {}


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


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


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _executor_key(row: Mapping[str, Any]) -> str:
    for key in ("id", "executor_id", "miner_hotkey"):
        value = row.get(key)
        if value is not None:
            return f"{key}:{value}"
    return json.dumps(row, sort_keys=True, default=str)
