import json
import tempfile
import unittest
from pathlib import Path

from the_compute_bazaar.prices.storage import read_parquet_rows
from the_compute_bazaar.sandbox_cost.pipeline import (
    build_sandbox_cost,
    query_sandbox_gold,
)
from the_compute_bazaar.sandbox_cost.vm_capacity import (
    refresh_vm_capacity_sources,
    validate_vm_capacity_history,
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

    def get(self, url: str, **_: object) -> _Response:
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
        raise AssertionError(f"Unexpected URL {url}")


class VmCapacityRefreshTests(unittest.TestCase):
    def test_refresh_deduplicates_unchanged_checks_and_retains_raw_sources(
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
            history = read_parquet_rows(first.history_ref)
            current = read_parquet_rows(first.current_ref)
            raw_manifests = list(
                (root / "raw").rglob("provider=*/date=*/run_id=*/manifest.json")
            )
            summary = validate_vm_capacity_history(
                history_ref=first.history_ref,
                current_ref=first.current_ref,
            )

        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "ok")
        self.assertEqual(len(history), 4)
        self.assertEqual({row["observation_count"] for row in current}, {2})
        self.assertEqual(
            {row["last_observed_at"] for row in current},
            {"2026-07-25T10:00:00+00:00"},
        )
        self.assertEqual(len(raw_manifests), 8)
        self.assertEqual(summary["history_event_count"], 4)
        self.assertTrue(summary["cohort_complete"])

    def test_changed_offer_appends_one_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = f"{tmpdir}/lake"
            raw_root = f"{tmpdir}/raw"
            first = refresh_vm_capacity_sources(
                output_root=output_root,
                raw_root=raw_root,
                observed_at="2026-07-25T09:00:00Z",
                session=_Session(),
            )
            refresh_vm_capacity_sources(
                output_root=output_root,
                raw_root=raw_root,
                observed_at="2026-07-25T10:00:00Z",
                session=_Session(vultr_price=0.06),
            )
            history = read_parquet_rows(first.history_ref)

        vultr = [row for row in history if row["provider_id"] == "vultr"]
        self.assertEqual(len(history), 5)
        self.assertEqual([row["event_order"] for row in vultr], [1, 2])
        self.assertEqual(vultr[-1]["price_usd_per_hour"], 0.06)

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


class VmCapacityGoldTests(unittest.TestCase):
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
            result = build_sandbox_cost(
                output_root=str(root / "publication-lake"),
                dashboard_output_root=str(root / "dashboard"),
                vm_capacity_history_ref=source.history_ref,
                vm_capacity_current_ref=source.current_ref,
                vm_capacity_manifest_ref=source.manifest_ref,
            )
            public = json.loads((root / "dashboard" / "sandbox-cost.json").read_text())
            fixed = query_sandbox_gold(
                output_root=str(root / "publication-lake"),
                query_id="vm-fixed-rate",
            )

        self.assertEqual(
            public["manifest"]["manifest_version"],
            "sandbox_cost_gold_v4",
        )
        self.assertEqual(result.row_counts["vm_capacity_current"], 4)
        self.assertEqual(result.row_counts["vm_capacity_fixed_rate"], 1)
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
            ["linode", "vultr", "scaleway", "azure"],
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
