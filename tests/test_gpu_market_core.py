from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from the_compute_bazaar.prices.gold import (
    build_gold_market_tables,
    export_gold_dashboard_snapshot,
    query_gold_benchmark_constituents,
    query_gold_benchmark_history,
    query_gold_benchmark_values,
    query_gold_featured_index,
    query_gold_index_constituents,
    query_gold_index_history,
    query_gold_listings,
    query_gold_market_state,
    query_gold_market_state_history,
    query_gold_prime_frontier_offer_market,
    query_gold_prime_h100_offer_reference,
    query_gold_provider_comparison,
    read_latest_gold_manifest,
)
from the_compute_bazaar.prices.coverage import query_frontier_coverage
from the_compute_bazaar.prices.market_run import (
    default_market_providers,
    list_market_runs,
    read_latest_market_run,
    run_market_hourly,
    write_market_run_manifest,
)
from the_compute_bazaar.prices.normalize import canonical_gpu_model
from the_compute_bazaar.prices.market_state import (
    normalize_akash_market_state,
    normalize_clore_market_state,
    normalize_prime_market_state,
    normalize_runpod_market_state,
)
from the_compute_bazaar.prices.operator import (
    list_operator_queries,
    preview_operator_ref,
    run_operator_query,
    run_operator_sql,
    trace_operator_row,
)
from the_compute_bazaar.prices.providers.lium import LiumClient, normalize_executor
from the_compute_bazaar.prices.pipeline import ingest_rate_card
from the_compute_bazaar.prices.providers.akash import AkashClient, normalize_gpu_prices
from the_compute_bazaar.prices.providers.aws_spot import (
    AwsSpotClient,
    normalize_spot_prices,
)
from the_compute_bazaar.prices.providers.azure_retail import (
    AzureRetailClient,
    normalize_retail_prices,
)
from the_compute_bazaar.prices.providers.clore import CloreClient, normalize_servers
from the_compute_bazaar.prices.providers.cloud_gpu_prices import (
    CloudGpuPricesClient,
    normalize_external_offerings as normalize_cloud_gpu_prices_external_offerings,
)
from the_compute_bazaar.prices.providers.digitalocean import (
    DigitalOceanClient,
    normalize_sizes as normalize_digitalocean_sizes,
)
from the_compute_bazaar.prices.providers.gpus_io import (
    GpusIoClient,
    normalize_prices as normalize_gpus_io_prices,
)
from the_compute_bazaar.prices.providers.getdeploying import (
    GetDeployingClient,
    normalize_external_offerings as normalize_getdeploying_external_offerings,
)
from the_compute_bazaar.prices.providers.gridstackhub import (
    GridStackHubClient,
    normalize_reference_prices as normalize_gridstackhub_reference_prices,
)
from the_compute_bazaar.prices.providers.hyperstack import (
    HyperstackClient,
    normalize_stock,
)
from the_compute_bazaar.prices.providers.inference_sh import (
    InferenceShClient,
    normalize_instance_types as normalize_inference_sh_instance_types,
)
from the_compute_bazaar.prices.providers.jarvislabs import (
    JarvisLabsClient,
    normalize_gpu_availability as normalize_jarvislabs_availability,
)
from the_compute_bazaar.prices.providers.lambda_cloud import (
    LambdaCloudClient,
    normalize_instance_types as normalize_lambda_instance_types,
)
from the_compute_bazaar.prices.providers.oracle_cloud import (
    OracleCloudClient,
    OracleGpuSku,
    normalize_gpu_products as normalize_oracle_gpu_products,
)
from the_compute_bazaar.prices.providers.ovhcloud import (
    OvhCloudClient,
    normalize_gpu_plans as normalize_ovhcloud_gpu_plans,
)
from the_compute_bazaar.prices.providers.prime_intellect import (
    PrimeIntellectClient,
    normalize_availability,
)
from the_compute_bazaar.prices.providers.rate_cards import rate_card_providers
from the_compute_bazaar.prices.providers.runpod import RunpodClient, normalize_gpu_types
from the_compute_bazaar.prices.providers.scaleway import (
    ScalewayClient,
    normalize_gpu_products as normalize_scaleway_gpu_products,
)
from the_compute_bazaar.prices.providers.sesterce import (
    normalize_offers as normalize_sesterce_offers,
)
from the_compute_bazaar.prices.providers.shadeform import normalize_instance_types
from the_compute_bazaar.prices.providers.spheron import (
    SpheronClient,
    normalize_offers as normalize_spheron_offers,
)
from the_compute_bazaar.prices.providers.tensordock import (
    TensorDockClient,
    normalize_hostnodes,
)
from the_compute_bazaar.prices.providers.thunder_compute import (
    ThunderComputeClient,
    normalize_catalog as normalize_thunder_catalog,
)
from the_compute_bazaar.prices.providers.verda import (
    VerdaClient,
    normalize_instance_catalog,
)
from the_compute_bazaar.prices.providers.vast import (
    VastClient,
    default_market_query,
    default_market_segments,
)
from the_compute_bazaar.prices.providers.vultr import (
    VultrClient,
    normalize_gpu_plans as normalize_vultr_gpu_plans,
)
from the_compute_bazaar.prices.schemas import ComputeMarketState, GpuOffer
from the_compute_bazaar.prices.storage import (
    read_json,
    write_json,
    write_offers_parquet,
    write_parquet_rows,
)


OBSERVED_AT = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)


class GpuNormalizationTests(unittest.TestCase):
    def test_lium_executor_normalizes_price_per_gpu_to_total_offer_price(self) -> None:
        offer = normalize_executor(
            {
                "id": "lium-1",
                "machine_name": "NVIDIA H100",
                "price_per_gpu": 1.25,
                "available_gpu_count": 2,
                "gpu_count": 2,
                "tier": "secure",
                "location": {
                    "country": "Finland",
                    "city": "Helsinki",
                    "region_name": "Uusimaa",
                },
                "specs": {
                    "gpu": {
                        "count": 2,
                        "details": [{"name": "NVIDIA H100", "capacity": 81920}],
                    }
                },
            },
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/lium.json",
        )

        self.assertIsNotNone(offer)
        assert offer is not None
        self.assertEqual(offer.provider, "lium")
        self.assertEqual(offer.gpu_model, "H100_80GB_x2")
        self.assertEqual(offer.gpu_count, 2)
        self.assertEqual(offer.available_gpu_count, 2)
        self.assertEqual(offer.price_usd_hr, 2.5)
        self.assertEqual(offer.vram_gb, 80)
        self.assertTrue(offer.is_secure)
        self.assertEqual(offer.country, "Finland")
        self.assertEqual(offer.region, "Helsinki, Uusimaa")

    def test_provider_gpu_name_variants_share_canonical_model(self) -> None:
        self.assertEqual(
            canonical_gpu_model("NVIDIA A100-SXM4-80GB", 81920), "A100_80GB"
        )
        self.assertEqual(
            canonical_gpu_model("NVIDIA RTX PRO 6000 Blackwell Server Edition", 98304),
            "RTXPro6000B_96GB",
        )
        self.assertEqual(canonical_gpu_model("GeForce RTX 4090", 24576), "RTX4090_24GB")
        self.assertEqual(
            canonical_gpu_model("NVIDIA RTX 6000 Ada Generation", 49152),
            "RTX6000Ada_48GB",
        )
        self.assertEqual(canonical_gpu_model("NVIDIA A800 PCIe", 81920), "A800_80GB")
        self.assertEqual(
            canonical_gpu_model("NVIDIA RTX 4090D", 24576), "RTX4090D_24GB"
        )
        self.assertEqual(canonical_gpu_model("NVIDIA Tesla T4", 16384), "T4_16GB")
        self.assertEqual(canonical_gpu_model("NVIDIA RTX A2000", 12288), "A2000_12GB")
        self.assertEqual(
            canonical_gpu_model("NVIDIA Quadro P4000", 8192), "QuadroP4000_8GB"
        )
        self.assertEqual(
            canonical_gpu_model("NVIDIA Quadro RTX 4000", 8192), "QuadroRTX4000_8GB"
        )
        self.assertEqual(canonical_gpu_model("A6000", 49152), "A6000_48GB")
        self.assertEqual(canonical_gpu_model("RTX4090", 24576), "RTX4090_24GB")
        self.assertEqual(canonical_gpu_model("RTXPro6000", 98304), "RTXPro6000B_96GB")
        self.assertEqual(canonical_gpu_model("V100_32G", 32768), "V100_32GB")
        self.assertEqual(canonical_gpu_model("A30", 24576), "A30_24GB")

    def test_lium_fetch_pages_preserves_raw_pages_and_dedupes_executors(self) -> None:
        session = _FakeSession(
            [
                {"data": [{"id": "exec-a"}, {"id": "exec-b"}]},
                {"data": [{"id": "exec-b"}, {"id": "exec-c"}]},
                {"data": []},
            ]
        )
        client = LiumClient(
            api_key="test-key", api_base="https://example.test/api", session=session
        )

        fetched = client.fetch_executor_pages(
            query={"size": 2}, paginate=True, max_pages=4
        )

        self.assertEqual(
            [row["id"] for row in fetched.executors], ["exec-a", "exec-b", "exec-c"]
        )
        self.assertEqual(fetched.raw_payload["mode"], "paginated")
        self.assertEqual(fetched.raw_payload["executor_count"], 3)
        self.assertEqual(len(fetched.raw_payload["pages"]), 3)
        self.assertEqual([call["params"]["page"] for call in session.calls], [1, 2, 3])

    def test_vast_default_market_query_uses_json_post_search(self) -> None:
        session = _FakeSession([{"offers": [{"id": 123, "gpu_name": "RTX 4090"}]}])
        client = VastClient(
            api_key="test-key", api_base="https://example.test/api/v0", session=session
        )

        payload = client.search_bundles()

        self.assertEqual(payload, {"offers": [{"id": 123, "gpu_name": "RTX 4090"}]})
        self.assertEqual(len(session.calls), 1)
        call = session.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "https://example.test/api/v0/bundles/")
        self.assertEqual(call["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(call["json"], default_market_query())

    def test_vast_segmented_market_search_preserves_raw_responses_and_dedupes(
        self,
    ) -> None:
        session = _FakeSession(
            [
                {"offers": [{"id": "broad-1", "gpu_name": "RTX 4090"}]},
                {
                    "offers": [
                        {"id": "h100-1", "gpu_name": "H100"},
                        {"id": "h200-1", "gpu_name": "H200"},
                        {"id": "b200-1", "gpu_name": "B200"},
                        {"id": "b300-1", "gpu_name": "B300"},
                    ]
                },
            ]
        )
        client = VastClient(
            api_key="test-key", api_base="https://example.test/api/v0", session=session
        )

        fetched = client.fetch_market_segments()

        self.assertEqual(
            [row["id"] for row in fetched.offers],
            ["broad-1", "h100-1", "h200-1", "b200-1", "b300-1"],
        )
        self.assertEqual(fetched.raw_payload["mode"], "segmented_market_search")
        self.assertEqual(fetched.raw_payload["segment_count"], 2)
        self.assertEqual(fetched.raw_payload["offer_count"], 5)
        self.assertEqual(
            [segment["segment"] for segment in fetched.raw_payload["segments"]],
            ["broad_market", "frontier_gpu_market"],
        )
        self.assertEqual(
            [call["json"] for call in session.calls],
            [query for _, query in default_market_segments()],
        )

    def test_aws_spot_prices_are_separate_instance_price_observations(self) -> None:
        session = _FakeBotoSession(
            {
                "us-east-1": {
                    "SpotPriceHistory": [
                        {
                            "AvailabilityZone": "us-east-1d",
                            "InstanceType": "p6-b300.48xlarge",
                            "ProductDescription": "Linux/UNIX",
                            "SpotPrice": "39.6519",
                            "Timestamp": OBSERVED_AT,
                        }
                    ]
                }
            }
        )
        fetched = AwsSpotClient(
            session=session, regions=["us-east-1"]
        ).fetch_current_prices(observed_at=OBSERVED_AT)
        offers, unknown = normalize_spot_prices(
            fetched.prices,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/aws-spot.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].gpu_model, "B300_288GB_x8")
        self.assertEqual(offers[0].gpu_count, 8)
        self.assertEqual(offers[0].price_usd_hr, 39.6519)
        self.assertEqual(offers[0].availability_status, "spot_price_observed")
        self.assertTrue(offers[0].is_spot)
        self.assertFalse(offers[0].metadata["capacity_confirmed"])

    def test_azure_retail_prices_paginate_and_keep_rate_types_separate(self) -> None:
        sku_spec = {
            "arm_sku_name": "Standard_ND128isr_NDR_GB200_v6",
            "gpu_raw_name": "NVIDIA B200 in GB200 NVL72",
            "gpu_model": "B200_180GB",
            "gpu_count": 4,
            "vram_gb": 192.0,
            "package_model": "GB200 NVL72",
        }
        linux_rate = {
            "currencyCode": "USD",
            "retailPrice": 108.16,
            "armRegionName": "westus3",
            "location": "US West 3",
            "effectiveStartDate": "2025-04-01T00:00:00Z",
            "meterId": "meter-ondemand",
            "meterName": "ND128isrNDRGB200v6",
            "productName": "Virtual Machines NDsrGB200NDRv6 Series",
            "skuName": "ND128isrNDRGB200v6",
            "serviceName": "Virtual Machines",
            "unitOfMeasure": "1 Hour",
            "type": "Consumption",
            "isPrimaryMeterRegion": True,
            "armSkuName": sku_spec["arm_sku_name"],
        }
        spot_rate = {
            **linux_rate,
            "retailPrice": 64.0,
            "meterId": "meter-spot",
            "meterName": "ND128isrNDRGB200v6 Spot",
            "skuName": "ND128isrNDRGB200v6 Spot",
        }
        session = _FakeSession(
            [
                {
                    "Items": [linux_rate],
                    "NextPageLink": "https://example.test/prices?page=2",
                    "Count": 1,
                },
                {
                    "Items": [
                        spot_rate,
                        {**linux_rate, "productName": "Virtual Machines Windows"},
                        {**linux_rate, "type": "Reservation"},
                    ],
                    "NextPageLink": None,
                    "Count": 3,
                },
            ]
        )
        fetched = AzureRetailClient(
            prices_url="https://example.test/prices",
            session=session,
        ).fetch_frontier_prices(sku_specs=[sku_spec])
        offers, unknown = normalize_retail_prices(
            fetched.prices,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/azure.json",
            sku_specs=[sku_spec],
        )

        self.assertEqual(len(fetched.prices), 4)
        self.assertEqual(fetched.raw_payload["page_count"], 2)
        self.assertEqual(session.calls[0]["params"]["$top"], 1000)
        self.assertEqual(session.calls[1]["params"], {})
        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].gpu_model, "B200_180GB_x4")
        self.assertEqual(offers[0].price_usd_hr, 108.16)
        self.assertEqual(offers[0].availability_status, "published_rate")
        self.assertEqual(offers[0].metadata["package_model"], "GB200 NVL72")
        self.assertFalse(offers[0].metadata["capacity_confirmed"])
        self.assertEqual(offers[1].availability_status, "spot_price_observed")
        self.assertTrue(offers[1].is_spot)

    def test_tensordock_keeps_live_capacity_but_marks_component_price(self) -> None:
        session = _FakeSession(
            [
                {
                    "data": {
                        "hostnodes": [
                            {
                                "id": "host-1",
                                "location_id": "loc-1",
                                "uptime_percentage": 99.9,
                                "available_resources": {
                                    "gpus": [
                                        {
                                            "v0Name": "h100-sxm5-80gb",
                                            "displayName": "H100 SXM5 80GB",
                                            "availableCount": 8,
                                            "price_per_hr": 2.2,
                                        }
                                    ]
                                },
                                "location": {
                                    "city": "Austin",
                                    "stateprovince": "Texas",
                                    "country": "United States",
                                    "organizationName": "Example DC",
                                },
                            }
                        ]
                    }
                }
            ]
        )
        fetched = TensorDockClient(
            api_key="token",
            api_base="https://example.test/api/v2",
            session=session,
        ).fetch_hostnodes()
        offers, unknown = normalize_hostnodes(
            fetched.hostnodes,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/tensordock.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].gpu_model, "H100_80GB")
        self.assertEqual(offers[0].available_gpu_count, 8)
        self.assertEqual(offers[0].price_usd_hr, 2.2)
        self.assertEqual(
            offers[0].availability_status,
            "available_component_rate",
        )
        self.assertEqual(
            session.calls[0]["headers"]["Authorization"],
            "Bearer token",
        )

    def test_inference_sh_preserves_upstream_provider_and_available_regions(
        self,
    ) -> None:
        session = _FakeSession(
            [
                [
                    {
                        "id": "lambdalabs.8x-b200",
                        "cloud": "lambdalabs",
                        "shade_instance_type": "8x B200",
                        "cloud_instance_type": "gpu_8x_b200",
                        "deployment_type": "vm",
                        "hourly_price": 3200,
                        "configuration": {
                            "gpu_type": "B200",
                            "num_gpus": 8,
                            "vram_per_gpu_in_gb": 180,
                            "vcpus": 208,
                            "memory_in_gb": 1800,
                        },
                        "availability": [
                            {"available": True, "region": "us-west-1"},
                            {"available": False, "region": "us-east-1"},
                        ],
                    }
                ]
            ]
        )
        fetched = InferenceShClient(
            api_base="https://example.test",
            session=session,
        ).fetch_instance_types()
        offers, unknown = normalize_inference_sh_instance_types(
            fetched.instance_types,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/inference-sh.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].provider, "lambda")
        self.assertEqual(offers[0].source_connector, "inference_sh")
        self.assertEqual(offers[0].gpu_model, "B200_180GB_x8")
        self.assertEqual(offers[0].available_gpu_count, 8)
        self.assertEqual(offers[0].price_usd_hr, 32)
        self.assertEqual(offers[0].region, "us-west-1")
        self.assertEqual(
            session.calls[0]["headers"]["X-API-Version"],
            "2",
        )

    def test_thunder_compute_joins_public_prices_and_live_availability(self) -> None:
        session = _FakeSession(
            [
                {"pricing": {"h100_x1": 2.19, "a100xl_x2": 2.08}},
                {
                    "specs": {
                        "h100_x1": "available",
                        "a100xl_x2": "unavailable",
                    }
                },
            ]
        )
        fetched = ThunderComputeClient(
            api_base="https://example.test",
            session=session,
        ).fetch_catalog()
        offers, unknown = normalize_thunder_catalog(
            fetched.pricing,
            fetched.availability,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/thunder.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].provider, "thunder_compute")
        self.assertEqual(offers[0].source_connector, "thunder_compute")
        self.assertEqual(offers[0].gpu_model, "H100_80GB")
        self.assertEqual(offers[0].price_usd_hr, 2.19)
        self.assertEqual(offers[0].available_gpu_count, 1)
        self.assertEqual(offers[1].gpu_model, "A100_80GB_x2")
        self.assertEqual(offers[1].availability_status, "unavailable")
        self.assertEqual(
            [call["url"] for call in session.calls],
            [
                "https://example.test/v2/pricing",
                "https://example.test/v2/status",
            ],
        )

    def test_vultr_joins_public_gpu_plans_to_region_deployability(self) -> None:
        session = _FakeSession(
            [
                {
                    "plans": [
                        {
                            "id": "vcg-a100-1c-6g-2vram",
                            "type": "vcg",
                            "gpu_type": "NVIDIA_H100",
                            "gpu_count": 1,
                            "gpu_vram_gb": 80,
                            "hourly_cost": 2.50,
                            "deploy_ondemand": True,
                            "deploy_preemptible": False,
                        }
                    ]
                },
                {
                    "plans_metal": [
                        {
                            "id": "vbm-8-b200-gpu",
                            "type": "vbm",
                            "gpu_type": "NVIDIA_B200",
                            "gpu_count": 8,
                            "gpu_vram_gb": 1440,
                            "hourly_cost": 0,
                            "hourly_cost_preemptible": 25.60,
                            "deploy_ondemand": False,
                            "deploy_preemptible": True,
                        }
                    ]
                },
                {"regions": [{"id": "ewr"}]},
                {"available_plans": ["vcg-a100-1c-6g-2vram"]},
            ]
        )
        fetched = VultrClient(
            api_base="https://example.test/v2",
            session=session,
        ).fetch_gpu_catalog()
        offers, unknown = normalize_vultr_gpu_plans(
            fetched.plans,
            available_regions_by_plan=fetched.available_regions_by_plan,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/vultr.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].gpu_model, "H100_80GB")
        self.assertEqual(offers[0].availability_status, "available")
        self.assertEqual(offers[0].region, "ewr")
        self.assertEqual(offers[0].available_gpu_count, 1)
        self.assertEqual(offers[1].gpu_model, "B200_180GB_x8")
        self.assertEqual(offers[1].price_usd_hr, 25.60)
        self.assertEqual(offers[1].availability_status, "spot_price_observed")
        self.assertIsNone(offers[1].available_gpu_count)

    def test_scaleway_converts_public_zone_prices_and_preserves_stock_state(
        self,
    ) -> None:
        fx_csv = "TIME_PERIOD,OBS_VALUE\n2026-07-23,1.14\n"
        session = _FakeSession(
            [
                fx_csv,
                {
                    "servers": {
                        "H100-1-80G": {
                            "gpu": 1,
                            "gpu_info": {
                                "gpu_name": "H100-PCIe",
                                "gpu_memory": 80 * 1024**3,
                            },
                            "hourly_price": 2.50,
                            "ncpus": 24,
                            "ram": 240 * 1024**3,
                            "end_of_service": False,
                        },
                        "B300-SXM-2-288G": {
                            "gpu": 2,
                            "gpu_info": {
                                "gpu_name": "B300-SXM",
                                "gpu_memory": 288 * 1024**3,
                            },
                            "hourly_price": 18.96,
                            "ncpus": 56,
                            "ram": 960 * 1024**3,
                            "end_of_service": False,
                        },
                    }
                },
                {
                    "servers": {
                        "H100-1-80G": {"availability": "scarce"},
                        "B300-SXM-2-288G": {"availability": "shortage"},
                    }
                },
            ]
        )
        fetched = ScalewayClient(
            api_base="https://example.test",
            fx_url="https://ecb.example.test",
            zones=["fr-par-2"],
            session=session,
        ).fetch_gpu_catalog()
        offers, unknown = normalize_scaleway_gpu_products(
            fetched.products,
            eur_usd_rate=fetched.eur_usd_rate,
            fx_observed_date=fetched.fx_observed_date,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/scaleway.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].gpu_model, "H100_80GB")
        self.assertEqual(offers[0].availability_status, "available")
        self.assertEqual(offers[0].available_gpu_count, 1)
        self.assertAlmostEqual(offers[0].price_usd_hr, 2.85)
        self.assertEqual(offers[0].metadata["source_availability"], "scarce")
        self.assertEqual(offers[1].gpu_model, "B300_288GB_x2")
        self.assertEqual(offers[1].availability_status, "unavailable")
        self.assertIsNone(offers[1].available_gpu_count)
        self.assertAlmostEqual(offers[1].price_usd_hr, 21.6144)
        self.assertEqual(fetched.fx_observed_date, "2026-07-23")
        self.assertEqual(
            [call["url"] for call in session.calls],
            [
                "https://ecb.example.test",
                "https://example.test/instance/v1/zones/fr-par-2/products/servers",
                "https://example.test/instance/v1/zones/fr-par-2/products/servers/availability",
            ],
        )

    def test_jarvislabs_preserves_prices_and_assigns_free_capacity_once(self) -> None:
        session = _FakeSession(
            [
                {
                    "server_meta": [
                        {
                            "gpu_type": "NVIDIA H200",
                            "region": "europe-1",
                            "num_free_devices": 9,
                            "effective_num_free_devices": 7,
                            "price_per_hour": 3.80,
                            "spot_price": 2.90,
                            "vram": "141 GB",
                            "arc": "hopper",
                        }
                    ]
                }
            ]
        )
        fetched = JarvisLabsClient(
            api_key="jarvis-key",
            api_base="https://example.test",
            session=session,
        ).fetch_gpu_availability()
        offers, unknown = normalize_jarvislabs_availability(
            fetched.rows,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/jarvislabs.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].gpu_model, "H200_141GB")
        self.assertEqual(offers[0].available_gpu_count, 7)
        self.assertEqual(offers[1].availability_status, "spot_available")
        self.assertIsNone(offers[1].available_gpu_count)
        self.assertEqual(
            session.calls[0]["headers"]["Authorization"],
            "Bearer jarvis-key",
        )

    def test_oracle_public_catalog_preserves_payg_rates_without_capacity_claim(
        self,
    ) -> None:
        session = _FakeSession(
            [
                {
                    "lastUpdated": "2026-07-16T13:52:41.483Z",
                    "items": [
                        {
                            "partNumber": "B110978",
                            "displayName": "OCI - Compute - GPU - B200",
                            "metricName": "GPU Per Hour",
                            "serviceCategory": "Compute - GPU",
                            "currencyCodeLocalizations": [
                                {
                                    "currencyCode": "USD",
                                    "prices": [
                                        {
                                            "model": "PAY_AS_YOU_GO",
                                            "value": 14,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                {
                    "lastUpdated": "2026-07-16T13:52:41.483Z",
                    "items": [
                        {
                            "partNumber": "B112140",
                            "displayName": "OCI - Compute - GPU - GB300",
                            "metricName": "GPU Per Hour",
                            "serviceCategory": "Compute - GPU",
                            "currencyCodeLocalizations": [
                                {
                                    "currencyCode": "USD",
                                    "prices": [
                                        {
                                            "model": "PAY_AS_YOU_GO",
                                            "value": 18,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            ]
        )
        fetched = OracleCloudClient(
            api_url="https://oracle.example.test/products/",
            skus=[
                OracleGpuSku("B110978", "NVIDIA B200", 180),
                OracleGpuSku("B112140", "NVIDIA B300", 288, "GB300"),
            ],
            session=session,
        ).fetch_gpu_catalog()
        offers, unknown = normalize_oracle_gpu_products(
            fetched.products,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/oracle.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].gpu_model, "B200_180GB")
        self.assertEqual(offers[0].price_usd_hr, 14)
        self.assertEqual(offers[0].availability_status, "published_rate")
        self.assertIsNone(offers[0].available_gpu_count)
        self.assertEqual(offers[1].gpu_model, "B300_288GB")
        self.assertEqual(offers[1].metadata["package_model"], "GB300")
        self.assertEqual(
            session.calls[0]["params"],
            {"partNumber": "B110978", "currencyCode": "USD"},
        )

    def test_ovhcloud_filters_hourly_gpu_vms_and_converts_public_eur_price(
        self,
    ) -> None:
        hourly_plan = {
            "planCode": "h100-380.consumption",
            "invoiceName": "h100-380",
            "product": "publiccloud-instance",
            "pricingType": "consumption",
            "pricings": [
                {
                    "interval": 1,
                    "intervalUnit": "hour",
                    "price": 280_000_000,
                    "type": "consumption",
                }
            ],
            "blobs": {
                "commercial": {"brick": "gpu"},
                "tags": ["active"],
                "technical": {
                    "cpu": {"cores": 30},
                    "gpu": {
                        "model": "H100",
                        "number": 1,
                        "memory": {"size": 80},
                    },
                    "memory": {"size": 380},
                    "os": {"family": "linux"},
                },
            },
        }
        monthly_plan = {
            **hourly_plan,
            "planCode": "h100-380.monthly.postpaid",
            "pricingType": "purchase",
        }
        session = _FakeSession(
            [
                {
                    "catalogId": 42,
                    "locale": {"currencyCode": "EUR", "subsidiary": "FR"},
                    "plans": [
                        {
                            "planCode": "project",
                            "addonFamilies": [{"addons": [hourly_plan, monthly_plan]}],
                        }
                    ],
                },
                "TIME_PERIOD,OBS_VALUE\n2026-07-23,1.14\n",
            ]
        )
        fetched = OvhCloudClient(
            catalog_url="https://ovh.example.test/catalog",
            fx_url="https://ecb.example.test",
            session=session,
        ).fetch_gpu_catalog()
        offers, unknown = normalize_ovhcloud_gpu_plans(
            fetched.plans,
            eur_usd_rate=fetched.eur_usd_rate,
            fx_observed_date=fetched.fx_observed_date,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/ovhcloud.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(fetched.plans), 1)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].gpu_model, "H100_80GB")
        self.assertAlmostEqual(offers[0].price_usd_hr, 3.192)
        self.assertEqual(offers[0].availability_status, "published_rate")
        self.assertIsNone(offers[0].available_gpu_count)
        self.assertEqual(
            offers[0].metadata["price_basis"],
            "ovhcloud_public_on_demand_instance_hour",
        )

    def test_gridstackhub_is_deduplicated_external_evidence_not_benchmark_input(
        self,
    ) -> None:
        session = _FakeSession(
            [
                {
                    "as_of": "2026-07-24",
                    "count": 3,
                    "data": [
                        {
                            "id": 1,
                            "provider": "Lambda Labs",
                            "gpu_model": "B200",
                            "gpu_vram_gb": 180,
                            "instance_type": "2x B200",
                            "gpu_count": 2,
                            "hourly_rate": 13.78,
                            "pricing_type": "on-demand",
                            "region": "US",
                            "last_updated": "2026-05-19T00:00:00.000Z",
                            "scrape_source": "manual",
                            "active": True,
                        },
                        {
                            "id": 2,
                            "provider": "Lambda",
                            "gpu_model": "B200",
                            "gpu_vram_gb": 180,
                            "instance_type": "2x B200",
                            "gpu_count": 2,
                            "hourly_rate": 13.78,
                            "pricing_type": "on-demand",
                            "region": "US",
                            "last_updated": "2026-07-23T00:00:00.000Z",
                            "scrape_source": "lambda-labs",
                            "active": True,
                        },
                        {
                            "id": 3,
                            "provider": "Example Cloud",
                            "gpu_model": "B300",
                            "gpu_vram_gb": 192,
                            "instance_type": "B300",
                            "gpu_count": 1,
                            "hourly_rate": 7.5,
                            "pricing_type": "on-demand",
                            "region": "EU",
                            "last_updated": "2026-07-22T00:00:00.000Z",
                            "scrape_source": "manual",
                            "active": True,
                        },
                    ],
                }
            ]
        )
        fetched = GridStackHubClient(
            api_url="https://gridstack.example.test/prices",
            session=session,
        ).fetch_prices()
        offers, unknown = normalize_gridstackhub_reference_prices(
            fetched.rows,
            as_of=fetched.as_of,
            fetched_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/gridstackhub.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].provider, "example_cloud")
        self.assertEqual(offers[0].gpu_model, "B300_288GB")
        self.assertEqual(offers[0].vram_gb, 288)
        self.assertEqual(offers[0].availability_status, "external_reference")
        self.assertFalse(offers[0].metadata["benchmark_eligible"])
        self.assertEqual(offers[1].provider, "lambda")
        self.assertEqual(offers[1].source_offer_id, "gridstackhub:2")
        self.assertEqual(offers[1].source_connector, "gridstackhub")

    def test_cloud_gpu_prices_keeps_only_complete_comparable_external_prices(
        self,
    ) -> None:
        session = _FakeSession(
            [
                {
                    "generated_at": "2026-07-24T05:11:26.731Z",
                    "pagination": {"next_cursor": None},
                    "offerings": [
                        {
                            "id": "offering-b300",
                            "name": "1x B300",
                            "provider": {
                                "slug": "example-cloud",
                                "name": "Example Cloud",
                            },
                            "product": {
                                "slug": "gpu-instances",
                                "name": "GPU Instances",
                                "category": "gpu_vm",
                            },
                            "source_url": "https://example.test/pricing",
                            "hardware": {
                                "selection": "fixed",
                                "options": [{"slug": "b300", "name": "NVIDIA B300"}],
                                "gpu_count": "1",
                                "gpu_memory_per_device_gb": 268,
                            },
                            "availability": "available",
                            "freshness": {"state": "current"},
                            "provenance": {"verified_at": "2026-07-23T12:00:00Z"},
                            "variants": [
                                {
                                    "id": "variant-standard",
                                    "name": "On-demand",
                                    "region_code": "us-east",
                                    "region": {"country_code": "US"},
                                    "operating_mode": "instance_rental",
                                    "purchase_option": "standard",
                                    "tenancy": "dedicated",
                                    "interruption_policy": "non_interruptible",
                                    "comparison": {
                                        "pricing_structure": "inclusive_total",
                                        "fixed_gpu_eligible": True,
                                        "total_price_eligible": True,
                                        "reason_codes": [],
                                        "comparable_hourly_amount_picos": (
                                            "7500000000000"
                                        ),
                                    },
                                },
                                {
                                    "id": "variant-components",
                                    "name": "Components",
                                    "comparison": {
                                        "pricing_structure": "additive_components",
                                        "fixed_gpu_eligible": True,
                                        "total_price_eligible": False,
                                        "reason_codes": ["additive_price_not_total"],
                                    },
                                },
                            ],
                        }
                    ],
                },
            ]
        )
        fetched = CloudGpuPricesClient(
            api_url="https://cloudgpuprices.example.test/offerings",
            session=session,
        ).fetch_frontier_offerings()
        offers, unknown = normalize_cloud_gpu_prices_external_offerings(
            fetched.offerings,
            generated_at=fetched.generated_at,
            fetched_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/cloud-gpu-prices.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(fetched.offerings), 1)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].provider, "example_cloud")
        self.assertEqual(offers[0].source_connector, "cloud_gpu_prices")
        self.assertEqual(offers[0].gpu_model, "B300_288GB")
        self.assertEqual(offers[0].vram_gb, 288)
        self.assertEqual(offers[0].price_usd_hr, 7.5)
        self.assertEqual(offers[0].availability_status, "external_reference")
        self.assertFalse(offers[0].metadata["benchmark_eligible"])
        self.assertEqual(offers[0].metadata["source_vram_gb"], 268)

    def test_getdeploying_paginates_frontier_external_references(self) -> None:
        session = _FakeSession(
            [
                {
                    "page": 1,
                    "page_size": 1,
                    "page_count": 2,
                    "total": 2,
                    "data": [
                        {
                            "id": "cloud-b300",
                            "external_id": "b300-8x",
                            "provider": {
                                "id": "example-cloud",
                                "name": "Example Cloud",
                                "website": "https://example.test",
                                "country": "US",
                            },
                            "configuration": {
                                "gpu_model": "nvidia-b300",
                                "gpu_count": 8,
                                "vram_per_gpu_gb": 270,
                                "interconnect": "SXM",
                            },
                            "pricing": {
                                "currency": "USD",
                                "billing_type": "ON_DEMAND",
                                "hourly": 56,
                                "hourly_per_gpu": 7,
                            },
                            "status": {
                                "availability": "AVAILABLE",
                                "last_verified": "2026-07-23T12:00:00Z",
                            },
                        }
                    ],
                },
                {
                    "page": 2,
                    "page_size": 1,
                    "page_count": 2,
                    "total": 2,
                    "data": [
                        {
                            "id": "cloud-h100",
                            "provider": {
                                "id": "other-cloud",
                                "name": "Other Cloud",
                            },
                            "configuration": {
                                "gpu_model": "nvidia-h100",
                                "gpu_count": 1,
                                "vram_per_gpu_gb": 80,
                            },
                            "pricing": {
                                "currency": "USD",
                                "billing_type": "SPOT",
                                "hourly": 2,
                            },
                            "status": {
                                "availability": "AVAILABLE",
                                "last_verified": "2026-07-23T13:00:00Z",
                            },
                        }
                    ],
                },
            ]
        )
        fetched = GetDeployingClient(
            api_key="getdeploying-key",
            api_url="https://getdeploying.example.test/offerings",
            session=session,
        ).fetch_frontier_offerings(page_size=1, max_pages=3)
        offers, unknown = normalize_getdeploying_external_offerings(
            fetched.offerings,
            fetched_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/getdeploying.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].gpu_model, "B300_288GB_x8")
        self.assertEqual(offers[0].vram_gb, 288)
        self.assertEqual(offers[0].availability_status, "external_reference")
        self.assertFalse(offers[0].metadata["benchmark_eligible"])
        self.assertTrue(offers[1].is_spot)
        self.assertEqual(
            session.calls[0]["headers"]["Authorization"],
            "Bearer getdeploying-key",
        )

    def test_default_market_scope_includes_public_feeds_and_keyed_jarvislabs(
        self,
    ) -> None:
        with patch.dict("os.environ", {}, clear=True):
            public_scope = default_market_providers()
        with patch.dict(
            "os.environ",
            {
                "CLORE_API_KEY": "configured",
                "JL_API_KEY": "configured",
                "GETDEPLOYING_API_KEY": "configured",
            },
            clear=True,
        ):
            authenticated_scope = default_market_providers()

        self.assertIn("thunder_compute", public_scope)
        self.assertIn("vultr", public_scope)
        self.assertIn("scaleway", public_scope)
        self.assertIn("oracle_cloud", public_scope)
        self.assertIn("ovhcloud", public_scope)
        self.assertIn("gridstackhub", public_scope)
        self.assertIn("cloud_gpu_prices", public_scope)
        self.assertNotIn("clore", public_scope)
        self.assertNotIn("jarvislabs", public_scope)
        self.assertIn("clore", authenticated_scope)
        self.assertIn("jarvislabs", authenticated_scope)
        self.assertIn("getdeploying", authenticated_scope)

    def test_gpus_io_paginates_and_preserves_provider_level_live_offers(
        self,
    ) -> None:
        session = _FakeSession(
            [
                {
                    "data": [
                        {
                            "gpu": {
                                "key": "b300",
                                "name": "NVIDIA B300",
                                "vramGb": 288,
                            },
                            "provider": {
                                "id": "lambdalabs",
                                "name": "Lambda",
                                "website": "https://lambda.ai",
                            },
                            "rentalType": "on_demand",
                            "commitmentTermMonths": None,
                            "gpuCount": 8,
                            "pricePerGpuHourUsd": 4.5,
                            "totalPricePerHourUsd": 36,
                            "regions": ["us", "fi"],
                            "available": True,
                            "lastUpdated": "2026-07-24T00:00:00Z",
                            "specs": {"vcpu": 208, "ramGb": 1800},
                        }
                    ],
                    "pagination": {"nextCursor": "next-page", "limit": 200},
                },
                {
                    "data": [
                        {
                            "gpu": {
                                "key": "h100",
                                "name": "NVIDIA H100",
                                "vramGb": 80,
                            },
                            "provider": {"id": "runpod", "name": "RunPod"},
                            "rentalType": "spot",
                            "gpuCount": 1,
                            "pricePerGpuHourUsd": 1.8,
                            "totalPricePerHourUsd": 1.8,
                            "regions": ["us"],
                            "available": True,
                        }
                    ],
                    "pagination": {"nextCursor": None, "limit": 200},
                },
            ]
        )
        fetched = GpusIoClient(
            api_key="gpus-key",
            api_base="https://example.test/v1",
            session=session,
        ).fetch_prices()
        offers, unknown = normalize_gpus_io_prices(
            fetched.prices,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/gpus-io.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(fetched.raw_payload["pages"]), 2)
        self.assertEqual(len(offers), 3)
        self.assertEqual(offers[0].provider, "lambda")
        self.assertEqual(offers[0].source_connector, "gpus_io")
        self.assertEqual(offers[0].gpu_model, "B300_288GB_x8")
        self.assertEqual(offers[0].available_gpu_count, 8)
        self.assertEqual(offers[0].price_usd_hr, 36)
        self.assertEqual(offers[2].availability_status, "spot_available")
        self.assertEqual(session.calls[1]["params"]["cursor"], "next-page")
        self.assertEqual(
            session.calls[0]["headers"]["Authorization"],
            "Bearer gpus-key",
        )

    def test_hyperstack_joins_live_stock_to_pricebook_without_double_counting(
        self,
    ) -> None:
        session = _FakeSession(
            [
                {
                    "stocks": [
                        {
                            "region": "CANADA-1",
                            "stock-type": "GPU",
                            "models": [
                                {
                                    "model": "B200-SXM",
                                    "available": "6",
                                    "configurations": {
                                        "1x": 6,
                                        "2x": 2,
                                        "4x": 0,
                                    },
                                }
                            ],
                        }
                    ]
                },
                [
                    {"name": "CPU", "value": "0"},
                    {"name": "RAM", "value": "0"},
                    {"name": "B200-SXM", "value": "4.25"},
                ],
            ]
        )
        fetched = HyperstackClient(
            api_key="key",
            api_base="https://example.test/v1",
            session=session,
        ).fetch_stock_and_prices()
        offers, unknown = normalize_stock(
            fetched.stocks,
            pricebook=fetched.pricebook,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/hyperstack.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].gpu_model, "B200_180GB")
        self.assertEqual(offers[0].available_gpu_count, 6)
        self.assertEqual(offers[0].price_usd_hr, 4.25)
        self.assertEqual(offers[1].gpu_model, "B200_180GB_x2")
        self.assertEqual(offers[1].available_gpu_count, 0)
        self.assertEqual(offers[1].price_usd_hr, 8.5)
        self.assertEqual(session.calls[0]["headers"]["api_key"], "key")

    def test_lambda_cloud_expands_capacity_regions_into_executable_offers(
        self,
    ) -> None:
        session = _FakeSession(
            [
                {
                    "data": {
                        "gpu_8x_b200": {
                            "instance_type": {
                                "name": "gpu_8x_b200",
                                "description": "8x NVIDIA B200",
                                "gpu_description": "NVIDIA B200 (180 GB SXM)",
                                "price_cents_per_hour": 3200,
                                "specs": {
                                    "vcpus": 208,
                                    "memory_gib": 1800,
                                    "storage_gib": 6144,
                                    "gpus": 8,
                                },
                            },
                            "regions_with_capacity_available": [
                                {"name": "us-west-1", "description": "California"},
                                {"name": "us-south-1", "description": "Texas"},
                            ],
                        }
                    }
                },
            ]
        )
        fetched = LambdaCloudClient(
            api_key="lambda-key",
            api_base="https://example.test/api/v1",
            session=session,
        ).fetch_instance_types()
        offers, unknown = normalize_lambda_instance_types(
            fetched.instance_types,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/lambda.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].gpu_model, "B200_180GB_x8")
        self.assertEqual(offers[0].gpu_count, 8)
        self.assertEqual(offers[0].available_gpu_count, 8)
        self.assertEqual(offers[0].price_usd_hr, 32)
        self.assertEqual(offers[1].region, "us-south-1")

    def test_digitalocean_paginates_live_gpu_sizes_by_region(self) -> None:
        session = _FakeSession(
            [
                {
                    "sizes": [
                        {
                            "slug": "gpu-b300x8-2304gb",
                            "available": True,
                            "description": "GPU B300 x8",
                            "price_hourly": 31.92,
                            "price_monthly": 23301.6,
                            "regions": ["ric1"],
                            "gpu_info": {
                                "count": 8,
                                "model": "nvidia_b300",
                                "vram": {"amount": 2304, "unit": "gib"},
                            },
                            "vcpus": 224,
                            "memory": 2097152,
                            "disk": 7200,
                        }
                    ],
                    "links": {"pages": {}},
                    "meta": {"total": 1},
                }
            ]
        )
        fetched = DigitalOceanClient(
            api_token="do-token",
            api_base="https://example.test/v2",
            session=session,
        ).fetch_sizes()
        offers, unknown = normalize_digitalocean_sizes(
            fetched.sizes,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/digitalocean.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].gpu_model, "B300_288GB_x8")
        self.assertEqual(offers[0].vram_gb, 288)
        self.assertEqual(offers[0].available_gpu_count, 8)
        self.assertEqual(offers[0].price_usd_hr, 31.92)
        self.assertEqual(offers[0].region, "ric1")

    def test_prime_intellect_frontier_availability_preserves_source_provider(
        self,
    ) -> None:
        session = _FakeSession(
            [
                {
                    "items": [
                        {
                            "cloudId": "h100-pcie-1",
                            "gpuType": "H100_80GB",
                            "provider": "runpod",
                            "gpuCount": 2,
                            "gpuMemory": 80,
                            "security": "secure_cloud",
                            "prices": {
                                "currency": "USD",
                                "onDemand": 4.2,
                                "isVariable": False,
                            },
                            "region": "united_states",
                            "dataCenter": "US-KS-2",
                            "country": "US",
                            "stockStatus": "Available",
                            "isSpot": False,
                            "socket": "PCIe",
                            "disk": {
                                "minCount": 80,
                                "defaultCount": 80,
                                "pricePerUnit": 0.00014,
                                "defaultIncludedInPrice": False,
                            },
                        }
                    ],
                    "totalCount": 1,
                }
            ]
        )
        fetched = PrimeIntellectClient(
            api_key="test-key",
            api_base="https://example.test/api/v1",
            session=session,
        ).fetch_frontier_availability(gpu_types=["H100_80GB"])
        offers, unknown = normalize_availability(
            fetched.items,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/prime.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].provider, "runpod")
        self.assertEqual(offers[0].source_connector, "prime_intellect")
        self.assertEqual(offers[0].gpu_model, "H100_80GB_x2")
        self.assertEqual(offers[0].price_usd_hr, 4.2)
        self.assertIsNone(offers[0].available_gpu_count)
        self.assertEqual(offers[0].gpu_socket, "PCIe")
        self.assertEqual(offers[0].stock_status, "Available")
        self.assertFalse(offers[0].price_is_variable)
        self.assertAlmostEqual(
            offers[0].required_resource_price_usd_hr or 0,
            0.0112,
        )
        self.assertAlmostEqual(
            offers[0].minimum_executable_price_usd_hr or 0,
            4.2112,
        )
        self.assertEqual(
            offers[0].metadata["capacity_basis"],
            "configuration_presence",
        )
        self.assertEqual(offers[0].metadata["upstream_provider"], "runpod")
        self.assertEqual(session.calls[0]["params"]["gpu_type"], "H100_80GB")

    def test_shadeform_expands_available_regions_and_converts_cents(self) -> None:
        offers, unknown = normalize_instance_types(
            [
                {
                    "cloud": "hyperstack",
                    "shade_instance_type": "H200x8",
                    "cloud_instance_type": "gpu_8x_h200",
                    "configuration": {
                        "gpu_type": "H200",
                        "num_gpus": 8,
                        "vram_per_gpu_in_gb": 141,
                    },
                    "hourly_price": 3200,
                    "availability": [
                        {"region": "eu-1", "available": True, "display_name": "Europe"},
                        {
                            "region": "us-1",
                            "available": False,
                            "display_name": "United States",
                        },
                    ],
                }
            ],
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/shadeform.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].provider, "hyperstack")
        self.assertEqual(offers[0].source_connector, "shadeform")
        self.assertEqual(offers[0].gpu_model, "H200_141GB_x8")
        self.assertEqual(offers[0].price_usd_hr, 32.0)
        self.assertEqual(offers[0].region, "Europe")

    def test_sesterce_and_runpod_normalize_live_availability(self) -> None:
        sesterce, sesterce_unknown = normalize_sesterce_offers(
            [
                {
                    "gpuName": "B200",
                    "gpuCount": 8,
                    "instanceId": "B200x8",
                    "cloud": {"_id": "cloud-1", "name": "Valence"},
                    "configuration": {"vRamGB": 180, "interconnect": "SXM"},
                    "hourlyPrice": 48,
                    "availability": [
                        {
                            "region": "fr-1",
                            "name": "France",
                            "countryCode": "FR",
                            "available": True,
                        }
                    ],
                }
            ],
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/sesterce.json",
        )
        runpod, runpod_unknown = normalize_gpu_types(
            [
                {
                    "id": "NVIDIA H100 80GB HBM3",
                    "displayName": "H100",
                    "memoryInGb": 80,
                    "secureCloud": True,
                    "lowestPrice": {
                        "stockStatus": "High",
                        "uninterruptablePrice": 2.49,
                        "availableGpuCounts": [1, 2, 4, 8],
                    },
                }
            ],
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/runpod.json",
        )

        self.assertEqual(sesterce_unknown, [])
        self.assertEqual(sesterce[0].gpu_model, "B200_180GB_x8")
        self.assertEqual(sesterce[0].price_usd_hr, 48)
        self.assertEqual(runpod_unknown, [])
        self.assertEqual(runpod[0].gpu_model, "H100_80GB")
        self.assertEqual(runpod[0].price_usd_hr, 2.49)
        self.assertEqual(runpod[0].availability_status, "available")

    def test_runpod_read_only_inventory_does_not_require_an_api_key(self) -> None:
        session = _FakeSession([{"data": {"gpuTypes": [{"id": "NVIDIA B300"}]}}])
        client = RunpodClient(
            session=session, graphql_url="https://example.test/graphql"
        )

        fetched = client.fetch_gpu_types()

        self.assertEqual(fetched.gpu_types, [{"id": "NVIDIA B300"}])
        self.assertNotIn("params", session.calls[0])

    def test_clore_public_marketplace_normalizes_available_server_hour_price(
        self,
    ) -> None:
        session = _FakeSession(
            [
                {
                    "code": 0,
                    "servers": [
                        {
                            "id": 113361,
                            "owner": 9001,
                            "rented": False,
                            "gpu_array": [" H100 80GB HBM3"] * 8,
                            "specs": {
                                "gpu": "8x NVIDIA H100 80GB HBM3",
                                "gpuram": 79,
                                "net": {"cc": "CA", "down": 1000, "up": 1000},
                            },
                            "price": {"usd": {"on_demand_usd": 20.0}},
                            "reliability": 0.99,
                            "rating": {"avg": 4.8, "cnt": 20},
                            "partial_gpu_rental": {
                                "total_gpus": 8,
                                "available_gpus": 8,
                            },
                            "cuda_version": "12.8",
                            "mrl": 24,
                        },
                        {
                            "id": 113362,
                            "rented": True,
                            "gpu_array": [" H100 80GB HBM3"],
                            "price": {"usd": {"on_demand_usd": 2.5}},
                        },
                    ],
                }
            ]
        )
        fetched = CloreClient(
            api_key="clore-key",
            marketplace_url="https://example.test/v1/marketplace",
            session=session,
        ).fetch_marketplace()
        offers, unknown = normalize_servers(
            fetched.servers,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/clore.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(fetched.raw_payload["server_count"], 2)
        self.assertEqual(session.calls[0]["headers"]["auth"], "clore-key")
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].provider, "clore")
        self.assertEqual(offers[0].gpu_model, "H100_80GB_x8")
        self.assertEqual(offers[0].gpu_count, 8)
        self.assertEqual(offers[0].price_usd_hr, 20.0)
        self.assertEqual(offers[0].country, "CA")
        self.assertEqual(offers[0].availability_status, "available")
        self.assertTrue(offers[0].metadata["capacity_confirmed"])
        self.assertTrue(offers[0].metadata["partial_gpu_rental_enabled"])
        self.assertEqual(offers[0].metadata["partial_gpu_available"], 8)

    def test_verda_public_catalog_and_authenticated_availability_are_distinct(
        self,
    ) -> None:
        instance_type = {
            "instance_type": "2B300.60V",
            "model": "B300",
            "name": "B300 SXM6 268GB",
            "price_per_hour": "15.00",
            "spot_price": "5.25",
            "currency": "usd",
            "gpu": {
                "description": "2x B300 SXM6 268GB",
                "number_of_gpus": 2,
            },
            "gpu_memory": {"size_in_gigabytes": 268},
            "manufacturer": "NVIDIA",
        }
        public_offers, public_unknown = normalize_instance_catalog(
            [instance_type],
            availability=None,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/verda.json",
        )
        live_offers, live_unknown = normalize_instance_catalog(
            [instance_type],
            availability=[
                {"location_code": "FIN-02", "availabilities": ["2B300.60V"]},
                {"location_code": "ICE-01", "availabilities": ["2B300.60V"]},
            ],
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/verda.json",
        )

        self.assertEqual(public_unknown, [])
        self.assertEqual(live_unknown, [])
        self.assertEqual(public_offers[0].availability_status, "published_rate")
        self.assertFalse(public_offers[0].metadata["capacity_confirmed"])
        self.assertEqual(
            [offer.region for offer in live_offers if not offer.is_spot],
            ["FIN-02", "ICE-01"],
        )
        self.assertTrue(
            all(offer.gpu_model == "B300_288GB_x2" for offer in live_offers)
        )
        self.assertEqual(live_offers[-1].availability_status, "spot_price_observed")

    def test_verda_client_uses_oauth_only_when_credentials_are_present(self) -> None:
        public_session = _FakeSession([[{"instance_type": "1H100"}]])
        public_fetch = VerdaClient(
            api_base="https://example.test/v1",
            session=public_session,
        ).fetch_catalog()
        authenticated_session = _FakeSession(
            [
                [{"instance_type": "1B300.30V"}],
                {"access_token": "short-lived-token"},
                [{"location_code": "FIN-02", "availabilities": ["1B300.30V"]}],
            ]
        )
        authenticated_fetch = VerdaClient(
            client_id="client-id",
            client_secret="client-secret",
            api_base="https://example.test/v1",
            session=authenticated_session,
        ).fetch_catalog()

        self.assertIsNone(public_fetch.availability)
        self.assertEqual([call["method"] for call in public_session.calls], ["GET"])
        self.assertEqual(authenticated_fetch.availability[0]["location_code"], "FIN-02")
        self.assertEqual(
            [call["method"] for call in authenticated_session.calls],
            ["GET", "POST", "GET"],
        )
        self.assertEqual(
            authenticated_session.calls[-1]["headers"]["Authorization"],
            "Bearer short-lived-token",
        )

    def test_spheron_flattens_live_feed_and_separates_spot_offers(self) -> None:
        session = _FakeSession(
            [
                {
                    "data": [
                        {
                            "gpuType": "B300_SXM6",
                            "displayName": "B300 SXM6",
                            "offers": [
                                {
                                    "provider": "spheron-es",
                                    "offerId": "uk-b300-spot",
                                    "gpuCount": 1,
                                    "price": 5.8455,
                                    "available": True,
                                    "clusters": ["UK South 1"],
                                    "gpu_memory": 262,
                                    "spot_price": 5.8455,
                                    "maintenance": False,
                                    "extras": {
                                        "technical": {
                                            "units_available": 26,
                                            "availability_level": "AVAILABILITY_LEVEL_MEDIUM",
                                        }
                                    },
                                }
                            ],
                        }
                    ]
                }
            ]
        )
        fetched = SpheronClient(
            offers_url="https://example.test/gpu-offers", session=session
        ).fetch_offers()
        offers, unknown = normalize_spheron_offers(
            fetched.offers,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/spheron.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].provider, "spheron")
        self.assertEqual(offers[0].source_connector, "spheron")
        self.assertEqual(offers[0].gpu_model, "B300_288GB")
        self.assertEqual(offers[0].availability_status, "spot_available")
        self.assertTrue(offers[0].is_spot)
        self.assertEqual(offers[0].metadata["upstream_provider"], "spheron-es")
        self.assertEqual(offers[0].metadata["units_available"], 26)
        self.assertEqual(offers[0].available_gpu_count, 26)

    def test_akash_preserves_capacity_without_duplicating_summary_rows(self) -> None:
        session = _FakeSession(
            [
                {
                    "availability": {"total": 261, "available": 135},
                    "models": [
                        {
                            "vendor": "nvidia",
                            "model": "h100",
                            "ram": "80Gi",
                            "interface": "SXM5",
                            "availability": {"total": 71, "available": 29},
                            "providerAvailability": {"total": 4, "available": 4},
                            "price": {
                                "currency": "USD",
                                "min": 2.01,
                                "max": 3.16,
                                "med": 2.58,
                            },
                        }
                    ],
                },
                [
                    {
                        "owner": "akash1provider",
                        "isOnline": True,
                        "gpuModels": [
                            {
                                "vendor": "nvidia",
                                "model": "h100",
                                "ram": "80Gi",
                                "interface": "SXM5",
                            }
                        ],
                        "stats": {
                            "cpu": {
                                "active": 60000,
                                "available": 12000,
                                "pending": 450,
                                "total": 72450,
                            },
                            "gpu": {
                                "active": 42,
                                "available": 29,
                                "pending": 0,
                                "total": 71,
                            },
                            "memory": {
                                "active": 111154125824,
                                "available": 25769803776,
                                "pending": 0,
                                "total": 136923929600,
                            },
                            "storage": {
                                "ephemeral": {
                                    "active": 206537178112,
                                    "available": 100000000000,
                                    "pending": 0,
                                    "total": 306537178112,
                                },
                                "persistent": {
                                    "active": 50000000000,
                                    "available": 25000000000,
                                    "pending": 0,
                                    "total": 75000000000,
                                },
                                "total": {
                                    "active": 256537178112,
                                    "available": 125000000000,
                                    "pending": 0,
                                    "total": 381537178112,
                                },
                            },
                        },
                    }
                ],
            ]
        )
        fetched = AkashClient(
            prices_url="https://example.test/v1/gpu-prices",
            session=session,
        ).fetch_gpu_prices()
        offers, unknown = normalize_gpu_prices(
            fetched.models,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/akash.json",
        )

        self.assertEqual(unknown, [])
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].gpu_model, "H100_80GB")
        self.assertEqual(offers[0].price_usd_hr, 2.01)
        self.assertEqual(offers[0].metadata["available_gpu_units"], 29)
        self.assertEqual(offers[0].available_gpu_count, 29)
        self.assertEqual(offers[0].metadata["available_provider_count"], 4)
        state = normalize_akash_market_state(
            models=fetched.models,
            providers=fetched.providers,
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/akash.json",
        )
        occupancy = next(
            row for row in state if row.measurement_kind == "rental_occupancy"
        )
        h100 = next(row for row in state if row.resource_type == "H100_80GB")
        self.assertEqual(occupancy.unit, "gpu_units")
        self.assertEqual(occupancy.rented_units, 42)
        self.assertAlmostEqual(occupancy.rented_share or 0, 42 / 71)
        self.assertEqual(h100.measurement_kind, "availability_pressure")
        self.assertAlmostEqual(h100.available_share or 0, 29 / 71)
        by_resource = {row.resource_type: row for row in state}
        self.assertEqual(by_resource["ALL_CPU"].unit, "millicpu")
        self.assertEqual(by_resource["ALL_CPU"].rented_units, 60000)
        self.assertAlmostEqual(
            by_resource["ALL_CPU"].rented_share or 0,
            60000 / 72450,
        )
        self.assertEqual(by_resource["ALL_MEMORY"].resource_market, "memory")
        self.assertEqual(
            by_resource["ALL_EPHEMERAL_STORAGE"].available_units,
            100000000000,
        )
        self.assertEqual(
            by_resource["ALL_PERSISTENT_STORAGE"].total_units,
            75000000000,
        )
        self.assertEqual(
            by_resource["ALL_STORAGE"].total_units,
            381537178112,
        )

    def test_prime_market_state_uses_cli_configuration_denominator(self) -> None:
        state = normalize_prime_market_state(
            [
                {
                    "provider": "runpod",
                    "gpuType": "H100_80GB",
                    "gpuMemory": 80,
                    "gpuCount": 8,
                    "stockStatus": "Available",
                },
                {
                    "provider": "runpod",
                    "gpuType": "H100_80GB",
                    "gpuMemory": 80,
                    "gpuCount": 1,
                    "stockStatus": "Low",
                },
                {
                    "provider": "runpod",
                    "gpuType": "H100_80GB",
                    "gpuMemory": 80,
                    "gpuCount": 2,
                    "stockStatus": "Unavailable",
                },
            ],
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/prime.json",
        )

        self.assertEqual(len(state), 1)
        row = state[0]
        self.assertEqual(row.total_units, 3)
        self.assertEqual(row.available_units, 2)
        self.assertAlmostEqual(row.available_share or 0, 2 / 3)
        self.assertEqual(row.unit, "configurations")
        self.assertIn("not physical GPU-fleet", row.notes or "")

    def test_clore_market_state_is_server_weighted_and_on_demand_scoped(self) -> None:
        state = normalize_clore_market_state(
            [
                {
                    "rented": False,
                    "gpu_array": ["H100 80GB"],
                    "specs": {"gpuram": 80},
                },
                {
                    "rented": True,
                    "gpu_array": ["H100 80GB"] * 8,
                    "specs": {"gpuram": 80},
                },
            ],
            observed_at=OBSERVED_AT,
            raw_ref="s3://bucket/raw/clore.json",
        )

        aggregate = next(row for row in state if row.resource_type == "ALL_GPU")
        self.assertEqual(aggregate.unit, "servers")
        self.assertEqual(aggregate.total_units, 2)
        self.assertEqual(aggregate.rented_units, 1)
        self.assertEqual(aggregate.rented_share, 0.5)
        self.assertIn("on-demand only", aggregate.notes or "")

    def test_published_rate_cards_normalize_as_provider_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            runpod = ingest_rate_card(
                provider="runpod",
                raw_root=raw_root,
                lake_root=lake_root,
                dry_run=True,
                run_id="runpod-rates",
            )
            hyperstack = ingest_rate_card(
                provider="hyperstack",
                raw_root=raw_root,
                lake_root=lake_root,
                dry_run=True,
                run_id="hyperstack-rates",
            )
            vessl = ingest_rate_card(
                provider="vessl",
                raw_root=raw_root,
                lake_root=lake_root,
                dry_run=True,
                run_id="vessl-rates",
            )

            build_gold_market_tables(
                lake_root=lake_root,
                providers=["runpod", "hyperstack", "vessl"],
                run_id="gold-rate-cards",
            )
            values = query_gold_benchmark_values(lake_root=lake_root)
            constituents = query_gold_benchmark_constituents(
                lake_root=lake_root,
                benchmark_family_id="B300",
            )

        self.assertIn("runpod", rate_card_providers())
        self.assertIn("gmi_cloud", rate_card_providers())
        self.assertIn("digitalocean", rate_card_providers())
        self.assertIn("denvr", rate_card_providers())
        self.assertIn("massed_compute", rate_card_providers())
        self.assertIn("verda", rate_card_providers())
        self.assertIn("voltage_park", rate_card_providers())
        self.assertIn("civo", rate_card_providers())
        self.assertIn("koyeb", rate_card_providers())
        self.assertIn("hyperbolic", rate_card_providers())
        self.assertGreater(runpod.normalized_offer_count, 0)
        self.assertGreater(hyperstack.normalized_offer_count, 0)
        self.assertGreater(vessl.normalized_offer_count, 0)
        rows = {row["benchmark_family_id"]: row for row in values["rows"]}
        self.assertEqual(rows["B300"]["status"], "observed")
        self.assertEqual(rows["B300"]["provider_count"], 2)
        self.assertEqual(rows["H200"]["provider_count"], 2)
        self.assertEqual(rows["B300"]["benchmark_basis"], "advertised_hourly")
        self.assertEqual(
            rows["B300"]["methodology_version"], "advertised_provider_floor_median_v1"
        )
        hyperstack_b300 = next(
            row for row in constituents["rows"] if row["provider"] == "hyperstack"
        )
        self.assertFalse(hyperstack_b300["included"])
        self.assertEqual(
            hyperstack_b300["availability_status"], "published_rate_future"
        )
        self.assertEqual(hyperstack_b300["exclusion_reason"], "future_rate")

    def test_new_rate_cards_expand_frontier_gpu_coverage(self) -> None:
        providers = ["denvr", "massed_compute", "verda", "voltage_park"]
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            for provider in providers:
                ingest_rate_card(
                    provider=provider,
                    raw_root=raw_root,
                    lake_root=lake_root,
                    dry_run=True,
                    run_id=f"{provider}-rates",
                )

            build_gold_market_tables(
                lake_root=lake_root,
                providers=providers,
                run_id="gold-expanded-rate-cards",
            )
            values = query_gold_benchmark_values(lake_root=lake_root)

        rows = {row["benchmark_family_id"]: row for row in values["rows"]}
        self.assertEqual(rows["H100"]["provider_count"], 3)
        self.assertEqual(rows["H100"]["benchmark_usd_gpu_hr"], 2.10)
        self.assertEqual(rows["H200"]["provider_count"], 2)
        self.assertEqual(rows["B200"]["provider_count"], 1)
        self.assertEqual(rows["B300"]["provider_count"], 1)


class GoldQueryTests(unittest.TestCase):
    def test_prime_frontier_offer_market_tracks_families_and_events(
        self,
    ) -> None:
        first_observed = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)
        second_observed = datetime(2026, 7, 27, 11, 0, tzinfo=timezone.utc)

        def prime_offer(
            provider: str,
            offer_id: str,
            price: float,
            observed_at: datetime,
            *,
            gpu_model: str = "H100_80GB",
            vram_gb: int = 80,
        ) -> GpuOffer:
            return _offer(
                provider=provider,
                source_connector="prime_intellect",
                source_offer_id=offer_id,
                price_usd_hr=price,
                gpu_raw_name=gpu_model,
                gpu_model=gpu_model,
                vram_gb=vram_gb,
                observed_at=observed_at,
                is_spot=False,
                is_secure=True,
                gpu_socket="SXM",
                stock_status="Available",
                price_is_variable=False,
                minimum_executable_price_usd_hr=price + 0.01,
                required_resource_price_usd_hr=0.01,
                price_basis="provider_reported_gpu_base_rate",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            dashboard_root = str(Path(tmpdir) / "dashboard")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="prime_intellect",
                run_id="prime-1000",
                observed_at=first_observed,
                offers=[
                    prime_offer("alpha", "alpha-h100", 3.0, first_observed),
                    prime_offer("beta", "beta-h100", 4.0, first_observed),
                    prime_offer("charlie", "charlie-h100", 5.0, first_observed),
                    prime_offer(
                        "alpha",
                        "alpha-h200",
                        4.0,
                        first_observed,
                        gpu_model="H200_141GB",
                        vram_gb=141,
                    ),
                    prime_offer(
                        "beta",
                        "beta-h200",
                        5.0,
                        first_observed,
                        gpu_model="H200_141GB",
                        vram_gb=141,
                    ),
                    prime_offer(
                        "charlie",
                        "charlie-h200",
                        6.0,
                        first_observed,
                        gpu_model="H200_141GB",
                        vram_gb=141,
                    ),
                    prime_offer(
                        "alpha",
                        "alpha-b300",
                        7.5,
                        first_observed,
                        gpu_model="B300_288GB",
                        vram_gb=288,
                    ),
                ],
            )
            first = build_gold_market_tables(
                lake_root=lake_root,
                providers=["prime_intellect"],
                run_id="gold-market-20260727T100000-00000001",
            )

            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="prime_intellect",
                run_id="prime-1100",
                observed_at=second_observed,
                offers=[
                    prime_offer("alpha", "alpha-h100", 3.0, second_observed),
                    prime_offer("beta", "beta-h100", 4.5, second_observed),
                    prime_offer("delta", "delta-h100", 4.0, second_observed),
                    prime_offer(
                        "alpha",
                        "alpha-h200",
                        4.5,
                        second_observed,
                        gpu_model="H200_141GB",
                        vram_gb=141,
                    ),
                    prime_offer(
                        "beta",
                        "beta-h200",
                        5.5,
                        second_observed,
                        gpu_model="H200_141GB",
                        vram_gb=141,
                    ),
                    prime_offer(
                        "charlie",
                        "charlie-h200",
                        6.5,
                        second_observed,
                        gpu_model="H200_141GB",
                        vram_gb=141,
                    ),
                    prime_offer(
                        "alpha",
                        "alpha-b300",
                        7.5,
                        second_observed,
                        gpu_model="B300_288GB",
                        vram_gb=288,
                    ),
                ],
            )
            second = build_gold_market_tables(
                lake_root=lake_root,
                providers=["prime_intellect"],
                run_id="gold-market-20260727T110000-00000002",
            )
            result = query_gold_prime_frontier_offer_market(lake_root=lake_root)
            h100_compatibility = query_gold_prime_h100_offer_reference(
                lake_root=lake_root
            )
            export = export_gold_dashboard_snapshot(
                lake_root=lake_root,
                output_root=dashboard_root,
            )
            public = read_json(export["output_refs"]["prime_frontier_offer_market"])
            shelf = read_json(export["output_refs"]["prime_frontier_offer_shelf"])
            h100_benchmark_card = read_json(
                export["output_refs"]["gpu_benchmark_h100"]
            )
            h100_prime_card = read_json(
                export["output_refs"]["prime_frontier_h100"]
            )
            capacity_card = read_json(
                export["output_refs"]["capacity_market_state"]
            )
            reference_query = run_operator_query(
                lake_root=lake_root,
                query_id="prime_frontier_offer_reference",
                limit=10,
            )
            ladder_query = run_operator_query(
                lake_root=lake_root,
                query_id="prime_frontier_offer_ladder",
                limit=100,
            )

        self.assertEqual(
            first.row_counts["fact_prime_frontier_offer_reference_history"],
            3,
        )
        self.assertEqual(
            second.row_counts["fact_prime_frontier_offer_reference_history"],
            6,
        )
        self.assertEqual(len(result["history"]), 6)
        self.assertEqual(
            set(result["current"]),
            {"H100", "H200", "B300"},
        )
        self.assertEqual(result["current"]["H100"]["reference_usd_gpu_hr"], 4.0)
        self.assertEqual(result["current"]["H100"]["provider_count"], 3)
        self.assertEqual(result["current"]["H100"]["configuration_count"], 3)
        self.assertEqual(result["current"]["H100"]["low_price_provider_count"], 2)
        self.assertEqual(result["current"]["H100"]["status"], "observed")
        self.assertEqual(result["current"]["H200"]["reference_usd_gpu_hr"], 5.5)
        self.assertEqual(result["current"]["B300"]["status"], "indicative")
        self.assertEqual(
            result["current"]["H100"]["gold_observed_at"],
            second_observed.isoformat(),
        )
        self.assertEqual(
            {
                row["event_type"]
                for row in result["events"]
                if row["gpu_family_id"] == "H100"
            },
            {"entered", "left_availability", "remained", "repriced_up"},
        )
        self.assertTrue(
            any(
                row["is_market_benchmark_level"]
                for row in result["ladder"]
                if row["gpu_family_id"] == "H100"
            )
        )
        self.assertGreaterEqual(len(result["ladder"]), 39)
        products = {row["family_id"]: row for row in public["products"]}
        self.assertEqual(set(products), {"H100", "H200", "B200", "B300"})
        self.assertEqual(products["H100"]["current"]["reference_usd_gpu_hr"], 4.0)
        self.assertEqual(len(products["H100"]["history"]), 2)
        self.assertIsNone(products["B200"]["current"])
        self.assertEqual(
            {row["provider"] for row in products["H100"]["sources"]},
            {"alpha", "beta", "delta"},
        )
        self.assertEqual(h100_compatibility["current"]["reference_usd_gpu_hr"], 4.0)
        self.assertNotIn("raw_ref", json.dumps(public))
        self.assertNotIn("s3://", json.dumps(public))
        self.assertEqual(
            shelf["schema_version"],
            "prime_frontier_offer_shelf_public_v1",
        )
        self.assertEqual(
            {product["family_id"] for product in shelf["products"]},
            {"H100", "H200"},
        )
        self.assertTrue(shelf["products"][0]["event_history"])
        shelf_events = [
            event
            for product in shelf["products"]
            for event in product["event_history"]
        ]
        self.assertTrue(all(event["event_id"] for event in shelf_events))
        self.assertTrue(all(event["listing_id"] for event in shelf_events))
        self.assertNotIn("benchmark_history", json.dumps(shelf))
        self.assertNotIn("s3://", json.dumps(shelf))
        self.assertEqual(
            h100_benchmark_card["schema_version"],
            "compute_bazaar_card_v1",
        )
        self.assertEqual(h100_benchmark_card["card_type"], "gpu_benchmark")
        self.assertEqual(h100_prime_card["card_type"], "prime_frontier_offer_market")
        self.assertEqual(h100_prime_card["data"]["family_id"], "H100")
        self.assertEqual(capacity_card["card_type"], "compute_market_state")
        self.assertNotIn("s3://", json.dumps(h100_prime_card))
        self.assertIn(
            "prime_frontier_offer_market",
            export["output_refs"],
        )
        self.assertIn(
            "prime_frontier_offer_shelf",
            export["output_refs"],
        )
        self.assertEqual(reference_query["query"]["engine"], "datafusion")
        self.assertEqual(
            {row["gpu_family_id"] for row in reference_query["rows"]},
            {"H100", "H200", "B300"},
        )
        self.assertTrue(
            any(row["is_market_benchmark_level"] for row in ladder_query["rows"])
        )

    def test_market_state_history_accumulates_without_rewriting_prior_rows(
        self,
    ) -> None:
        first_observed = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        second_observed = datetime(2026, 7, 25, 13, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            dashboard_root = str(Path(tmpdir) / "dashboard")
            offer = _offer(
                provider="runpod",
                source_offer_id="runpod-h100",
                price_usd_hr=2.5,
                gpu_raw_name="H100",
                gpu_model="H100_80GB",
                vram_gb=80,
            )
            for run_id, observed_at, stock_status in [
                ("runpod-state-1200", first_observed, "Low"),
                ("runpod-state-1300", second_observed, "High"),
            ]:
                state = normalize_runpod_market_state(
                    [
                        {
                            "id": "NVIDIA H100 80GB HBM3",
                            "displayName": "H100",
                            "memoryInGb": 80,
                            "lowestPrice": {
                                "stockStatus": stock_status,
                                "availableGpuCounts": [1, 2, 4, 8],
                            },
                        }
                    ],
                    observed_at=observed_at,
                    raw_ref=f"raw/{run_id}.json",
                )
                _write_provider_run(
                    lake_root=lake_root,
                    raw_root=raw_root,
                    provider="runpod",
                    run_id=run_id,
                    offers=[offer],
                    market_state=state,
                )
                build_gold_market_tables(
                    lake_root=lake_root,
                    providers=["runpod"],
                    run_id=f"gold-{run_id}",
                )

            history = query_gold_market_state_history(lake_root=lake_root)
            export = export_gold_dashboard_snapshot(
                lake_root=lake_root,
                output_root=dashboard_root,
            )
            public_state = read_json(export["output_refs"]["market_state"])
            state_rows = [
                row
                for row in history["rows"]
                if row["provider"] == "runpod" and row["resource_type"] == "H100_80GB"
            ]
            latest = read_latest_gold_manifest(lake_root)

        self.assertEqual(len(state_rows), 2)
        self.assertEqual(
            {row["stock_status"] for row in state_rows},
            {"Low", "High"},
        )
        self.assertEqual(history["history_manifest_count"], 2)
        self.assertEqual(
            latest["row_counts"]["fact_compute_market_state_history"],
            4,
        )
        self.assertEqual(public_state["current_row_count"], 1)
        self.assertEqual(public_state["history_row_count"], 0)
        self.assertEqual(
            {row["measurement_kind"] for row in public_state["current_rows"]},
            {"availability_pressure"},
        )
        self.assertNotIn("dashboard_output_root", public_state["manifest"])
        self.assertNotIn("s3://", json.dumps(public_state))

    def test_market_state_keeps_prime_but_prefers_matching_direct_source(self) -> None:
        direct_state = normalize_runpod_market_state(
            [
                {
                    "id": "NVIDIA H100 80GB HBM3",
                    "displayName": "H100",
                    "memoryInGb": 80,
                    "lowestPrice": {
                        "stockStatus": "High",
                        "availableGpuCounts": [1, 2, 4, 8],
                    },
                }
            ],
            observed_at=OBSERVED_AT,
            raw_ref="raw/runpod.json",
        )
        aggregate_state = normalize_prime_market_state(
            [
                {
                    "provider": "runpod",
                    "gpuType": "H100_80GB",
                    "gpuMemory": 80,
                    "gpuCount": 8,
                    "stockStatus": "Low",
                }
            ],
            observed_at=OBSERVED_AT,
            raw_ref="raw/prime_intellect.json",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="runpod",
                run_id="runpod-state",
                offers=[
                    _offer(
                        provider="runpod",
                        source_offer_id="runpod-h100",
                        price_usd_hr=2.5,
                        gpu_raw_name="H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    )
                ],
                market_state=direct_state,
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="prime_intellect",
                run_id="prime-state",
                offers=[
                    _offer(
                        provider="runpod",
                        source_connector="prime_intellect",
                        source_offer_id="prime-runpod-h100",
                        price_usd_hr=2.6,
                        gpu_raw_name="H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    )
                ],
                market_state=aggregate_state,
            )

            build = build_gold_market_tables(
                lake_root=lake_root,
                providers=["runpod", "prime_intellect"],
                run_id="gold-market-20260725T120000-1234abcd",
            )
            rows = query_gold_market_state(lake_root=lake_root)["rows"]

        availability = [
            row
            for row in rows
            if row["measurement_kind"] == "availability_pressure"
            and row["provider"] == "runpod"
            and row["resource_type"] == "H100_80GB"
        ]
        self.assertEqual(build.row_counts["fact_compute_market_state"], 4)
        self.assertEqual(len(availability), 2)
        by_connector = {row["source_connector"]: row for row in availability}
        self.assertTrue(by_connector["runpod"]["aggregation_eligible"])
        self.assertFalse(by_connector["prime_intellect"]["aggregation_eligible"])
        self.assertEqual(
            by_connector["prime_intellect"]["aggregation_exclusion_reason"],
            "matching_direct_provider_source",
        )

    def test_provider_comparison_uses_available_offers_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-test",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="vast-unavailable",
                        price_usd_hr=0.10,
                        availability_status="unavailable",
                    ),
                    _offer(
                        provider="vast",
                        source_offer_id="vast-available",
                        price_usd_hr=0.20,
                    ),
                ],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="lium",
                run_id="lium-test",
                offers=[
                    _offer(
                        provider="lium",
                        source_offer_id="lium-available",
                        price_usd_hr=0.30,
                    ),
                ],
            )

            build_gold_market_tables(
                lake_root=lake_root, providers=["vast", "lium"], run_id="gold-test"
            )
            result = query_gold_provider_comparison(
                lake_root=lake_root,
                gpu_model="RTX4090_24GB",
                limit=10,
            )
            constituents = query_gold_index_constituents(
                lake_root=lake_root,
                gpu_model="RTX4090_24GB",
                limit=10,
            )
            listings = query_gold_listings(
                lake_root=lake_root,
                gpu_model="RTX4090_24GB",
                limit=10,
            )

        rows = sorted(result["rows"], key=lambda row: row["provider"])
        self.assertEqual([row["provider"] for row in rows], ["lium", "vast"])
        self.assertEqual(rows[0]["floor_usd_gpu_hr"], 0.30)
        self.assertEqual(rows[1]["floor_usd_gpu_hr"], 0.20)
        self.assertEqual(rows[1]["listing_count"], 1)
        excluded = [
            row
            for row in constituents["rows"]
            if row["listing_id"] == "vast:vast-unavailable"
        ]
        self.assertEqual(len(excluded), 1)
        self.assertFalse(excluded[0]["included"])
        self.assertEqual(excluded[0]["exclusion_reason"], "not_available")
        available_listing = [
            row
            for row in listings["rows"]
            if row["listing_id"] == "vast:vast-available"
        ]
        self.assertEqual(len(available_listing), 1)
        self.assertEqual(available_listing[0]["price_usd_instance_hr"], 0.20)
        self.assertEqual(available_listing[0]["price_usd_gpu_hr"], 0.20)
        self.assertTrue(available_listing[0]["has_raw_evidence"])
        self.assertEqual(
            available_listing[0]["source_run_id"], "vast:vast-test,lium:lium-test"
        )

    def test_market_run_manifest_writes_latest_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            payload = {
                "manifest_version": "v1",
                "table": "market_runs",
                "market_run_id": "market-test",
                "status": "success",
                "checks": {"vast": "ok", "lium": "ok", "gold": "ok"},
            }

            manifest_ref = write_market_run_manifest(
                lake_root=lake_root,
                observed_date="2026-06-17",
                market_run_id="market-test",
                payload=payload,
            )
            latest = read_latest_market_run(lake_root)
            history = list_market_runs(lake_root)

        self.assertEqual(latest["market_run_id"], "market-test")
        self.assertEqual(latest["manifest_ref"], manifest_ref)
        self.assertEqual([row["market_run_id"] for row in history], ["market-test"])
        self.assertTrue(
            manifest_ref.endswith(
                "/_manifests/market_runs/date=2026-06-17/run_id=market-test.json"
            )
        )

    def test_gold_index_history_reads_recent_gold_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-history-1",
                offers=[
                    _offer(provider="vast", source_offer_id="vast-1", price_usd_hr=0.20)
                ],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="lium",
                run_id="lium-history-1",
                offers=[
                    _offer(provider="lium", source_offer_id="lium-1", price_usd_hr=0.30)
                ],
            )
            build_gold_market_tables(
                lake_root=lake_root, providers=["vast", "lium"], run_id="gold-history-1"
            )

            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-history-2",
                offers=[
                    _offer(provider="vast", source_offer_id="vast-2", price_usd_hr=0.40)
                ],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="lium",
                run_id="lium-history-2",
                offers=[
                    _offer(provider="lium", source_offer_id="lium-2", price_usd_hr=0.50)
                ],
            )
            build_gold_market_tables(
                lake_root=lake_root, providers=["vast", "lium"], run_id="gold-history-2"
            )

            history = query_gold_index_history(
                lake_root=lake_root,
                history_limit=10,
                gpu_models=["RTX4090_24GB"],
            )

        rows = history["rows"]
        self.assertEqual(history["history_manifest_count"], 2)
        self.assertEqual(
            {row["gold_run_id"] for row in rows}, {"gold-history-1", "gold-history-2"}
        )
        self.assertEqual({row["gpu_model"] for row in rows}, {"RTX4090_24GB"})
        self.assertEqual({row["floor_usd_gpu_hr"] for row in rows}, {0.20, 0.40})

    def test_gold_benchmark_history_exports_compact_frontier_series(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            dashboard_root = str(Path(tmpdir) / "dashboard")

            for suffix, gold_run_id, price in [
                ("1", "gold-market-20260101T000000-00000001", 2.00),
                ("2", "gold-market-20260101T010000-00000002", 2.50),
            ]:
                _write_provider_run(
                    lake_root=lake_root,
                    raw_root=raw_root,
                    provider="vast",
                    run_id=f"vast-benchmark-history-{suffix}",
                    offers=[
                        _offer(
                            provider="vast",
                            source_offer_id=f"h100-history-{suffix}",
                            price_usd_hr=price,
                            gpu_raw_name="NVIDIA H100",
                            gpu_model="H100_80GB",
                            vram_gb=80,
                        )
                    ],
                )
                build_gold_market_tables(
                    lake_root=lake_root,
                    providers=["vast"],
                    run_id=gold_run_id,
                )
                if suffix == "1":
                    export_gold_dashboard_snapshot(
                        lake_root=lake_root,
                        output_root=dashboard_root,
                        limit=1,
                        benchmark_history_limit=1,
                    )

            history = query_gold_benchmark_history(
                lake_root=lake_root,
                history_limit=10,
            )
            export = export_gold_dashboard_snapshot(
                lake_root=lake_root,
                output_root=dashboard_root,
                limit=1,
                benchmark_history_limit=1,
            )
            public_history = read_json(export["output_refs"]["benchmark_history"])

        h100_rows = [
            row for row in history["rows"] if row["benchmark_family_id"] == "H100"
        ]
        self.assertEqual(history["history_manifest_count"], 2)
        self.assertEqual(
            [row["benchmark_usd_gpu_hr"] for row in h100_rows],
            [2.00, 2.50],
        )
        self.assertEqual(
            {row["gold_run_id"] for row in h100_rows},
            {
                "gold-market-20260101T000000-00000001",
                "gold-market-20260101T010000-00000002",
            },
        )
        self.assertEqual(public_history["history_manifest_count"], 2)
        self.assertEqual(public_history["row_count"], 2)
        self.assertEqual(export["row_counts"]["benchmark_history"], 2)
        self.assertNotIn("source_manifest_ref", public_history["rows"][0])
        self.assertNotIn("source_run_id", public_history["rows"][0])

    def test_gold_benchmark_values_group_frontier_gpu_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            dashboard_root = str(Path(tmpdir) / "dashboard")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-benchmark",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="h100-vast-1",
                        price_usd_hr=1.00,
                        gpu_raw_name="NVIDIA H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    ),
                    _offer(
                        provider="vast",
                        source_offer_id="h100-vast-2",
                        price_usd_hr=2.00,
                        gpu_raw_name="NVIDIA H100 PCIe",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    ),
                ],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="lium",
                run_id="lium-benchmark",
                offers=[
                    _offer(
                        provider="lium",
                        source_offer_id="h100-lium-1",
                        price_usd_hr=3.00,
                        gpu_raw_name="NVIDIA H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    ),
                    _offer(
                        provider="lium",
                        source_offer_id="b200-lium-1",
                        price_usd_hr=12.00,
                        gpu_raw_name="NVIDIA B200",
                        gpu_model="B200_180GB",
                        vram_gb=180,
                    ),
                ],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="gridstackhub",
                run_id="gridstackhub-benchmark",
                offers=[
                    _offer(
                        provider="external_cloud",
                        source_connector="gridstackhub",
                        source_offer_id="h100-external-1",
                        price_usd_hr=0.01,
                        gpu_raw_name="NVIDIA H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                        availability_status="external_reference",
                    ),
                ],
            )

            build = build_gold_market_tables(
                lake_root=lake_root,
                providers=["vast", "lium", "gridstackhub"],
                run_id="gold-market-20260101T000000-00000001",
            )
            values = query_gold_benchmark_values(lake_root=lake_root)
            constituents = query_gold_benchmark_constituents(
                lake_root=lake_root, benchmark_family_id="H100"
            )
            export = export_gold_dashboard_snapshot(
                lake_root=lake_root,
                output_root=dashboard_root,
                limit=1,
            )
            public_benchmarks = read_json(export["output_refs"]["featured_benchmarks"])
            public_constituents = read_json(
                export["output_refs"]["benchmark_constituents"]
            )

        rows = {row["benchmark_family_id"]: row for row in values["rows"]}
        self.assertEqual(build.row_counts["fact_benchmark_values"], 4)
        self.assertEqual(build.row_counts["fact_benchmark_constituents"], 5)
        self.assertEqual(rows["H100"]["status"], "observed")
        self.assertEqual(rows["H100"]["offer_count"], 3)
        self.assertEqual(rows["H100"]["provider_count"], 2)
        self.assertEqual(rows["H100"]["floor_usd_gpu_hr"], 1.00)
        self.assertEqual(rows["H100"]["benchmark_usd_gpu_hr"], 2.00)
        self.assertEqual(rows["B200"]["benchmark_usd_gpu_hr"], 12.00)
        self.assertEqual(rows["H200"]["status"], "not_observed")
        self.assertIsNone(rows["H200"]["benchmark_usd_gpu_hr"])
        self.assertEqual(len(constituents["rows"]), 4)
        self.assertEqual(sum(bool(row["included"]) for row in constituents["rows"]), 2)
        excluded = [row for row in constituents["rows"] if not row["included"]]
        self.assertEqual(
            {row["exclusion_reason"] for row in excluded},
            {"higher_same_provider_offer", "not_currently_available"},
        )
        self.assertIn("featured_benchmarks", export["output_refs"])
        self.assertIn("benchmark_history", export["output_refs"])
        self.assertIn("benchmark_constituents", export["output_refs"])
        self.assertEqual(export["row_counts"]["featured_benchmarks"], 4)
        self.assertEqual(export["row_counts"]["benchmark_history"], 2)
        self.assertEqual(export["row_counts"]["benchmark_constituents"], 5)
        self.assertTrue(public_constituents["complete"])
        self.assertEqual(public_constituents["row_count"], 5)
        self.assertEqual(len(public_constituents["rows"]), 5)
        external_rows = [
            row
            for row in public_constituents["rows"]
            if row["source_connector"] == "gridstackhub"
        ]
        self.assertEqual(len(external_rows), 1)
        self.assertEqual(external_rows[0]["provider"], "external_cloud")
        self.assertFalse(external_rows[0]["included"])
        self.assertNotIn("source_manifest_ref", public_benchmarks["rows"][0])
        self.assertNotIn("source_normalized_ref", public_benchmarks["rows"][0])
        self.assertNotIn("raw_ref", public_constituents["rows"][0])
        self.assertNotIn("source_manifest_ref", public_constituents["rows"][0])
        self.assertNotIn("source_normalized_ref", public_constituents["rows"][0])

    def test_frontier_coverage_keeps_live_spot_and_rate_card_counts_separate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-coverage",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="h100-live-1",
                        price_usd_hr=2,
                        gpu_raw_name="H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                        available_gpu_count=30,
                    ),
                    _offer(
                        provider="vast",
                        source_offer_id="h100-live-2",
                        price_usd_hr=3,
                        gpu_raw_name="H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                        available_gpu_count=25,
                    ),
                ],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="aws_spot",
                run_id="aws-coverage",
                offers=[
                    _offer(
                        provider="aws_spot",
                        source_offer_id="h100-spot",
                        price_usd_hr=4,
                        availability_status="spot_price_observed",
                        gpu_raw_name="H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    )
                ],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="runpod",
                run_id="runpod-coverage",
                offers=[
                    _offer(
                        provider="runpod",
                        source_offer_id="h100-rate",
                        price_usd_hr=5,
                        availability_status="published_rate",
                        gpu_raw_name="H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    )
                ],
            )
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="inference_sh",
                run_id="inference-sh-coverage",
                offers=[
                    _offer(
                        provider="vast",
                        source_connector="inference_sh",
                        source_offer_id="h100-aggregate-copy",
                        price_usd_hr=2.5,
                        gpu_raw_name="H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                        available_gpu_count=10,
                    )
                ],
            )
            build_gold_market_tables(
                lake_root=lake_root,
                providers=["vast", "aws_spot", "runpod", "inference_sh"],
                run_id="gold-coverage",
            )
            coverage = query_frontier_coverage(
                lake_root=lake_root,
                target=2,
                capacity_target=50,
                observation_target=4,
            )

        rows = {row["gpu_family"]: row for row in coverage["rows"]}
        self.assertEqual(rows["H100"]["live_offer_count"], 3)
        self.assertEqual(rows["H100"]["live_gpu_capacity_lower_bound"], 55)
        self.assertEqual(rows["H100"]["live_on_demand_offer_count"], 3)
        self.assertEqual(rows["H100"]["live_spot_offer_count"], 0)
        self.assertEqual(rows["H100"]["spot_price_observation_count"], 1)
        self.assertEqual(rows["H100"]["published_rate_count"], 1)
        self.assertEqual(rows["H100"]["current_observation_count"], 5)
        self.assertTrue(rows["H100"]["target_met"])
        self.assertTrue(rows["H100"]["capacity_target_met"])
        self.assertEqual(rows["H100"]["capacity_shortfall_to_target"], 0)
        self.assertTrue(rows["H100"]["observation_target_met"])
        self.assertEqual(rows["H100"]["observation_shortfall_to_target"], 0)
        self.assertEqual(rows["B300"]["shortfall_to_target"], 2)
        self.assertEqual(rows["B300"]["capacity_shortfall_to_target"], 50)
        self.assertEqual(rows["B300"]["observation_shortfall_to_target"], 4)

    def test_featured_index_keeps_frontier_gpus_and_last_seen_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            dashboard_root = str(Path(tmpdir) / "dashboard")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-frontier-1",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="h200-old",
                        price_usd_hr=7.60,
                        gpu_raw_name="NVIDIA H200",
                        gpu_model="H200_141GB",
                        vram_gb=141,
                    )
                ],
            )
            build_gold_market_tables(
                lake_root=lake_root, providers=["vast"], run_id="gold-frontier-1"
            )

            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-frontier-2",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="h100-latest",
                        price_usd_hr=1.25,
                        gpu_raw_name="NVIDIA H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    )
                ],
            )
            build_gold_market_tables(
                lake_root=lake_root, providers=["vast"], run_id="gold-frontier-2"
            )

            featured = query_gold_featured_index(
                lake_root=lake_root,
                products=[
                    {"gpu_model": "H100_80GB", "label": "H100"},
                    {"gpu_model": "H200_141GB", "label": "H200"},
                ],
                history_limit=10,
            )
            export = export_gold_dashboard_snapshot(
                lake_root=lake_root,
                output_root=dashboard_root,
                limit=1,
            )

        rows = {row["gpu_model"]: row for row in featured["rows"]}
        self.assertEqual(rows["H100_80GB"]["status"], "observed_latest")
        self.assertTrue(rows["H100_80GB"]["is_latest"])
        self.assertEqual(rows["H100_80GB"]["floor_usd_gpu_hr"], 1.25)
        self.assertEqual(rows["H200_141GB"]["status"], "not_present_latest")
        self.assertFalse(rows["H200_141GB"]["is_latest"])
        self.assertIsNone(rows["H200_141GB"]["floor_usd_gpu_hr"])
        self.assertEqual(rows["H200_141GB"]["last_seen_floor_usd_gpu_hr"], 7.60)
        self.assertIn("featured_index", export["output_refs"])
        self.assertEqual(export["row_counts"]["featured_index"], 4)

    def test_operator_saved_queries_run_against_latest_gold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-operator",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="h100-operator",
                        price_usd_hr=2.00,
                        gpu_raw_name="NVIDIA H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    )
                ],
            )
            build_gold_market_tables(
                lake_root=lake_root, providers=["vast"], run_id="gold-operator"
            )

            catalog = list_operator_queries(lake_root=lake_root)
            values = run_operator_query(
                lake_root=lake_root, query_id="benchmark_values", limit=10
            )
            constituents = run_operator_query(
                lake_root=lake_root, query_id="benchmark_constituents", limit=10
            )
            counts = run_operator_query(
                lake_root=lake_root, query_id="gold_table_counts", limit=20
            )
            scratch = run_operator_sql(
                lake_root=lake_root,
                sql="""
                select
                  benchmark_family_id,
                  benchmark_usd_gpu_hr
                from fact_benchmark_values
                order by benchmark_family_id
                """,
                limit=2,
            )
            lineage = trace_operator_row(
                lake_root=lake_root,
                query_id="benchmark_constituents",
                row=constituents["rows"][0],
            )
            preview = preview_operator_ref(
                lake_root=lake_root,
                ref=f"{raw_root}/provider=vast/date=2026-06-17/run_id=vast-operator/offers.json",
            )
            sql_preview = preview_operator_ref(
                lake_root=lake_root,
                ref="queries/curia/benchmark_constituents_v0.sql",
            )
            with self.assertRaises(PermissionError):
                preview_operator_ref(
                    lake_root=lake_root, ref=f"{raw_root}/not-in-manifest.json"
                )
            with self.assertRaises(ValueError):
                run_operator_sql(
                    lake_root=lake_root, sql="drop table fact_gpu_listings"
                )
            with self.assertRaises(ValueError):
                run_operator_sql(
                    lake_root=lake_root,
                    sql="select * from fact_gpu_listings; select * from dim_providers",
                )
            with self.assertRaises(ValueError):
                run_operator_sql(
                    lake_root=lake_root,
                    sql="select * from read_parquet('s3://bucket/elsewhere')",
                )

        self.assertEqual(catalog["manifest"]["run_id"], "gold-operator")
        catalog_rows = {query["query_id"]: query for query in catalog["queries"]}
        self.assertIn("benchmark_values", catalog_rows)
        self.assertEqual(catalog_rows["benchmark_values"]["version"], "v0")
        self.assertEqual(catalog_rows["benchmark_values"]["engine"], "datafusion")
        self.assertEqual(
            catalog_rows["benchmark_values"]["sql_path"],
            "queries/curia/benchmark_values_v0.sql",
        )
        self.assertEqual(len(catalog_rows["benchmark_values"]["query_hash"]), 64)
        self.assertTrue(catalog_rows["benchmark_values"]["available"])
        self.assertTrue(catalog_rows["compute_market_state"]["available"])
        self.assertFalse(catalog_rows["compute_price_cross_section"]["available"])
        self.assertFalse(catalog_rows["sandbox_workload_costs"]["available"])
        self.assertEqual(
            values["query"]["sql_path"], "queries/curia/benchmark_values_v0.sql"
        )
        self.assertEqual(values["query"]["version"], "v0")
        benchmark_rows = {row["benchmark_family_id"]: row for row in values["rows"]}
        self.assertEqual(benchmark_rows["H100"]["benchmark_usd_gpu_hr"], 2.00)
        self.assertEqual(scratch["query"]["query_id"], "scratch_sql")
        self.assertEqual(scratch["query"]["engine"], "datafusion")
        self.assertTrue(scratch["query"]["read_only"])
        self.assertIn("fact_benchmark_values", scratch["query"]["tables"])
        self.assertEqual(scratch["limit"], 2)
        self.assertEqual(len(scratch["rows"]), 2)
        table_counts = {row["table_name"]: row["row_count"] for row in counts["rows"]}
        self.assertEqual(table_counts["fact_gpu_listings"], 1)
        self.assertEqual(table_counts["fact_benchmark_values"], 4)
        self.assertEqual(
            [step["layer"] for step in lineage["trajectory"]],
            ["bronze", "silver", "curia", "gold"],
        )
        self.assertEqual(lineage["row_refs"]["provider"], "vast")
        self.assertEqual(
            lineage["provider_runs"][0]["raw_ref"],
            f"{raw_root}/provider=vast/date=2026-06-17/run_id=vast-operator/offers.json",
        )
        self.assertIn("fact_benchmark_constituents", lineage["gold"]["table_refs"])
        self.assertEqual(preview["kind"], "json")
        self.assertEqual(preview["json_summary"]["type"], "array")
        self.assertEqual(preview["json_summary"]["item_count"], 1)
        self.assertEqual(sql_preview["kind"], "sql")
        self.assertIn("fact_benchmark_constituents", sql_preview["text"])

    def test_operator_composes_gpu_vm_and_sandbox_gold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lake_root = str(Path(tmpdir) / "lake")
            raw_root = str(Path(tmpdir) / "raw")
            _write_provider_run(
                lake_root=lake_root,
                raw_root=raw_root,
                provider="vast",
                run_id="vast-operator-combined",
                offers=[
                    _offer(
                        provider="vast",
                        source_offer_id="h100-operator-combined",
                        price_usd_hr=2.00,
                        gpu_raw_name="NVIDIA H100",
                        gpu_model="H100_80GB",
                        vram_gb=80,
                    )
                ],
            )
            build_gold_market_tables(
                lake_root=lake_root,
                providers=["vast"],
                run_id="gold-operator-combined",
            )
            gpu_manifest_ref = read_latest_gold_manifest(lake_root)["manifest_ref"]

            sandbox_root = f"{lake_root}/sandbox_cost"
            vm_ref = f"{sandbox_root}/gold/vm-capacity-expanded-current.parquet"
            rates_ref = f"{sandbox_root}/gold/sandbox-current-rates.parquet"
            workload_ref = (
                f"{sandbox_root}/gold/sandbox-workload-service-summary.parquet"
            )
            write_parquet_rows(
                vm_ref,
                [
                    {
                        "plan_label": "Example VM",
                        "provider_label": "Example Cloud",
                        "price_usd_per_hour": 0.08,
                        "billing_mode": "public hourly offer",
                        "checked_at": "2026-07-26T10:00:00+00:00",
                        "source_url": "https://example.test/vm",
                        "methodology_version": "vm_v1",
                    }
                ],
            )
            write_parquet_rows(
                rates_ref,
                [
                    {
                        "series_label": "Example Sandbox",
                        "price_usd_per_hour": 0.40,
                        "billing_basis_label": "allocated CPU and memory",
                        "observed_date": "2026-07-24",
                        "source_url": "https://example.test/sandbox",
                    }
                ],
            )
            write_parquet_rows(
                workload_ref,
                [
                    {
                        "series_label": "Example Sandbox",
                        "median_estimated_cost_usd": 0.02,
                        "p25_estimated_cost_usd": 0.018,
                        "p75_estimated_cost_usd": 0.022,
                        "median_runtime_seconds": 180.0,
                        "p25_runtime_seconds": 170.0,
                        "p75_runtime_seconds": 190.0,
                        "result_count": 12,
                        "source_replicate_slot_count": 12,
                        "incomplete_replicate_count": 0,
                        "replicate_completion_ratio": 1.0,
                        "benchmark_run_id": "example-run",
                        "methodology_id": "example-methodology",
                        "latest_generated_at": "2026-07-23T16:40:10Z",
                    }
                ],
            )
            sandbox_manifest_ref = f"{sandbox_root}/_manifests/sandbox_cost/latest.json"
            write_json(
                sandbox_manifest_ref,
                {
                    "manifest_version": "sandbox_cost_gold_v5",
                    "manifest_ref": sandbox_manifest_ref,
                    "build_id": "sandbox-cost-operator",
                    "built_at": "2026-07-26T10:00:00+00:00",
                    "bronze_refs": {
                        "source_manifest": f"{sandbox_root}/bronze/source-manifest.json"
                    },
                    "silver_refs": {"rates": f"{sandbox_root}/silver/rates.parquet"},
                    "table_refs": {
                        "vm_capacity_expanded_current": vm_ref,
                        "sandbox_current_rates": rates_ref,
                        "sandbox_workload_service_summary": workload_ref,
                    },
                    "row_counts": {
                        "vm_capacity_expanded_current": 1,
                        "sandbox_current_rates": 1,
                        "sandbox_workload_service_summary": 1,
                    },
                },
            )

            catalog = list_operator_queries(lake_root=lake_root)
            cross_section = run_operator_query(
                lake_root=lake_root,
                query_id="compute_price_cross_section",
                limit=20,
            )
            workload = run_operator_query(
                lake_root=lake_root,
                query_id="sandbox_workload_costs",
                limit=20,
            )
            scratch = run_operator_sql(
                lake_root=lake_root,
                sql="select series_label from sandbox_current_rates",
                limit=10,
            )
            lineage = trace_operator_row(
                lake_root=lake_root,
                query_id="sandbox_workload_costs",
                row=workload["rows"][0],
            )
            cross_section_lineage = trace_operator_row(
                lake_root=lake_root,
                query_id="compute_price_cross_section",
                row=cross_section["rows"][0],
            )

        catalog_rows = {query["query_id"]: query for query in catalog["queries"]}
        self.assertTrue(catalog_rows["compute_price_cross_section"]["available"])
        self.assertTrue(catalog_rows["sandbox_workload_costs"]["available"])
        self.assertEqual(catalog["manifest"]["gpu_table_count"], 10)
        self.assertEqual(catalog["manifest"]["sandbox_table_count"], 3)
        self.assertEqual(
            {row["market_layer"] for row in cross_section["rows"]},
            {"gpu_benchmark", "vm_offer", "managed_sandbox"},
        )
        self.assertEqual(workload["rows"][0]["median_runtime_seconds"], 180.0)
        self.assertEqual(scratch["rows"], [{"series_label": "Example Sandbox"}])
        self.assertEqual(lineage["provider_runs"], [])
        self.assertEqual(lineage["gold"]["component"], "sandbox")
        self.assertEqual(
            lineage["gold"]["component_runs"],
            {"sandbox": "sandbox-cost-operator"},
        )
        self.assertEqual(
            lineage["gold"]["manifest_refs"],
            [sandbox_manifest_ref],
        )
        self.assertEqual(cross_section_lineage["gold"]["component"], "combined")
        self.assertEqual(
            cross_section_lineage["gold"]["component_runs"],
            {
                "gpu": "gold-operator-combined",
                "sandbox": "sandbox-cost-operator",
            },
        )
        self.assertEqual(
            cross_section_lineage["gold"]["manifest_refs"],
            [gpu_manifest_ref, sandbox_manifest_ref],
        )
        self.assertIn(
            f"{sandbox_root}/bronze/source-manifest.json",
            lineage["trajectory"][0]["refs"],
        )

    def test_market_run_keeps_partial_snapshot_when_one_provider_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_root = f"{tmp}/raw"
            lake_root = f"{tmp}/lake"
            dashboard_root = f"{tmp}/dashboard"

            result = run_market_hourly(
                raw_root=raw_root,
                lake_root=lake_root,
                dashboard_output_root=dashboard_root,
                providers=["crusoe", "unsupported-provider"],
                run_id="market-partial",
                dry_run=True,
            )
            latest = read_latest_market_run(lake_root)
            public_latest = read_json(f"{dashboard_root}/market-run.json")
            sandbox_public = read_json(f"{dashboard_root}/sandbox-cost.json")
            sandbox_relative = read_json(
                result.dashboard_output_refs["sandbox_relative"]
            )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.successful_providers, ["crusoe"])
        self.assertEqual(result.failed_providers, ["unsupported-provider"])
        self.assertEqual(result.checks["crusoe"], "ok")
        self.assertEqual(result.checks["unsupported-provider"], "error")
        self.assertEqual(latest["successful_providers"], ["crusoe"])
        self.assertEqual(latest["failed_providers"], ["unsupported-provider"])
        self.assertEqual(public_latest["successful_providers"], ["crusoe"])
        self.assertEqual(public_latest["failed_providers"], ["unsupported-provider"])
        self.assertGreater(result.row_counts["listings"], 0)
        self.assertEqual(result.checks["sandbox_cost"], "warning")
        self.assertEqual(result.row_counts["sandbox_price_observations"], 33)
        self.assertEqual(result.row_counts["sandbox_benchmark_results"], 72)
        self.assertEqual(
            result.dashboard_output_refs["sandbox_cost"],
            f"{dashboard_root}/sandbox-cost.json",
        )
        self.assertEqual(
            result.dashboard_output_refs["sandbox_relative"],
            f"{dashboard_root}/sandbox/relative.json",
        )
        self.assertEqual(
            sandbox_relative["card_type"],
            "compute_relative_prices",
        )
        self.assertEqual(
            sandbox_public["manifest"]["row_counts"]["sandbox_hourly_price_series"],
            33,
        )
        self.assertEqual(sandbox_public["workload"]["source_batch_count"], 8)


def _offer(
    *,
    provider: str,
    source_offer_id: str,
    price_usd_hr: float,
    availability_status: str = "available",
    gpu_raw_name: str = "RTX 4090",
    gpu_model: str = "RTX4090_24GB",
    vram_gb: float = 24,
    available_gpu_count: int | None = None,
    source_connector: str | None = None,
    observed_at: datetime = OBSERVED_AT,
    gpu_count: int = 1,
    is_spot: bool | None = None,
    is_secure: bool | None = None,
    gpu_socket: str | None = None,
    stock_status: str | None = None,
    price_is_variable: bool | None = None,
    minimum_executable_price_usd_hr: float | None = None,
    required_resource_price_usd_hr: float | None = None,
    price_basis: str | None = None,
) -> GpuOffer:
    return GpuOffer(
        provider=provider,
        source_offer_id=source_offer_id,
        observed_at=observed_at,
        gpu_raw_name=gpu_raw_name,
        gpu_model=gpu_model,
        gpu_count=gpu_count,
        vram_gb=vram_gb,
        price_usd_hr=price_usd_hr,
        available_gpu_count=available_gpu_count,
        source_connector=source_connector,
        country="US",
        region="California",
        is_spot=is_spot,
        is_secure=is_secure,
        availability_status=availability_status,
        raw_ref=f"raw/{provider}.json",
        gpu_socket=gpu_socket,
        stock_status=stock_status,
        price_is_variable=price_is_variable,
        minimum_executable_price_usd_hr=minimum_executable_price_usd_hr,
        required_resource_price_usd_hr=required_resource_price_usd_hr,
        price_basis=price_basis,
    )


def _write_provider_run(
    *,
    lake_root: str,
    raw_root: str,
    provider: str,
    run_id: str,
    offers: list[GpuOffer],
    market_state: list[ComputeMarketState] | None = None,
    observed_at: datetime = OBSERVED_AT,
) -> None:
    observed_date = observed_at.date().isoformat()
    raw_ref = f"{raw_root}/provider={provider}/date={observed_date}/run_id={run_id}/offers.json"
    normalized_ref = f"{lake_root}/silver/gpu_offers/date={observed_date}/provider={provider}/run_id={run_id}/offers.parquet"
    manifest_ref = f"{lake_root}/_manifests/gpu_offers/provider={provider}/date={observed_date}/run_id={run_id}.json"
    latest_ref = f"{lake_root}/_manifests/gpu_offers/provider={provider}/latest.json"
    market_state_ref = (
        f"{lake_root}/silver/compute_market_state/date={observed_date}/"
        f"provider={provider}/run_id={run_id}/observations.parquet"
        if market_state
        else None
    )
    manifest = {
        "manifest_version": "v1",
        "table": "gpu_offers",
        "provider": provider,
        "run_id": run_id,
        "observed_at": observed_at.isoformat(),
        "raw_ref": raw_ref,
        "normalized_ref": normalized_ref,
        "raw_offer_count": len(offers),
        "normalized_offer_count": len(offers),
        "published_events": len(offers) + 1,
        "publish_mode": "test",
        "unknown_gpu_names": [],
        "market_state_ref": market_state_ref,
        "market_state_observation_count": len(market_state or []),
        "manifest_ref": manifest_ref,
    }
    write_json(raw_ref, [offer.to_dict() for offer in offers])
    write_offers_parquet(normalized_ref, offers)
    if market_state_ref:
        write_parquet_rows(
            market_state_ref,
            [
                {
                    **observation.to_dict(),
                    "source_run_id": run_id,
                    "source_manifest_ref": manifest_ref,
                    "source_normalized_ref": normalized_ref,
                    "source_market_state_ref": market_state_ref,
                }
                for observation in market_state or []
            ],
        )
    write_json(manifest_ref, manifest)
    write_json(latest_ref, manifest)


class _FakeSession:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, object],
        headers: dict[str, str],
        timeout: int,
    ) -> "_FakeResponse":
        self.calls.append(
            {
                "method": "GET",
                "url": url,
                "params": dict(params),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        return _FakeResponse(self.payloads[len(self.calls) - 1])

    def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
        timeout: int,
        params: dict[str, object] | None = None,
    ) -> "_FakeResponse":
        call: dict[str, object] = {
            "method": "POST",
            "url": url,
            "json": dict(json),
            "headers": dict(headers),
            "timeout": timeout,
        }
        if params is not None:
            call["params"] = dict(params)
        self.calls.append(call)
        return _FakeResponse(self.payloads[len(self.calls) - 1])


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload

    @property
    def text(self) -> str:
        if isinstance(self.payload, str):
            return self.payload
        raise TypeError("Fake response payload is not text")


class _FakeBotoSession:
    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def client(self, service_name: str, *, region_name: str) -> "_FakeEc2Client":
        self.calls.append({"service_name": service_name, "region_name": region_name})
        return _FakeEc2Client(self.responses[region_name])


class _FakeEc2Client:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    def describe_spot_price_history(self, **kwargs: object) -> dict[str, object]:
        return self.response


if __name__ == "__main__":
    unittest.main()
