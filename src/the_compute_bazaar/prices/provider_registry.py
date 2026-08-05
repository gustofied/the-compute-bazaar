"""Canonical registry for market provider ingestion."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

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

ProviderIngester = Callable[..., Any]


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    ingester: ProviderIngester
    default_enabled: bool = True
    credential_envs: tuple[str, ...] = ()

    def is_enabled(self) -> bool:
        return self.default_enabled or all(os.getenv(name) for name in self.credential_envs)


PROVIDERS = (
    ProviderDefinition("vast", ingest_vast),
    ProviderDefinition("lium", ingest_lium),
    ProviderDefinition("spheron", ingest_spheron),
    ProviderDefinition("inference_sh", ingest_inference_sh),
    ProviderDefinition("gridstackhub", ingest_gridstackhub),
    ProviderDefinition("cloud_gpu_prices", ingest_cloud_gpu_prices),
    ProviderDefinition("thunder_compute", ingest_thunder_compute),
    ProviderDefinition("vultr", ingest_vultr),
    ProviderDefinition("scaleway", ingest_scaleway),
    ProviderDefinition("oracle_cloud", ingest_oracle_cloud),
    ProviderDefinition("ovhcloud", ingest_ovhcloud),
    ProviderDefinition("akash", ingest_akash),
    ProviderDefinition("aws_spot", ingest_aws_spot),
    ProviderDefinition("azure", ingest_azure_retail),
    ProviderDefinition("runpod", ingest_runpod),
    ProviderDefinition("verda", ingest_verda),
    ProviderDefinition(
        "clore", ingest_clore, default_enabled=False, credential_envs=("CLORE_API_KEY",)
    ),
    ProviderDefinition(
        "prime_intellect",
        ingest_prime_intellect,
        default_enabled=False,
        credential_envs=("PRIME_INTELLECT_API_KEY",),
    ),
    ProviderDefinition(
        "shadeform",
        ingest_shadeform,
        default_enabled=False,
        credential_envs=("SHADEFORM_API_KEY",),
    ),
    ProviderDefinition(
        "sesterce",
        ingest_sesterce,
        default_enabled=False,
        credential_envs=("SESTERCE_API_KEY",),
    ),
    ProviderDefinition(
        "tensordock",
        ingest_tensordock,
        default_enabled=False,
        credential_envs=("TENSORDOCK_API_KEY",),
    ),
    ProviderDefinition(
        "hyperstack",
        ingest_hyperstack,
        default_enabled=False,
        credential_envs=("HYPERSTACK_API_KEY",),
    ),
    ProviderDefinition(
        "lambda",
        ingest_lambda_cloud,
        default_enabled=False,
        credential_envs=("LAMBDA_CLOUD_API_KEY",),
    ),
    ProviderDefinition(
        "digitalocean",
        ingest_digitalocean,
        default_enabled=False,
        credential_envs=("DIGITALOCEAN_API_TOKEN",),
    ),
    ProviderDefinition(
        "gpus_io",
        ingest_gpus_io,
        default_enabled=False,
        credential_envs=("GPUS_IO_API_KEY",),
    ),
    ProviderDefinition(
        "getdeploying",
        ingest_getdeploying,
        default_enabled=False,
        credential_envs=("GETDEPLOYING_API_KEY",),
    ),
    ProviderDefinition(
        "jarvislabs",
        ingest_jarvislabs,
        default_enabled=False,
        credential_envs=("JL_API_KEY",),
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
