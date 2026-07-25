import json
import tempfile
import unittest
from pathlib import Path

from the_compute_bazaar.prices.storage import (
    LeaseBusyError,
    exclusive_lease,
    read_parquet_rows,
)
from the_compute_bazaar.sandbox_cost.pipeline import (
    build_sandbox_cost,
    query_sandbox_gold,
)
from the_compute_bazaar.sandbox_cost.vm_capacity import (
    refresh_vm_capacity_sources,
    validate_vm_capacity_history,
)
from the_compute_bazaar.sandbox_cost.vm_discovery import (
    refresh_vm_capacity_discovery_sources,
    validate_vm_capacity_discovery_history,
)


class _Response:
    def __init__(
        self,
        payload: dict | None = None,
        *,
        text: str | None = None,
        status_code: int = 200,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(payload)
        self.content = self.text.encode("utf-8")

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("Response is not JSON")
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    def __init__(
        self,
        *,
        vultr_price: float = 0.055,
        vultr_vcpus: int = 4,
    ) -> None:
        self.vultr_price = vultr_price
        self.vultr_vcpus = vultr_vcpus

    def get(self, url: str, **kwargs: object) -> _Response:
        if "api.linode.com" in url:
            return _Response(
                {
                    "data": [
                        {
                            "id": "g6-standard-4",
                            "label": "Linode 8GB",
                            "class": "standard",
                            "vcpus": 4,
                            "memory": 8192,
                            "disk": 163840,
                            "gpus": 0,
                            "price": {"hourly": 0.072},
                        }
                    ]
                }
            )
        if "api.vultr.com" in url:
            return _Response(
                {
                    "plans": [
                        {
                            "id": "vc2-4c-8gb",
                            "vcpu_count": self.vultr_vcpus,
                            "ram": 8192,
                            "disk": 160,
                            "disk_type": "SSD",
                            "hourly_cost": self.vultr_price,
                            "type": "vc2",
                            "locations": ["cdg", "fra"],
                            "cpu_vendor": "Intel",
                            "vcpu_type": "thread",
                            "gpu_brand": "none",
                        }
                    ]
                }
            )
        if "api.scaleway.com" in url:
            return _Response(
                {
                    "products": [
                        {
                            "sku": "/compute/basic3_x4c_8g/run_fr-par-2",
                            "product": "BASIC3-X4C-8G",
                            "price": {
                                "retail_price": {
                                    "currency_code": "EUR",
                                    "units": 0,
                                    "nanos": 79001000,
                                }
                            },
                            "properties": {
                                "hardware": {
                                    "cpu": {
                                        "description": "AMD EPYC 9555P",
                                        "virtual": {"count": 4},
                                    },
                                    "ram": {"size": 8 * 1024**3},
                                }
                            },
                            "unit_of_measure": {"unit": "hour", "size": 1},
                        }
                    ],
                    "total_count": 1,
                }
            )
        if "data-api.ecb.europa.eu" in url:
            return _Response(text="TIME_PERIOD,OBS_VALUE\n2026-07-24,1.1\n")
        if "prices.azure.com" in url:
            return _Response(
                {
                    "Items": [
                        {
                            "armSkuName": "Standard_F4s_v2",
                            "armRegionName": "westeurope",
                            "location": "EU West",
                            "skuName": "F4s v2",
                            "productName": "Virtual Machines FSv2 Series",
                            "type": "Consumption",
                            "unitOfMeasure": "1 Hour",
                            "retailPrice": 0.194,
                            "effectiveStartDate": "2025-10-01T00:00:00Z",
                            "meterId": "meter-f4s-v2",
                            "skuId": "sku-f4s-v2",
                        }
                    ]
                }
            )
        if "eu.api.ovh.com" in url:
            return _Response(
                {
                    "locale": {"currencyCode": "EUR"},
                    "plans": [
                        {
                            "planCode": "d2-8.consumption",
                            "product": "publiccloud-instance",
                            "pricingType": "consumption",
                            "invoiceName": "d2-8",
                            "blobs": {
                                "tags": ["active"],
                                "technical": {
                                    "cpu": {
                                        "cores": 4,
                                        "model": "AMD EPYC",
                                        "frequency": 2.4,
                                    },
                                    "memory": {"size": 8},
                                    "os": {"family": "linux"},
                                    "storage": {
                                        "disks": [{"capacity": 50}],
                                    },
                                },
                            },
                            "pricings": [
                                {
                                    "intervalUnit": "hour",
                                    "interval": 1,
                                    "type": "consumption",
                                    "price": 3_720_000,
                                }
                            ],
                        }
                    ],
                }
            )
        if "apexapps.oracle.com" in url:
            params = kwargs.get("params")
            sku = params.get("partNumber") if isinstance(params, dict) else None
            if sku == "B93113":
                return _Response(_oracle_price("B93113", "OCPU Per Hour", 0.025))
            if sku == "B93114":
                return _Response(_oracle_price("B93114", "Gigabyte Per Hour", 0.0015))
        raise AssertionError(f"Unexpected URL {url}")

    def post(self, url: str, **kwargs: object) -> _Response:
        if "console-api.akash.network" not in url:
            raise AssertionError(f"Unexpected URL {url}")
        payload = kwargs.get("json")
        return _Response(
            {
                "spec": payload,
                "akash": 30.46,
                "aws": 146.29,
                "gcp": 161.77,
                "azure": 175.33,
            }
        )


class _AwsPricingClient:
    def __init__(self, *, price: float = 0.2121) -> None:
        self.price = price

    def get_products(self, **_: object) -> dict:
        product = {
            "product": {
                "sku": "VW5T9CHEU2H26ZET",
                "attributes": {
                    "instanceType": "c7i.xlarge",
                    "regionCode": "eu-west-3",
                    "vcpu": "4",
                    "memory": "8 GiB",
                    "operatingSystem": "Linux",
                    "tenancy": "Shared",
                    "marketoption": "OnDemand",
                    "physicalProcessor": "Intel Xeon Scalable",
                },
            },
            "terms": {
                "OnDemand": {
                    "term": {
                        "effectiveDate": "2026-07-01T00:00:00Z",
                        "priceDimensions": {
                            "hour": {
                                "unit": "Hrs",
                                "beginRange": "0",
                                "endRange": "Inf",
                                "pricePerUnit": {"USD": str(self.price)},
                            }
                        },
                    }
                }
            },
            "version": "20260701000000",
            "publicationDate": "2026-07-01T00:00:00Z",
        }
        return {"PriceList": [json.dumps(product)]}


class _FailingAwsPricingClient:
    def get_products(self, **_: object) -> dict:
        raise RuntimeError("AWS pricing unavailable")


def _oracle_price(part_number: str, metric: str, value: float) -> dict:
    return {
        "lastUpdated": "2026-07-01T00:00:00Z",
        "items": [
            {
                "partNumber": part_number,
                "metricName": metric,
                "serviceCategory": "Compute - Virtual Machine",
                "currencyCodeLocalizations": [
                    {
                        "currencyCode": "USD",
                        "prices": [
                            {
                                "model": "PAY_AS_YOU_GO",
                                "value": value,
                            }
                        ],
                    }
                ],
            }
        ],
    }


class VmCapacityRefreshTests(unittest.TestCase):
    def test_local_publication_lease_rejects_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_ref = str(Path(tmpdir) / "refresh.lock")
            with exclusive_lease(lock_ref):
                with self.assertRaises(LeaseBusyError):
                    with exclusive_lease(lock_ref):
                        self.fail("Overlapping lease should not be acquired")

    def test_refresh_retains_unchanged_hourly_checks_and_raw_sources(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_root = str(root / "lake")
            raw_root = str(root / "raw")
            first = refresh_vm_capacity_sources(
                output_root=output_root,
                raw_root=raw_root,
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
            )
            second = refresh_vm_capacity_sources(
                output_root=output_root,
                raw_root=raw_root,
                observed_at="2026-07-25T10:00:00Z",
                session=_Session(),
            )
            first_history = read_parquet_rows(first.history_ref)
            history = read_parquet_rows(second.history_ref)
            current = read_parquet_rows(second.current_ref)
            raw_manifests = list(
                (root / "raw").rglob("provider=*/date=*/run_id=*/manifest.json")
            )
            summary = validate_vm_capacity_history(
                history_ref=second.history_ref,
                current_ref=second.current_ref,
            )

        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "ok")
        self.assertEqual(len(first_history), 4)
        self.assertNotEqual(first.history_ref, second.history_ref)
        self.assertEqual(len(history), 8)
        self.assertEqual(
            {row["first_observed_at"] for row in current},
            {"2026-07-25T09:00:00+00:00"},
        )
        self.assertEqual({row["observation_count"] for row in current}, {2})
        self.assertEqual(
            {row["last_observed_at"] for row in current},
            {"2026-07-25T10:00:00+00:00"},
        )
        self.assertEqual(len(raw_manifests), 8)
        self.assertEqual(summary["history_event_count"], 8)
        self.assertEqual(summary["history_observation_count"], 8)
        self.assertTrue(summary["cohort_complete"])

    def test_changed_offer_is_retained_in_next_complete_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = f"{tmpdir}/lake"
            raw_root = f"{tmpdir}/raw"
            refresh_vm_capacity_sources(
                output_root=output_root,
                raw_root=raw_root,
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
            )
            second = refresh_vm_capacity_sources(
                output_root=output_root,
                raw_root=raw_root,
                observed_at="2026-07-25T10:00:00Z",
                session=_Session(vultr_price=0.06),
            )
            history = read_parquet_rows(second.history_ref)

        vultr = [row for row in history if row["provider_id"] == "vultr"]
        self.assertEqual(len(history), 8)
        self.assertEqual([row["event_order"] for row in vultr], [1, 2])
        self.assertEqual(vultr[-1]["price_usd_per_hour"], 0.06)

    def test_conflicting_same_timestamp_does_not_replace_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = refresh_vm_capacity_sources(
                output_root=str(root / "lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
            )
            conflict = refresh_vm_capacity_sources(
                output_root=str(root / "lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(vultr_price=0.06),
            )
            history = read_parquet_rows(first.history_ref)
            raw_manifests = list(
                (root / "raw").rglob("provider=*/date=*/run_id=*/manifest.json")
            )

        self.assertEqual(conflict.status, "warning")
        self.assertEqual(conflict.failed_providers, ["vultr"])
        self.assertEqual(conflict.history_ref, first.history_ref)
        self.assertEqual(conflict.manifest_ref, first.manifest_ref)
        self.assertEqual(len(history), 4)
        self.assertEqual(len(raw_manifests), 4)
        vultr = next(row for row in history if row["provider_id"] == "vultr")
        self.assertEqual(vultr["price_usd_per_hour"], 0.055)

    def test_provider_shape_drift_isolated_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = refresh_vm_capacity_sources(
                output_root=str(root / "lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(vultr_vcpus=8),
            )
            manifest = json.loads(Path(result.manifest_ref).read_text())
            raw_capture = list(
                (root / "raw").rglob("provider=vultr/date=*/run_id=*/vultr-plans.json")
            )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.failed_providers, ["vultr"])
        self.assertEqual(result.current_member_count, 3)
        self.assertIn("machine shape drifted", manifest["errors"]["vultr"]["message"])
        self.assertEqual(len(raw_capture), 1)
        self.assertTrue(manifest["source_checks"]["vultr"]["raw_refs"])


class VmCapacityDiscoveryTests(unittest.TestCase):
    def test_discovery_retains_every_hour_and_keeps_marketplace_separate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = refresh_vm_capacity_discovery_sources(
                output_root=str(root / "lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
                aws_pricing_client=_AwsPricingClient(),
            )
            second = refresh_vm_capacity_discovery_sources(
                output_root=str(root / "lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T10:00:00Z",
                session=_Session(),
                aws_pricing_client=_AwsPricingClient(),
            )
            first_history = read_parquet_rows(first.history_ref)
            history = read_parquet_rows(second.history_ref)
            current = read_parquet_rows(second.current_ref)
            summary = validate_vm_capacity_discovery_history(
                history_ref=second.history_ref,
                current_ref=second.current_ref,
            )

        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "ok")
        self.assertEqual(len(first_history), 4)
        self.assertNotEqual(first.history_ref, second.history_ref)
        self.assertEqual(len(history), 8)
        self.assertEqual(
            {row["first_observed_at"] for row in current},
            {"2026-07-25T09:00:00+00:00"},
        )
        self.assertEqual(len(current), 4)
        self.assertEqual(summary["history_event_count"], 8)
        self.assertEqual(summary["history_observation_count"], 8)
        self.assertEqual(
            {
                row["source_id"]
                for row in current
                if row["source_class"] == "direct_vendor_offer"
            },
            {"aws", "ovhcloud", "oracle_cloud"},
        )
        akash = next(row for row in current if row["source_id"] == "akash")
        self.assertEqual(akash["source_class"], "marketplace_indication")
        self.assertFalse(akash["benchmark_eligible"])
        self.assertFalse(akash["executable_offer"])

    def test_discovery_same_timestamp_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = refresh_vm_capacity_discovery_sources(
                output_root=f"{tmpdir}/lake",
                raw_root=f"{tmpdir}/raw",
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
                aws_pricing_client=_AwsPricingClient(),
            )
            refresh_vm_capacity_discovery_sources(
                output_root=f"{tmpdir}/lake",
                raw_root=f"{tmpdir}/raw",
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
                aws_pricing_client=_AwsPricingClient(),
            )
            history = read_parquet_rows(first.history_ref)

        self.assertEqual(len(history), 4)

    def test_discovery_conflict_does_not_replace_same_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = refresh_vm_capacity_discovery_sources(
                output_root=str(root / "lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
                aws_pricing_client=_AwsPricingClient(),
            )
            conflict = refresh_vm_capacity_discovery_sources(
                output_root=str(root / "lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
                aws_pricing_client=_AwsPricingClient(price=0.25),
            )
            history = read_parquet_rows(first.history_ref)
            raw_manifests = list(
                (root / "raw").rglob("source=*/date=*/run_id=*/manifest.json")
            )

        self.assertEqual(conflict.status, "warning")
        self.assertEqual(conflict.failed_sources, ["aws"])
        self.assertEqual(conflict.history_ref, first.history_ref)
        self.assertEqual(conflict.manifest_ref, first.manifest_ref)
        self.assertEqual(len(history), 4)
        self.assertEqual(len(raw_manifests), 4)
        aws = next(row for row in history if row["source_id"] == "aws")
        self.assertEqual(aws["price_usd_per_hour"], 0.2121)


class VmCapacityGoldTests(unittest.TestCase):
    def test_incomplete_expansion_keeps_legacy_cohort_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = refresh_vm_capacity_sources(
                output_root=str(root / "source-lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
            )
            discovery = refresh_vm_capacity_discovery_sources(
                output_root=str(root / "source-lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
                aws_pricing_client=_FailingAwsPricingClient(),
            )
            result = build_sandbox_cost(
                output_root=str(root / "publication-lake"),
                dashboard_output_root=str(root / "dashboard"),
                vm_capacity_history_ref=source.history_ref,
                vm_capacity_current_ref=source.current_ref,
                vm_capacity_manifest_ref=source.manifest_ref,
                vm_discovery_history_ref=discovery.history_ref,
                vm_discovery_current_ref=discovery.current_ref,
                vm_discovery_manifest_ref=discovery.manifest_ref,
            )
            public = json.loads((root / "dashboard" / "sandbox-cost.json").read_text())

        self.assertEqual(discovery.status, "warning")
        self.assertEqual(result.row_counts["vm_capacity_expanded_current"], 6)
        self.assertEqual(result.row_counts["vm_capacity_expanded_rate"], 0)
        self.assertEqual(public["vm_capacity"]["cohort_id"], "public_vm_4vcpu_8gib_v1")
        self.assertEqual(len(public["vm_capacity"]["current_cross_section"]), 4)
        self.assertEqual(len(public["vm_capacity"]["observed_market_rate"]), 1)
        self.assertEqual(len(public["vm_capacity"]["marketplace_indications"]), 1)

    def test_datafusion_build_publishes_fixed_cohort_without_private_refs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = refresh_vm_capacity_sources(
                output_root=str(root / "source-lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
            )
            source = refresh_vm_capacity_sources(
                output_root=str(root / "source-lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T10:00:00Z",
                session=_Session(),
            )
            discovery = refresh_vm_capacity_discovery_sources(
                output_root=str(root / "source-lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
                aws_pricing_client=_AwsPricingClient(),
            )
            discovery = refresh_vm_capacity_discovery_sources(
                output_root=str(root / "source-lake"),
                raw_root=str(root / "raw"),
                observed_at="2026-07-25T10:00:00Z",
                session=_Session(),
                aws_pricing_client=_AwsPricingClient(),
            )
            result = build_sandbox_cost(
                output_root=str(root / "publication-lake"),
                dashboard_output_root=str(root / "dashboard"),
                vm_capacity_history_ref=source.history_ref,
                vm_capacity_current_ref=source.current_ref,
                vm_capacity_manifest_ref=source.manifest_ref,
                vm_discovery_history_ref=discovery.history_ref,
                vm_discovery_current_ref=discovery.current_ref,
                vm_discovery_manifest_ref=discovery.manifest_ref,
            )
            public = json.loads((root / "dashboard" / "sandbox-cost.json").read_text())
            fixed = query_sandbox_gold(
                output_root=str(root / "publication-lake"),
                query_id="vm-fixed-rate",
            )
            observed = query_sandbox_gold(
                output_root=str(root / "publication-lake"),
                query_id="vm-observed-rate",
            )

        self.assertEqual(
            public["manifest"]["manifest_version"],
            "sandbox_cost_gold_v5",
        )
        self.assertEqual(result.row_counts["vm_capacity_current"], 4)
        self.assertEqual(result.row_counts["vm_capacity_fixed_rate"], 2)
        self.assertEqual(result.row_counts["vm_capacity_expanded_current"], 7)
        self.assertEqual(result.row_counts["vm_capacity_expanded_rate"], 2)
        self.assertEqual(result.row_counts["vm_capacity_marketplace_current"], 1)
        self.assertEqual(
            result.row_counts["vm_sandbox_current_comparison"],
            1,
        )
        self.assertAlmostEqual(
            fixed["rows"][0]["median_usd_per_hour"],
            (0.072 + 0.079001 * 1.1) / 2,
        )
        self.assertEqual(
            public["vm_capacity"]["fixed_members"],
            [
                "linode",
                "vultr",
                "scaleway",
                "azure",
                "aws",
                "ovhcloud",
                "oracle_cloud",
            ],
        )
        self.assertEqual(len(public["vm_capacity"]["current_cross_section"]), 7)
        self.assertEqual(len(public["vm_capacity"]["marketplace_indications"]), 1)
        self.assertEqual(len(public["vm_capacity"]["observed_market_rate"]), 2)
        self.assertEqual(len(public["vm_capacity"]["fixed_cohort_rate"]), 2)
        self.assertEqual(len(public["vm_capacity"]["legacy_fixed_cohort_rate"]), 2)
        self.assertEqual(
            public["vm_capacity"]["fixed_cohort_rate"],
            public["vm_capacity"]["observed_market_rate"],
        )
        self.assertNotEqual(
            public["vm_capacity"]["fixed_cohort_rate"],
            public["vm_capacity"]["legacy_fixed_cohort_rate"],
        )
        self.assertAlmostEqual(
            observed["rows"][0]["median_usd_per_hour"],
            0.072,
        )
        self.assertEqual(observed["rows"][0]["base_100"], 100.0)
        self.assertEqual(
            observed["rows"][0]["base_observed_at"].isoformat(),
            "2026-07-25T09:00:00",
        )
        self.assertEqual(
            observed["rows"][0]["base_median_usd_per_hour"],
            observed["rows"][0]["median_usd_per_hour"],
        )
        self.assertAlmostEqual(
            observed["rows"][0]["minimum_base_100"],
            observed["rows"][0]["minimum_usd_per_hour"]
            / observed["rows"][0]["median_usd_per_hour"]
            * 100.0,
        )
        self.assertAlmostEqual(
            observed["rows"][0]["maximum_base_100"],
            observed["rows"][0]["maximum_usd_per_hour"]
            / observed["rows"][0]["median_usd_per_hour"]
            * 100.0,
        )
        self.assertTrue(
            all(
                {
                    "base_observed_at",
                    "base_median_usd_per_hour",
                    "base_100",
                    "p25_base_100",
                    "p75_base_100",
                    "minimum_base_100",
                    "maximum_base_100",
                }.issubset(row)
                for row in public["vm_capacity"]["observed_market_rate"]
            )
        )
        serialized = json.dumps(public["vm_capacity"])
        self.assertNotIn("raw_refs_json", serialized)
        self.assertNotIn(str(root / "raw"), serialized)
        self.assertIn(
            "persistent block storage priced separately",
            {
                row["storage_scope"]
                for row in public["vm_capacity"]["current_cross_section"]
            },
        )

    def test_build_requires_history_and_current_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = refresh_vm_capacity_sources(
                output_root=f"{tmpdir}/source",
                raw_root=f"{tmpdir}/raw",
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
            )
            with self.assertRaisesRegex(
                ValueError,
                "history and current refs",
            ):
                build_sandbox_cost(
                    output_root=f"{tmpdir}/publication",
                    vm_capacity_history_ref=source.history_ref,
                )


if __name__ == "__main__":
    unittest.main()
