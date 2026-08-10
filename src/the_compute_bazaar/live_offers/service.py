"""Fetch and normalize offers directly from RunPod and Verda."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, cast

from ..prices.normalize import canonical_gpu_model
from .models import LiveOffer, LiveOfferResult, ProviderName, ProviderStatus


class LiveOfferError(RuntimeError):
    pass


class LiveOfferService:
    def __init__(
        self,
        *,
        runpod_api_key: str | None = None,
        verda_client_id: str | None = None,
        verda_client_secret: str | None = None,
        verda_access_token: str | None = None,
        runpod_client: Any | None = None,
        verda_client: Any | None = None,
    ) -> None:
        self.runpod_api_key = runpod_api_key
        self.verda_client_id = verda_client_id
        self.verda_client_secret = verda_client_secret
        self.verda_access_token = verda_access_token
        self._runpod_client = runpod_client
        self._verda_client = verda_client

    @classmethod
    def from_environment(cls) -> LiveOfferService:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        return cls(
            runpod_api_key=os.getenv("RUNPOD_API_KEY"),
            verda_client_id=os.getenv("VERDA_CLIENT_ID"),
            verda_client_secret=os.getenv("VERDA_CLIENT_SECRET"),
            verda_access_token=os.getenv("VERDA_ACCESS_TOKEN"),
        )

    def list_offers(
        self,
        *,
        providers: Iterable[str] | None = None,
        gpu_model: str | None = None,
        include_unavailable: bool = False,
        limit: int = 100,
    ) -> LiveOfferResult:
        observed_at = datetime.now(timezone.utc)
        selected = _provider_names(providers)
        offers: list[LiveOffer] = []
        statuses: list[ProviderStatus] = []
        for provider in selected:
            try:
                rows = (
                    self._runpod_offers(observed_at)
                    if provider == "runpod"
                    else self._verda_offers(observed_at)
                )
            except _CredentialsRequired as exc:
                statuses.append(
                    ProviderStatus(
                        provider=provider,
                        status="credentials_required",
                        message=str(exc),
                    )
                )
                continue
            except (OSError, RuntimeError, ValueError) as exc:
                statuses.append(
                    ProviderStatus(
                        provider=provider,
                        status="error",
                        message=str(exc),
                    )
                )
                continue
            filtered = [
                row
                for row in rows
                if _matches_gpu(row.gpu_model, gpu_model)
                and (include_unavailable or row.available)
            ]
            offers.extend(filtered)
            statuses.append(
                ProviderStatus(
                    provider=provider,
                    status="ok",
                    offer_count=len(filtered),
                )
            )

        offers.sort(
            key=lambda row: (
                not row.available,
                row.price_usd_gpu_hr,
                row.provider,
                row.offer_id,
            )
        )
        return LiveOfferResult(
            observed_at=observed_at,
            offers=tuple(offers[:limit]),
            providers=tuple(statuses),
        )

    def inspect(self, offer_id: str) -> LiveOffer:
        provider = offer_id.partition(":")[0].lower()
        if provider not in {"runpod", "verda"}:
            raise LiveOfferError(f"Unknown live offer: {offer_id}")
        result = self.list_offers(
            providers=[provider], include_unavailable=True, limit=1000
        )
        for offer in result.offers:
            if offer.offer_id == offer_id:
                return offer
        status = result.providers[0]
        if status.status != "ok":
            raise LiveOfferError(status.message or f"{provider} is unavailable")
        raise LiveOfferError(
            f"Offer {offer_id} is no longer visible. Run: compute-bazaar offers list"
        )

    def _runpod_offers(self, observed_at: datetime) -> list[LiveOffer]:
        if self._runpod_client is None:
            try:
                from ..prices.providers.runpod import RunpodClient
            except ImportError as exc:
                raise LiveOfferError(
                    "Live offers require: uv sync --extra live"
                ) from exc
            self._runpod_client = RunpodClient(api_key=self.runpod_api_key)
        fetched = self._runpod_client.fetch_live_market()
        locations = _runpod_locations(fetched.data_centers)
        offers: list[LiveOffer] = []
        for row in fetched.gpu_types:
            native_gpu_id = str(row.get("id") or "")
            gpu_name = str(row.get("displayName") or native_gpu_id)
            vram_gb = _float(row.get("memoryInGb"))
            gpu_model = canonical_gpu_model(
                gpu_name, vram_gb * 1024 if vram_gb is not None else None
            )
            if not native_gpu_id or not gpu_model:
                continue
            available_locations = locations.get(native_gpu_id, ())
            for cloud_type, enabled_key, price_key in (
                ("secure", "secureCloud", "securePrice"),
                ("community", "communityCloud", "communityPrice"),
            ):
                price = _float(row.get(price_key))
                if not row.get(enabled_key) or price is None or price <= 0:
                    continue
                location_ids = tuple(item[0] for item in available_locations)
                best_stock = _best_stock(item[2] for item in available_locations)
                native_offer_id = f"{native_gpu_id}:{cloud_type}"
                offers.append(
                    LiveOffer(
                        offer_id=_offer_id("runpod", native_offer_id),
                        provider="runpod",
                        native_offer_id=native_offer_id,
                        offer_kind="deployment_requirement",
                        observed_at=observed_at,
                        gpu_model=gpu_model,
                        gpu_name=gpu_name,
                        gpu_count=1,
                        vram_gb=vram_gb,
                        price_usd_gpu_hr=price,
                        price_usd_instance_hr=price,
                        cloud_type=cloud_type,
                        location=_location_summary(available_locations),
                        location_ids=location_ids,
                        stock_status=best_stock,
                        available=bool(location_ids) and _has_stock(best_stock),
                        selection={
                            "provider": "runpod",
                            "operation": "create_pod",
                            "gpuTypeIds": [native_gpu_id],
                            "gpuCount": 1,
                            "cloudType": cloud_type.upper(),
                            "dataCenterIds": list(location_ids),
                        },
                    )
                )
        return offers

    def _verda_offers(self, observed_at: datetime) -> list[LiveOffer]:
        if (
            not self.verda_access_token
            and not (self.verda_client_id and self.verda_client_secret)
            and self._verda_client is None
        ):
            raise _CredentialsRequired(
                "Verda live availability requires VERDA_CLIENT_ID and "
                "VERDA_CLIENT_SECRET, or VERDA_ACCESS_TOKEN."
            )
        if self._verda_client is None:
            try:
                from ..prices.providers.verda import VerdaClient
            except ImportError as exc:
                raise LiveOfferError(
                    "Live offers require: uv sync --extra live"
                ) from exc
            self._verda_client = VerdaClient(
                client_id=self.verda_client_id,
                client_secret=self.verda_client_secret,
                access_token=self.verda_access_token,
            )
        fetched = self._verda_client.fetch_catalog()
        if fetched.availability is None:
            raise _CredentialsRequired(
                "Verda credentials are valid for pricing only, not live availability."
            )
        locations_by_type = _verda_locations(fetched.availability)
        offers: list[LiveOffer] = []
        for row in fetched.instance_types:
            native_type = str(row.get("instance_type") or row.get("id") or "")
            locations = locations_by_type.get(native_type, ())
            price = _float(row.get("price_per_hour"))
            currency = str(row.get("currency") or "").upper()
            if not native_type or not locations or price is None or price <= 0:
                continue
            if currency != "USD":
                continue
            gpu = row.get("gpu") if isinstance(row.get("gpu"), Mapping) else {}
            memory = (
                row.get("gpu_memory")
                if isinstance(row.get("gpu_memory"), Mapping)
                else {}
            )
            gpu_name = str(
                row.get("name") or row.get("display_name") or row.get("model") or ""
            )
            gpu_count = _integer(gpu.get("number_of_gpus")) or 1
            vram_gb = _float(memory.get("size_in_gigabytes"))
            gpu_model = canonical_gpu_model(
                gpu_name, vram_gb * 1024 if vram_gb is not None else None
            )
            if not gpu_model:
                continue
            if gpu_count > 1:
                gpu_model = f"{gpu_model}_x{gpu_count}"
            for location in locations:
                native_offer_id = f"{native_type}:{location}"
                offers.append(
                    LiveOffer(
                        offer_id=_offer_id("verda", native_offer_id),
                        provider="verda",
                        native_offer_id=native_offer_id,
                        offer_kind="instance_location",
                        observed_at=observed_at,
                        gpu_model=gpu_model,
                        gpu_name=gpu_name,
                        gpu_count=gpu_count,
                        vram_gb=vram_gb,
                        price_usd_gpu_hr=price / gpu_count,
                        price_usd_instance_hr=price,
                        cloud_type="secure",
                        location=location,
                        location_ids=(location,),
                        stock_status="available",
                        available=True,
                        selection={
                            "provider": "verda",
                            "operation": "create_instance",
                            "instance_type": native_type,
                            "location_code": location,
                        },
                    )
                )
        return offers


class _CredentialsRequired(RuntimeError):
    pass


def _provider_names(providers: Iterable[str] | None) -> tuple[ProviderName, ...]:
    values = tuple(dict.fromkeys(value.lower() for value in (providers or ())))
    if not values:
        return ("runpod", "verda")
    unknown = sorted(set(values) - {"runpod", "verda"})
    if unknown:
        raise LiveOfferError(f"Unknown live provider: {', '.join(unknown)}")
    return cast(tuple[ProviderName, ...], values)


def _offer_id(provider: ProviderName, native_offer_id: str) -> str:
    digest = hashlib.sha256(native_offer_id.encode("utf-8")).hexdigest()[:12]
    return f"{provider}:{digest}"


def _matches_gpu(gpu_model: str, selector: str | None) -> bool:
    if not selector:
        return True
    candidate = gpu_model.upper().replace("-", "_")
    requested = selector.upper().replace("-", "_")
    return candidate == requested or candidate.startswith(f"{requested}_")


def _runpod_locations(
    data_centers: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[tuple[str, str, str], ...]]:
    result: dict[str, list[tuple[str, str, str]]] = {}
    for center in data_centers:
        center_id = str(center.get("id") or "")
        if not center_id:
            continue
        name = str(center.get("name") or center.get("location") or center_id)
        availability = center.get("gpuAvailability")
        if not isinstance(availability, list):
            continue
        for row in availability:
            if not isinstance(row, Mapping):
                continue
            gpu_type_id = str(row.get("gpuTypeId") or "")
            stock = str(row.get("stockStatus") or "none")
            if gpu_type_id and _has_stock(stock):
                result.setdefault(gpu_type_id, []).append((center_id, name, stock))
    return {
        key: tuple(sorted(values, key=lambda item: item[0]))
        for key, values in result.items()
    }


def _verda_locations(
    availability: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for row in availability:
        location = str(row.get("location_code") or "")
        instance_types = row.get("availabilities")
        if not location or not isinstance(instance_types, list):
            continue
        for instance_type in instance_types:
            result.setdefault(str(instance_type), []).append(location)
    return {key: tuple(sorted(set(values))) for key, values in result.items()}


_STOCK_RANK = {"high": 3, "medium": 2, "low": 1}


def _has_stock(value: str) -> bool:
    return _STOCK_RANK.get(value.strip().lower(), 0) > 0


def _best_stock(values: Iterable[str]) -> str:
    return max(
        values,
        key=lambda value: _STOCK_RANK.get(value.lower(), 0),
        default="none",
    )


def _location_summary(locations: tuple[tuple[str, str, str], ...]) -> str:
    if not locations:
        return "none"
    if len(locations) == 1:
        return locations[0][1]
    return f"{len(locations)} datacenters"


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
