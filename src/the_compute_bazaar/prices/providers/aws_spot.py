"""Current AWS EC2 Spot price observations for frontier GPU instances."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..schemas import GpuOffer


DEFAULT_AWS_SPOT_REGIONS = (
    "us-east-1",
    "us-east-2",
    "us-west-2",
    "ca-central-1",
    "eu-west-1",
    "eu-west-2",
    "eu-central-1",
    "eu-north-1",
    "ap-south-1",
    "ap-northeast-1",
    "ap-northeast-2",
    "ap-southeast-1",
    "ap-southeast-2",
)

AWS_FRONTIER_INSTANCE_TYPES: dict[str, dict[str, Any]] = {
    "p5.4xlarge": {
        "gpu_name": "NVIDIA H100",
        "gpu_model": "H100_80GB",
        "gpu_count": 1,
        "vram_gb": 80,
    },
    "p5.48xlarge": {
        "gpu_name": "NVIDIA H100",
        "gpu_model": "H100_80GB",
        "gpu_count": 8,
        "vram_gb": 80,
    },
    "p5e.48xlarge": {
        "gpu_name": "NVIDIA H200",
        "gpu_model": "H200_141GB",
        "gpu_count": 8,
        "vram_gb": 141,
    },
    "p5en.48xlarge": {
        "gpu_name": "NVIDIA H200",
        "gpu_model": "H200_141GB",
        "gpu_count": 8,
        "vram_gb": 141,
    },
    "p6-b200.48xlarge": {
        "gpu_name": "NVIDIA B200",
        "gpu_model": "B200_180GB",
        "gpu_count": 8,
        "vram_gb": 180,
    },
    "p6-b300.48xlarge": {
        "gpu_name": "NVIDIA B300",
        "gpu_model": "B300_288GB",
        "gpu_count": 8,
        "vram_gb": 288,
    },
}


@dataclass(frozen=True)
class AwsSpotFetch:
    raw_payload: dict[str, Any]
    prices: list[dict[str, Any]]


class AwsSpotClient:
    def __init__(
        self,
        *,
        session: Any | None = None,
        regions: Sequence[str] | None = None,
    ) -> None:
        if session is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("AWS Spot ingestion requires boto3") from exc
            session = boto3.Session(
                profile_name=os.getenv("AWS_PROFILE") or None,
                region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
            )
        self.session = session
        self.regions = tuple(regions or DEFAULT_AWS_SPOT_REGIONS)

    def fetch_current_prices(self, *, observed_at: datetime) -> AwsSpotFetch:
        """Fetch one current Spot price per region/AZ/instance type."""
        region_results: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        successful_regions = 0

        for region in self.regions:
            try:
                client = self.session.client("ec2", region_name=region)
                response = client.describe_spot_price_history(
                    InstanceTypes=list(AWS_FRONTIER_INSTANCE_TYPES),
                    ProductDescriptions=["Linux/UNIX"],
                    StartTime=observed_at,
                    EndTime=observed_at,
                    MaxResults=1000,
                )
                prices = [
                    {**dict(row), "_region": region}
                    for row in response.get("SpotPriceHistory", [])
                    if isinstance(row, Mapping)
                ]
                rows.extend(prices)
                successful_regions += 1
                region_results.append(
                    {
                        "region": region,
                        "request": {
                            "instance_types": list(AWS_FRONTIER_INSTANCE_TYPES),
                            "product_descriptions": ["Linux/UNIX"],
                            "observed_at": observed_at,
                        },
                        "response": response,
                        "extracted_price_count": len(prices),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - retain partial regional coverage.
                region_results.append(
                    {
                        "region": region,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "extracted_price_count": 0,
                    }
                )

        if successful_regions == 0:
            errors = "; ".join(
                f"{row['region']}: {row.get('error', 'unknown error')}"
                for row in region_results
            )
            raise RuntimeError(
                f"AWS Spot price collection failed in every configured region: {errors}"
            )

        prices = _latest_unique_prices(rows)
        return AwsSpotFetch(
            raw_payload={
                "mode": "current_spot_price_snapshot",
                "observed_at": observed_at,
                "regions": region_results,
                "successful_region_count": successful_regions,
                "region_count": len(self.regions),
                "price_count": len(prices),
                "prices": prices,
            },
            prices=prices,
        )


def normalize_spot_prices(
    prices: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_instance_types: list[str] = []

    for entry in prices:
        instance_type = str(entry.get("InstanceType") or "")
        spec = AWS_FRONTIER_INSTANCE_TYPES.get(instance_type)
        if spec is None:
            if instance_type:
                unknown_instance_types.append(instance_type)
            continue

        price = _float_or_none(entry.get("SpotPrice"))
        if price is None or price <= 0:
            continue

        region = str(entry.get("_region") or "")
        availability_zone = str(entry.get("AvailabilityZone") or "")
        gpu_count = int(spec["gpu_count"])
        normalized.append(
            GpuOffer(
                provider="aws_spot",
                source_offer_id=f"{region}:{availability_zone}:{instance_type}:linux-unix",
                observed_at=observed_at,
                gpu_raw_name=str(spec["gpu_name"]),
                gpu_model=str(spec["gpu_model"])
                if gpu_count == 1
                else f"{spec['gpu_model']}_x{gpu_count}",
                gpu_count=gpu_count,
                vram_gb=float(spec["vram_gb"]),
                price_usd_hr=price,
                country=None,
                region=", ".join(part for part in (region, availability_zone) if part)
                or None,
                is_spot=True,
                is_secure=True,
                availability_status="spot_price_observed",
                raw_ref=raw_ref,
                metadata={
                    "instance_type": instance_type,
                    "availability_zone": availability_zone,
                    "product_description": entry.get("ProductDescription"),
                    "price_timestamp": entry.get("Timestamp"),
                    "price_basis": "aws_ec2_spot_instance_hour",
                    "capacity_confirmed": False,
                },
            )
        )

    return normalized, sorted(set(unknown_instance_types))


def _latest_unique_prices(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        clean = dict(row)
        key = (
            str(clean.get("_region") or ""),
            str(clean.get("AvailabilityZone") or ""),
            str(clean.get("InstanceType") or ""),
            str(clean.get("ProductDescription") or ""),
        )
        current = latest.get(key)
        if current is None or str(clean.get("Timestamp") or "") > str(
            current.get("Timestamp") or ""
        ):
            latest[key] = clean
    return [latest[key] for key in sorted(latest)]


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
