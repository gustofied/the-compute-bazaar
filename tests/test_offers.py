from __future__ import annotations

import unittest
import json
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import requests

from the_compute_bazaar.fleet import FleetRegistry
from the_compute_bazaar.offers import OfferService
from the_compute_bazaar.operations import OperationalLedger
from the_compute_bazaar.provider_execution import (
    LaunchExecutionError,
    RunpodExecutor,
)
from the_compute_bazaar.provisioning import LaunchPlanner
from the_compute_bazaar.prices.providers.runpod import RunpodClient, normalize_gpu_types


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

            def record_offer_batch(self, batch: Any) -> None:
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

            def record_offer_batch(self, batch: Any) -> None:
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

    def test_scheduled_and_direct_reads_share_a_market_product_key(self) -> None:
        observed_at = datetime(2026, 8, 11, 12, tzinfo=UTC)
        scheduled, _ = normalize_gpu_types(
            [
                {
                    "id": "NVIDIA H100 80GB HBM3",
                    "displayName": "H100 PCIe",
                    "memoryInGb": 80,
                    "secureCloud": True,
                    "lowestPrice": {
                        "stockStatus": "High",
                        "uninterruptablePrice": 2.49,
                    },
                }
            ],
            observed_at=observed_at,
            raw_ref="raw.json",
        )
        direct = OfferService(runpod_client=FakeRunpodClient()).list_offers(
            providers=["runpod"]
        )

        self.assertEqual(
            scheduled[0].market_product_key,
            direct.observations[0].market_product_key,
        )

    def test_direct_provider_evidence_is_sanitized_and_retained(self) -> None:
        class RawRunpodClient(FakeRunpodClient):
            def fetch_live_market(self) -> SimpleNamespace:
                payload = super().fetch_live_market()
                payload.raw_payload = {
                    "authorization": "Bearer secret",
                    "nested": {"api_key": "secret", "count": 1},
                }
                return payload

        with tempfile.TemporaryDirectory() as temporary:
            ledger = OperationalLedger(Path(temporary) / "operations.sqlite3")
            OfferService(
                runpod_client=RawRunpodClient(),
                ledger=ledger,
            ).list_offers(providers=["runpod"])

            row = ledger.arrow_tables()["provider_read_batches"].to_pylist()[0]

            self.assertTrue(row["raw_ref"].startswith("sqlite://"))
            self.assertNotIn("secret", row["sanitized_payload_json"])
            self.assertEqual(
                json.loads(row["sanitized_payload_json"])["authorization"],
                "[redacted]",
            )

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
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "id_ed25519"
            identity.write_text("test", encoding="utf-8")
            calls: list[list[str]] = []
            registry = FleetRegistry(root / "fleet")
            ledger = OperationalLedger(root / "operations.sqlite3", registry=registry)
            service = OfferService(
                runpod_api_key="configured",
                runpod_client=FakeRunpodClient(),
                ledger=ledger,
            )
            offer = service.list_offers(providers=["runpod"]).observations[0]
            plan = LaunchPlanner(service).plan(
                offer.source_offer_id,
                name="bazaar-h100-01",
                image="runpod/pytorch:latest",
            )

            def fake_runner(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                if command[1:3] == ["pod", "create"]:
                    attempts = ledger.arrow_tables()["provisioning_attempts"].to_pylist()
                    self.assertEqual(attempts[0]["state"], "pending")
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

            receipt = RunpodExecutor(
                api_key="configured",
                registry=registry,
                runner=fake_runner,
                binary="runpodctl",
                identity_file=str(identity),
                ledger=ledger,
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
            self.assertEqual(receipt.machine.ssh.target, "root@203.0.113.10")
            self.assertEqual(registry.get("runpod:pod-123"), receipt.machine)
            self.assertEqual(receipt.expected_max_cost_usd, 0.995)
            self.assertEqual(receipt.machine.allocation_id, receipt.allocation_id)
            request = ledger.arrow_tables()["provisioning_requests"].to_pylist()[0]
            self.assertEqual(
                request["candidate_observation_id"], plan.candidate_observation_id
            )
            self.assertEqual(
                request["preflight_observation_id"], plan.preflight_observation_id
            )

    def test_wait_timeout_still_registers_the_paid_pod(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "id_ed25519"
            identity.write_text("test", encoding="utf-8")
            registry = FleetRegistry(root / "fleet")
            ledger = OperationalLedger(root / "operations.sqlite3", registry=registry)
            service = OfferService(
                runpod_api_key="configured",
                runpod_client=FakeRunpodClient(),
                ledger=ledger,
            )
            offer = service.list_offers(providers=["runpod"]).observations[0]
            plan = LaunchPlanner(service).plan(
                offer.source_offer_id,
                name="bazaar-h100-01",
                image="runpod/pytorch:latest",
            )

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

            receipt = RunpodExecutor(
                api_key="configured",
                registry=registry,
                runner=fake_runner,
                identity_file=str(identity),
                ledger=ledger,
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

    def test_runpod_execution_rejects_a_stale_preflight(self) -> None:
        service = OfferService(
            runpod_api_key="configured",
            runpod_client=FakeRunpodClient(),
        )
        offer = service.list_offers(providers=["runpod"]).observations[0]
        plan = LaunchPlanner(service).plan(
            offer.source_offer_id,
            name="bazaar-h100-01",
            image="runpod/pytorch:latest",
        ).model_copy(
            update={"observed_at": datetime.now(UTC) - timedelta(minutes=2)}
        )

        with self.assertRaisesRegex(LaunchExecutionError, "plan it again"):
            RunpodExecutor(api_key="configured").execute(
                plan,
                runtime_minutes=30,
                max_hourly_usd=3,
                confirm_spend=True,
            )

    def test_uncertain_create_blocks_a_duplicate_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "id_ed25519"
            identity.write_text("test", encoding="utf-8")
            registry = FleetRegistry(root / "fleet")
            ledger = OperationalLedger(root / "operations.sqlite3", registry=registry)
            service = OfferService(
                runpod_api_key="configured",
                runpod_client=FakeRunpodClient(),
                ledger=ledger,
            )
            offer = service.list_offers(providers=["runpod"]).observations[0]
            plan = LaunchPlanner(service).plan(
                offer.source_offer_id,
                name="bazaar-h100-01",
                image="runpod/pytorch:latest",
            )
            calls = 0

            def failing_runner(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                nonlocal calls
                calls += 1
                return subprocess.CompletedProcess(command, 1, "", "network lost")

            executor = RunpodExecutor(
                api_key="configured",
                registry=registry,
                runner=failing_runner,
                identity_file=str(identity),
                ledger=ledger,
            )

            with self.assertRaises(LaunchExecutionError):
                executor.execute(
                    plan,
                    runtime_minutes=30,
                    max_hourly_usd=3,
                    confirm_spend=True,
                )
            with self.assertRaisesRegex(LaunchExecutionError, "uncertain"):
                executor.execute(
                    plan,
                    runtime_minutes=30,
                    max_hourly_usd=3,
                    confirm_spend=True,
                )

            attempts = ledger.arrow_tables()["provisioning_attempts"].to_pylist()
            self.assertEqual(calls, 1)
            self.assertEqual(attempts[0]["state"], "uncertain")

    def test_provider_capacity_rejection_is_a_failed_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "id_ed25519"
            identity.write_text("test", encoding="utf-8")
            registry = FleetRegistry(root / "fleet")
            ledger = OperationalLedger(root / "operations.sqlite3", registry=registry)
            service = OfferService(
                runpod_api_key="configured",
                runpod_client=FakeRunpodClient(),
                ledger=ledger,
            )
            offer = service.list_offers(providers=["runpod"]).observations[0]
            plan = LaunchPlanner(service).plan(
                offer.source_offer_id,
                name="bazaar-h100-unavailable",
                image="runpod/pytorch:latest",
            )
            error = {
                "error": "There are no longer any instances available",
                "code": "graphql_error",
            }

            def rejected(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                stderr = "note: only the first data center is used\n" + json.dumps(error)
                return subprocess.CompletedProcess(command, 1, "", stderr)

            with self.assertRaises(LaunchExecutionError):
                RunpodExecutor(
                    api_key="configured",
                    registry=registry,
                    runner=rejected,
                    identity_file=str(identity),
                    ledger=ledger,
                ).execute(
                    plan,
                    runtime_minutes=30,
                    max_hourly_usd=3,
                    confirm_spend=True,
                )

            attempt = ledger.arrow_tables()["provisioning_attempts"].to_pylist()[0]
            self.assertEqual(attempt["state"], "failed")

    def test_uncertain_create_recovers_one_exact_provider_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "id_ed25519"
            identity.write_text("test", encoding="utf-8")
            registry = FleetRegistry(root / "fleet")
            ledger = OperationalLedger(root / "operations.sqlite3", registry=registry)
            service = OfferService(
                runpod_api_key="configured",
                runpod_client=FakeRunpodClient(),
                ledger=ledger,
            )
            offer = service.list_offers(providers=["runpod"]).observations[0]
            plan = LaunchPlanner(service).plan(
                offer.source_offer_id,
                name="bazaar-h100-recover",
                image="runpod/pytorch:latest",
            )

            def failed_create(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(command, 1, "", "network lost")

            executor = RunpodExecutor(
                api_key="configured",
                registry=registry,
                runner=failed_create,
                binary="runpodctl",
                identity_file=str(identity),
                ledger=ledger,
            )
            with self.assertRaises(LaunchExecutionError):
                executor.execute(
                    plan,
                    runtime_minutes=30,
                    max_hourly_usd=3,
                    confirm_spend=True,
                )
            attempt_id = ledger.arrow_tables()["provisioning_attempts"].to_pylist()[
                0
            ]["attempt_id"]

            def provider_state(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                if command[1:3] == ["pod", "list"]:
                    payload: object = [
                        {
                            "id": "pod-recovered",
                            "name": "bazaar-h100-recover",
                            "runtimeStatus": "RUNNING",
                        }
                    ]
                else:
                    payload = {
                        "id": "pod-recovered",
                        "ip": "203.0.113.11",
                        "port": 22023,
                        "ssh_command": "ssh root@203.0.113.11 -p 22023",
                    }
                return subprocess.CompletedProcess(
                    command, 0, json.dumps(payload), ""
                )

            executor.runner = provider_state
            receipt = executor.reconcile(attempt_id)

            self.assertEqual(receipt.state, "succeeded")
            self.assertEqual(receipt.provider_resource_id, "pod-recovered")
            self.assertEqual(receipt.machine.ssh.target, "root@203.0.113.11")
            attempts = ledger.arrow_tables()["provisioning_attempts"].to_pylist()
            allocations = ledger.arrow_tables()["allocations"].to_pylist()
            self.assertEqual(attempts[0]["state"], "succeeded")
            self.assertEqual(allocations[0]["provider_resource_id"], "pod-recovered")


if __name__ == "__main__":
    unittest.main()
