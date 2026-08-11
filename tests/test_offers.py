from __future__ import annotations

import unittest
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import requests

from the_compute_bazaar.fleet import FleetRegistry
from the_compute_bazaar.offers import OfferService
from the_compute_bazaar.provider_execution import (
    LaunchExecutionError,
    RunpodExecutor,
)
from the_compute_bazaar.provisioning import LaunchPlanner
from the_compute_bazaar.prices.providers.runpod import RunpodClient


class FakeRunpodClient:
    def fetch_live_market(self) -> SimpleNamespace:
        return SimpleNamespace(
            gpu_types=[
                {
                    "id": "NVIDIA H100 80GB HBM3",
                    "displayName": "H100 PCIe",
                    "memoryInGb": 80,
                    "secureCloud": True,
                    "communityCloud": True,
                    "securePrice": 2.49,
                    "communityPrice": 1.99,
                }
            ],
            data_centers=[
                {
                    "id": "EU-RO-1",
                    "name": "EU Romania",
                    "location": "Romania",
                    "gpuAvailability": [
                        {
                            "gpuTypeId": "NVIDIA H100 80GB HBM3",
                            "stockStatus": "High",
                        }
                    ],
                }
            ],
        )


class FakeVerdaClient:
    def fetch_catalog(self) -> SimpleNamespace:
        return SimpleNamespace(
            instance_types=[
                {
                    "instance_type": "1H100.8V",
                    "name": "NVIDIA H100 80GB",
                    "currency": "USD",
                    "price_per_hour": 2.4,
                    "gpu": {"number_of_gpus": 1},
                    "gpu_memory": {"size_in_gigabytes": 80},
                }
            ],
            availability=[
                {
                    "location_code": "FIN-01",
                    "availabilities": ["1H100.8V"],
                }
            ],
        )


class OfferServiceTest(unittest.TestCase):
    def test_display_limit_does_not_truncate_recorded_observations(self) -> None:
        class Ledger:
            batch: Any = None

            def record_offer_observations(self, batch: Any) -> None:
                self.batch = batch

        ledger = Ledger()
        result = OfferService(
            runpod_client=FakeRunpodClient(),
            ledger=ledger,  # type: ignore[arg-type]
        ).list_offers(providers=["runpod"], limit=1)

        self.assertEqual(len(result.observations), 1)
        self.assertEqual(len(ledger.batch.observations), 2)
        self.assertEqual(
            {row.observation_purpose for row in ledger.batch.observations},
            {"interactive"},
        )

    def test_hidden_unavailable_rows_are_still_recorded(self) -> None:
        class Ledger:
            batch: Any = None

            def record_offer_observations(self, batch: Any) -> None:
                self.batch = batch

        class UnavailableRunpodClient(FakeRunpodClient):
            def fetch_live_market(self) -> SimpleNamespace:
                payload = super().fetch_live_market()
                payload.data_centers = []
                return payload

        ledger = Ledger()
        result = OfferService(
            runpod_client=UnavailableRunpodClient(),
            ledger=ledger,  # type: ignore[arg-type]
        ).list_offers(providers=["runpod"])

        self.assertEqual(result.observations, ())
        self.assertEqual(len(ledger.batch.observations), 2)
        self.assertFalse(any(row.available for row in ledger.batch.observations))

    def test_runpod_authentication_never_enters_the_request_url(self) -> None:
        class FailingSession:
            def post(self, url: str, **kwargs: object) -> object:
                self.url = url
                self.kwargs = kwargs
                raise requests.ConnectionError(f"failed at {url}?api_key=secret")

        session = FailingSession()
        client = RunpodClient(api_key="secret", session=session)  # type: ignore[arg-type]

        with self.assertRaisesRegex(RuntimeError, "RunPod API request failed") as error:
            client.fetch_live_market()

        self.assertEqual(session.url, "https://api.runpod.io/graphql")
        self.assertNotIn("secret", str(error.exception))
        self.assertEqual(
            session.kwargs["headers"],
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "Bearer secret",
            },
        )

    def test_runpod_keeps_cloud_and_datacenter_selectors(self) -> None:
        result = OfferService(runpod_client=FakeRunpodClient()).list_offers(
            providers=["runpod"], gpu_model="H100"
        )

        self.assertEqual(len(result.observations), 2)
        secure = next(row for row in result.observations if row.cloud_type == "secure")
        self.assertEqual(secure.location_ids, ("EU-RO-1",))
        self.assertEqual(secure.stock_status, "High")
        self.assertEqual(
            secure.native_selection,
            {
                "provider": "runpod",
                "operation": "create_pod",
                "gpuTypeIds": ["NVIDIA H100 80GB HBM3"],
                "gpuCount": 1,
                "cloudType": "SECURE",
                "dataCenterIds": ["EU-RO-1"],
            },
        )

    def test_verda_keeps_instance_type_and_location(self) -> None:
        result = OfferService(verda_client=FakeVerdaClient()).list_offers(
            providers=["verda"], gpu_model="H100"
        )

        self.assertEqual(len(result.observations), 1)
        offer = result.observations[0]
        self.assertEqual(offer.location, "FIN-01")
        self.assertEqual(
            offer.native_selection,
            {
                "provider": "verda",
                "operation": "create_instance",
                "instance_type": "1H100.8V",
                "location_code": "FIN-01",
            },
        )

    def test_inspect_revalidates_the_provider_offer(self) -> None:
        service = OfferService(runpod_client=FakeRunpodClient())
        visible = service.list_offers(providers=["runpod"]).observations[0]

        inspected = service.inspect(visible.source_offer_id)

        self.assertEqual(inspected.source_offer_id, visible.source_offer_id)
        self.assertEqual(inspected.observation_purpose, "preflight")
        self.assertEqual(inspected.observation_resolution, "deployment_option")
        self.assertNotEqual(inspected.observation_id, visible.observation_id)

    def test_runpod_plan_uses_native_selection_without_submitting(self) -> None:
        service = OfferService(runpod_client=FakeRunpodClient())
        offer = service.list_offers(providers=["runpod"]).observations[0]

        plan = LaunchPlanner(service).plan(offer.source_offer_id)

        self.assertEqual(plan.status, "draft")
        self.assertEqual(plan.required_inputs, ("name", "image"))
        self.assertEqual(plan.request["gpuTypeIds"], ["NVIDIA H100 80GB HBM3"])
        self.assertEqual(plan.request["dataCenterIds"], ["EU-RO-1"])
        self.assertFalse(plan.credentials_configured)
        self.assertFalse(plan.payload()["submitted"])

    def test_runpod_plan_becomes_ready_when_request_is_complete(self) -> None:
        service = OfferService(
            runpod_api_key="configured",
            runpod_client=FakeRunpodClient(),
        )
        offer = service.list_offers(providers=["runpod"]).observations[0]

        plan = LaunchPlanner(service).plan(
            offer.source_offer_id,
            name="bazaar-h100-01",
            image="runpod/pytorch:latest",
        )

        self.assertEqual(plan.status, "ready_for_confirmation")
        self.assertEqual(plan.required_inputs, ())
        self.assertEqual(plan.request["name"], "bazaar-h100-01")
        self.assertEqual(plan.request["imageName"], "runpod/pytorch:latest")
        self.assertTrue(plan.credentials_configured)

    def test_verda_plan_requires_ssh_key_and_keeps_exact_location(self) -> None:
        service = OfferService(verda_client=FakeVerdaClient())
        offer = service.list_offers(providers=["verda"]).observations[0]

        plan = LaunchPlanner(service).plan(
            offer.source_offer_id,
            name="bazaar-h100-02",
            image="ubuntu-22.04-cuda",
        )

        self.assertEqual(plan.required_inputs, ("ssh_key_id",))
        self.assertEqual(plan.request["instance_type"], "1H100.8V")
        self.assertEqual(plan.request["location_code"], "FIN-01")

    def test_paid_runpod_launch_requires_explicit_confirmation(self) -> None:
        service = OfferService(
            runpod_api_key="configured",
            runpod_client=FakeRunpodClient(),
        )
        offer = service.list_offers(providers=["runpod"]).observations[0]
        plan = LaunchPlanner(service).plan(
            offer.source_offer_id,
            name="bazaar-h100-01",
            image="runpod/pytorch:latest",
        )

        with self.assertRaisesRegex(LaunchExecutionError, "confirm-spend"):
            RunpodExecutor(api_key="configured").execute(
                plan,
                runtime_minutes=30,
                max_hourly_usd=3,
                confirm_spend=False,
            )

    def test_runpod_execution_has_price_ceiling_and_provider_deadline(self) -> None:
        service = OfferService(
            runpod_api_key="configured",
            runpod_client=FakeRunpodClient(),
        )
        offer = service.list_offers(providers=["runpod"]).observations[0]
        plan = LaunchPlanner(service).plan(
            offer.source_offer_id,
            name="bazaar-h100-01",
            image="runpod/pytorch:latest",
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "id_ed25519"
            identity.write_text("test", encoding="utf-8")
            calls: list[list[str]] = []

            def fake_runner(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                if command[1:3] == ["pod", "create"]:
                    output = {"id": "pod-123", "desiredStatus": "RUNNING"}
                else:
                    output = {
                        "id": "pod-123",
                        "name": "bazaar-h100-01",
                        "ip": "203.0.113.10",
                        "port": 22123,
                        "ssh_command": "ssh root@203.0.113.10 -p 22123",
                        "ssh_key": {},
                    }
                return subprocess.CompletedProcess(command, 0, json.dumps(output), "")

            registry = FleetRegistry(root / "fleet")
            receipt = RunpodExecutor(
                api_key="configured",
                registry=registry,
                runner=fake_runner,
                binary="runpodctl",
                identity_file=str(identity),
            ).execute(
                plan,
                runtime_minutes=30,
                max_hourly_usd=3,
                confirm_spend=True,
            )

            create = calls[0]
            self.assertIn("--terminate-after", create)
            self.assertIn("--wait", create)
            self.assertNotIn("--stop-after", create)
            self.assertEqual(receipt.machine.host_id, "runpod:pod-123")
            self.assertEqual(receipt.machine.ssh.host, "203.0.113.10")
            self.assertEqual(registry.get("runpod:pod-123"), receipt.machine)
            self.assertEqual(receipt.expected_max_cost_usd, 0.995)

    def test_wait_timeout_still_registers_the_paid_pod(self) -> None:
        service = OfferService(
            runpod_api_key="configured",
            runpod_client=FakeRunpodClient(),
        )
        offer = service.list_offers(providers=["runpod"]).observations[0]
        plan = LaunchPlanner(service).plan(
            offer.source_offer_id,
            name="bazaar-h100-01",
            image="runpod/pytorch:latest",
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "id_ed25519"
            identity.write_text("test", encoding="utf-8")

            def fake_runner(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                if command[1:3] == ["pod", "create"]:
                    error = {"error": "ssh wait timed out", "id": "pod-123"}
                    return subprocess.CompletedProcess(
                        command, 1, "", json.dumps(error)
                    )
                pending = {"error": "pod not ready", "id": "pod-123"}
                return subprocess.CompletedProcess(command, 0, json.dumps(pending), "")

            registry = FleetRegistry(root / "fleet")
            receipt = RunpodExecutor(
                api_key="configured",
                registry=registry,
                runner=fake_runner,
                identity_file=str(identity),
            ).execute(
                plan,
                runtime_minutes=30,
                max_hourly_usd=3,
                confirm_spend=True,
            )

            self.assertEqual(registry.get("runpod:pod-123").host_id, "runpod:pod-123")
            self.assertIsNone(receipt.machine.ssh)
            self.assertEqual(len(receipt.warnings), 2)

    def test_runpod_execution_refuses_price_above_ceiling(self) -> None:
        service = OfferService(
            runpod_api_key="configured",
            runpod_client=FakeRunpodClient(),
        )
        offer = service.list_offers(providers=["runpod"]).observations[0]
        plan = LaunchPlanner(service).plan(
            offer.source_offer_id,
            name="bazaar-h100-01",
            image="runpod/pytorch:latest",
        )

        with self.assertRaisesRegex(LaunchExecutionError, "exceeds"):
            RunpodExecutor(api_key="configured").execute(
                plan,
                runtime_minutes=30,
                max_hourly_usd=1,
                confirm_spend=True,
            )


if __name__ == "__main__":
    unittest.main()
