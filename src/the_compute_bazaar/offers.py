"""Direct provider observations used for selection and preflight."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .prices.events import new_run_id
from .prices.schemas import OfferObservation, to_jsonable

if TYPE_CHECKING:
    from .operations import OperationalLedger


class OfferServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    status: str
    offer_count: int = 0
    message: str | None = None


@dataclass(frozen=True)
class OfferBatch:
    batch_id: str
    observed_at: datetime
    observations: tuple[OfferObservation, ...]
    providers: tuple[ProviderStatus, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "observed_at": self.observed_at,
            "providers": [to_jsonable(status) for status in self.providers],
            "rows": [display_row(row) for row in self.observations],
        }


class OfferService:
    def __init__(
        self,
        *,
        runpod_api_key: str | None = None,
        verda_client_id: str | None = None,
        verda_client_secret: str | None = None,
        verda_access_token: str | None = None,
        runpod_client: Any | None = None,
        verda_client: Any | None = None,
        ledger: OperationalLedger | None = None,
    ) -> None:
        self.runpod_api_key = runpod_api_key
        self.verda_client_id = verda_client_id
        self.verda_client_secret = verda_client_secret
        self.verda_access_token = verda_access_token
        self._runpod_client = runpod_client
        self._verda_client = verda_client
        self.ledger = ledger

    @classmethod
    def from_environment(cls, *, record: bool = True) -> OfferService:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        ledger = None
        if record:
            from .operations import OperationalLedger

            ledger = OperationalLedger()
        return cls(
            runpod_api_key=os.getenv("RUNPOD_API_KEY"),
            verda_client_id=os.getenv("VERDA_CLIENT_ID"),
            verda_client_secret=os.getenv("VERDA_CLIENT_SECRET"),
            verda_access_token=os.getenv("VERDA_ACCESS_TOKEN"),
            ledger=ledger,
        )

    def list_offers(
        self,
        *,
        providers: Iterable[str] | None = None,
        gpu_model: str | None = None,
        include_unavailable: bool = False,
        limit: int = 100,
        purpose: str = "interactive",
    ) -> OfferBatch:
        if purpose not in {"interactive", "preflight"}:
            raise ValueError("Direct offer reads must be interactive or preflight")
        observed_at = datetime.now(timezone.utc)
        batch_id = new_run_id(purpose)
        selected = _provider_names(providers)
        query_scope = {
            "providers": list(selected),
            "gpu_model": gpu_model,
        }
        observations: list[OfferObservation] = []
        displayed: list[OfferObservation] = []
        statuses: list[ProviderStatus] = []
        for provider in selected:
            try:
                rows = (
                    self._runpod_observations(
                        observed_at, batch_id, purpose, query_scope
                    )
                    if provider == "runpod"
                    else self._verda_observations(
                        observed_at, batch_id, purpose, query_scope
                    )
                )
            except _CredentialsRequired as exc:
                statuses.append(
                    ProviderStatus(provider, "credentials_required", message=str(exc))
                )
                continue
            except (OSError, RuntimeError, ValueError) as exc:
                statuses.append(ProviderStatus(provider, "error", message=str(exc)))
                continue
            matched = [row for row in rows if _matches_gpu(row.gpu_model, gpu_model)]
            observations.extend(matched)
            displayed.extend(
                row for row in matched if include_unavailable or row.available
            )
            statuses.append(ProviderStatus(provider, "ok", len(matched)))

        observations.sort(key=_offer_sort_key)
        displayed.sort(key=_offer_sort_key)
        complete = OfferBatch(
            batch_id=batch_id,
            observed_at=observed_at,
            observations=tuple(observations),
            providers=tuple(statuses),
        )
        if self.ledger:
            self.ledger.record_offer_observations(complete)
        return replace(complete, observations=tuple(displayed[:limit]))

    def inspect(self, offer_id: str) -> OfferObservation:
        provider = offer_id.partition(":")[0].lower()
        if provider not in {"runpod", "verda"}:
            raise OfferServiceError(f"Unknown offer: {offer_id}")
        result = self.list_offers(
            providers=[provider],
            include_unavailable=True,
            limit=1000,
            purpose="preflight",
        )
        for observation in result.observations:
            if observation.source_offer_id == offer_id:
                return observation
        status = result.providers[0]
        if status.status != "ok":
            raise OfferServiceError(status.message or f"{provider} is unavailable")
        raise OfferServiceError(
            f"Offer {offer_id} is no longer visible. Run: compute-bazaar offers list"
        )

    def _runpod_observations(
        self,
        observed_at: datetime,
        batch_id: str,
        purpose: str,
        query_scope: dict[str, Any],
    ) -> list[OfferObservation]:
        if self._runpod_client is None:
            try:
                from .prices.providers.runpod import RunpodClient
            except ImportError as exc:
                raise OfferServiceError(
                    "Provider reads require: uv sync --extra providers"
                ) from exc
            self._runpod_client = RunpodClient(api_key=self.runpod_api_key)
        from .prices.providers.runpod import normalize_live_market

        fetched = self._runpod_client.fetch_live_market()
        return normalize_live_market(
            fetched.gpu_types,
            fetched.data_centers,
            observed_at=observed_at,
            batch_id=batch_id,
            purpose=purpose,
            query_scope=query_scope,
        )

    def _verda_observations(
        self,
        observed_at: datetime,
        batch_id: str,
        purpose: str,
        query_scope: dict[str, Any],
    ) -> list[OfferObservation]:
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
            from .prices.providers.verda import VerdaClient

            self._verda_client = VerdaClient(
                client_id=self.verda_client_id,
                client_secret=self.verda_client_secret,
                access_token=self.verda_access_token,
            )
        from .prices.providers.verda import normalize_live_catalog

        fetched = self._verda_client.fetch_catalog()
        if fetched.availability is None:
            raise _CredentialsRequired(
                "Verda credentials are valid for pricing only, not live availability."
            )
        return normalize_live_catalog(
            fetched.instance_types,
            fetched.availability,
            observed_at=observed_at,
            batch_id=batch_id,
            purpose=purpose,
            query_scope=query_scope,
        )


class _CredentialsRequired(RuntimeError):
    pass


def display_row(observation: OfferObservation) -> dict[str, Any]:
    return {
        "observation_id": observation.observation_id,
        "offer_id": observation.source_offer_id,
        "provider": observation.provider,
        "gpu_model": observation.gpu_model,
        "gpu_name": observation.gpu_raw_name,
        "gpu_count": observation.gpu_count,
        "vram_gb": observation.vram_gb,
        "price_usd_gpu_hr": observation.price_usd_gpu_hr,
        "price_usd_instance_hr": observation.price_usd_instance_hr,
        "cloud_type": observation.cloud_type,
        "location": observation.location,
        "location_count": len(observation.location_ids),
        "stock_status": observation.stock_status_value,
        "available": observation.available,
        "observed_at": observation.observed_at,
    }


def _provider_names(providers: Iterable[str] | None) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(value.lower() for value in (providers or ())))
    if not values:
        return ("runpod", "verda")
    unknown = sorted(set(values) - {"runpod", "verda"})
    if unknown:
        raise OfferServiceError(f"Unknown provider: {', '.join(unknown)}")
    return values


def _matches_gpu(gpu_model: str, selector: str | None) -> bool:
    if not selector:
        return True
    candidate = gpu_model.upper().replace("-", "_")
    requested = selector.upper().replace("-", "_")
    return candidate == requested or candidate.startswith(f"{requested}_")


def _offer_sort_key(row: OfferObservation) -> tuple[bool, float, str, str]:
    return (
        not row.available,
        row.price_usd_gpu_hr,
        row.provider,
        row.source_offer_id,
    )
