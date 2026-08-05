"""Canonical registry for market provider ingestion."""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal, Mapping

from .pipeline import (
    ingest_akash,
    ingest_aws_spot,
    ingest_azure_retail,
    ingest_clore,
    ingest_cloud_gpu_prices,
    ingest_digitalocean,
    ingest_getdeploying,
    ingest_gpus_io,
    ingest_gridstackhub,
    ingest_hyperstack,
    ingest_inference_sh,
    ingest_jarvislabs,
    ingest_lambda_cloud,
    ingest_lium,
    ingest_oracle_cloud,
    ingest_ovhcloud,
    ingest_prime_intellect,
    ingest_runpod,
    ingest_scaleway,
    ingest_sesterce,
    ingest_shadeform,
    ingest_spheron,
    ingest_tensordock,
    ingest_thunder_compute,
    ingest_verda,
    ingest_vast,
    ingest_vultr,
)

if TYPE_CHECKING:
    from .pipeline import IngestResult


ProviderKind = Literal["marketplace", "cloud", "aggregator"]
ObservationKind = Literal[
    "live_offer",
    "published_rate",
    "spot_price",
    "mixed_advertised_price",
    "reference_price",
]
ProviderIngester = Callable[..., "IngestResult"]


@dataclass(frozen=True)
class ProviderCredential:
    env_name: str
    description: str
    required_for_schedule: bool = False


@dataclass(frozen=True)
class ProviderRunContext:
    market_run_id: str
    raw_root: str
    lake_root: str
    automq_bootstrap_servers: str | None
    automq_config: Mapping[str, str]
    topic_prefix: str
    dry_run: bool
    provider_options: Mapping[str, Mapping[str, Any]]

    def common_kwargs(self, provider: str) -> dict[str, Any]:
        return {
            "raw_root": self.raw_root,
            "lake_root": self.lake_root,
            "automq_bootstrap_servers": self.automq_bootstrap_servers,
            "automq_config": dict(self.automq_config),
            "topic_prefix": self.topic_prefix,
            "dry_run": self.dry_run,
            "run_id": f"{provider}-{self.market_run_id}",
            "trace_id": self.market_run_id,
        }


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    ingester: ProviderIngester
    provider_kind: ProviderKind
    observation_kind: ObservationKind
    default_enabled: bool = True
    credentials: tuple[ProviderCredential, ...] = ()
    default_options: Mapping[str, Any] | None = None

    def is_enabled(self) -> bool:
        return self.default_enabled or (
            bool(self.credentials)
            and all(os.getenv(credential.env_name) for credential in self.credentials)
        )

    def ingest(self, context: ProviderRunContext) -> IngestResult:
        common_kwargs = context.common_kwargs(self.name)
        options = deepcopy(dict(self.default_options or {}))
        options.update(dict(context.provider_options.get(self.name, {})))
        overlap = set(common_kwargs) & set(options)
        if overlap:
            raise ValueError(
                f"Provider {self.name} options override run context: "
                f"{', '.join(sorted(overlap))}"
            )
        result = self.ingester(**common_kwargs, **options)
        if result.provider != self.name:
            raise RuntimeError(
                f"Provider adapter {self.name} returned data for {result.provider}"
            )
        return result


PROVIDERS = (
    ProviderDefinition(
        "vast",
        ingest_vast,
        "marketplace",
        "live_offer",
        credentials=(ProviderCredential("VAST_API_KEY", "Vast API key", True),),
    ),
    ProviderDefinition(
        "lium",
        ingest_lium,
        "marketplace",
        "live_offer",
        credentials=(ProviderCredential("LIUM_API_KEY", "Lium API key", True),),
        default_options={"query": {"size": 200}, "paginate": True, "max_pages": 10},
    ),
    ProviderDefinition(
        "spheron", ingest_spheron, "marketplace", "mixed_advertised_price"
    ),
    ProviderDefinition("inference_sh", ingest_inference_sh, "cloud", "published_rate"),
    ProviderDefinition(
        "gridstackhub", ingest_gridstackhub, "aggregator", "reference_price"
    ),
    ProviderDefinition(
        "cloud_gpu_prices",
        ingest_cloud_gpu_prices,
        "aggregator",
        "reference_price",
    ),
    ProviderDefinition(
        "thunder_compute", ingest_thunder_compute, "cloud", "published_rate"
    ),
    ProviderDefinition("vultr", ingest_vultr, "cloud", "mixed_advertised_price"),
    ProviderDefinition("scaleway", ingest_scaleway, "cloud", "published_rate"),
    ProviderDefinition("oracle_cloud", ingest_oracle_cloud, "cloud", "published_rate"),
    ProviderDefinition("ovhcloud", ingest_ovhcloud, "cloud", "published_rate"),
    ProviderDefinition("akash", ingest_akash, "marketplace", "live_offer"),
    ProviderDefinition("aws_spot", ingest_aws_spot, "cloud", "spot_price"),
    ProviderDefinition("azure", ingest_azure_retail, "cloud", "mixed_advertised_price"),
    ProviderDefinition("runpod", ingest_runpod, "marketplace", "live_offer"),
    ProviderDefinition(
        "verda",
        ingest_verda,
        "cloud",
        "mixed_advertised_price",
        credentials=(
            ProviderCredential("VERDA_CLIENT_ID", "Verda OAuth client ID"),
            ProviderCredential("VERDA_CLIENT_SECRET", "Verda OAuth client secret"),
        ),
    ),
    ProviderDefinition(
        "clore",
        ingest_clore,
        "marketplace",
        "live_offer",
        default_enabled=False,
        credentials=(ProviderCredential("CLORE_API_KEY", "Clore API key"),),
    ),
    ProviderDefinition(
        "prime_intellect",
        ingest_prime_intellect,
        "marketplace",
        "live_offer",
        default_enabled=False,
        credentials=(
            ProviderCredential(
                "PRIME_INTELLECT_API_KEY", "Prime Intellect availability API key"
            ),
        ),
    ),
    ProviderDefinition(
        "shadeform",
        ingest_shadeform,
        "aggregator",
        "live_offer",
        default_enabled=False,
        credentials=(ProviderCredential("SHADEFORM_API_KEY", "Shadeform API key"),),
    ),
    ProviderDefinition(
        "sesterce",
        ingest_sesterce,
        "cloud",
        "published_rate",
        default_enabled=False,
        credentials=(ProviderCredential("SESTERCE_API_KEY", "Sesterce API key"),),
    ),
    ProviderDefinition(
        "tensordock",
        ingest_tensordock,
        "marketplace",
        "live_offer",
        default_enabled=False,
        credentials=(ProviderCredential("TENSORDOCK_API_KEY", "TensorDock API key"),),
    ),
    ProviderDefinition(
        "hyperstack",
        ingest_hyperstack,
        "cloud",
        "mixed_advertised_price",
        default_enabled=False,
        credentials=(ProviderCredential("HYPERSTACK_API_KEY", "Hyperstack API key"),),
    ),
    ProviderDefinition(
        "lambda",
        ingest_lambda_cloud,
        "cloud",
        "published_rate",
        default_enabled=False,
        credentials=(
            ProviderCredential("LAMBDA_CLOUD_API_KEY", "Lambda Cloud API key"),
        ),
    ),
    ProviderDefinition(
        "digitalocean",
        ingest_digitalocean,
        "cloud",
        "published_rate",
        default_enabled=False,
        credentials=(
            ProviderCredential("DIGITALOCEAN_API_TOKEN", "DigitalOcean API token"),
        ),
    ),
    ProviderDefinition(
        "gpus_io",
        ingest_gpus_io,
        "aggregator",
        "live_offer",
        default_enabled=False,
        credentials=(ProviderCredential("GPUS_IO_API_KEY", "GPUs.io API key"),),
    ),
    ProviderDefinition(
        "getdeploying",
        ingest_getdeploying,
        "aggregator",
        "reference_price",
        default_enabled=False,
        credentials=(
            ProviderCredential("GETDEPLOYING_API_KEY", "GetDeploying API key"),
        ),
    ),
    ProviderDefinition(
        "jarvislabs",
        ingest_jarvislabs,
        "cloud",
        "mixed_advertised_price",
        default_enabled=False,
        credentials=(ProviderCredential("JL_API_KEY", "JarvisLabs API key"),),
    ),
)

PROVIDER_BY_NAME = {provider.name: provider for provider in PROVIDERS}


def enabled_provider_names() -> list[str]:
    return [provider.name for provider in PROVIDERS if provider.is_enabled()]


def get_provider(name: str) -> ProviderDefinition:
    try:
        return PROVIDER_BY_NAME[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported market provider: {name}") from exc


def provider_credentials() -> tuple[ProviderCredential, ...]:
    credentials: dict[str, ProviderCredential] = {}
    for provider in PROVIDERS:
        for credential in provider.credentials:
            credentials[credential.env_name] = credential
    return tuple(credentials[name] for name in sorted(credentials))


def provider_catalog_rows(names: list[str]) -> list[dict[str, str]]:
    return [
        {
            "provider": provider.name,
            "provider_kind": provider.provider_kind,
            "observation_kind": provider.observation_kind,
        }
        for name in names
        for provider in [get_provider(name)]
    ]
