from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
import json
from pathlib import Path
import sys
import tempfile
import unittest
from typing import Any, Callable

EVAL_ROOT = Path(__file__).resolve().parents[1]
TASK_ROOT = EVAL_ROOT / "task"
sys.path.insert(0, str(TASK_ROOT))

from tests import verify  # noqa: E402
from tests.market_engine import MarketEngine  # noqa: E402


SelectionPolicy = Callable[[MarketEngine], list[int]]


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _post_state(observation: Any) -> dict[str, Any]:
    return {
        "completed_deals": observation.completed_deals,
        "invalid_actions": observation.invalid_actions,
        "terminal": observation.terminal,
        "terminal_reason": (
            observation.terminal_reason.value
            if observation.terminal_reason is not None
            else None
        ),
    }


def _lowest_failure_suppliers(engine: MarketEngine) -> list[int]:
    eligible = [item for item in engine._private_suppliers_for_qa() if item.eligible]
    eligible.sort(key=lambda item: (item.failure_probability, item.supplier_id))
    return [item.supplier_id for item in eligible[: engine.config.deal_size]]


def _highest_failure_suppliers(engine: MarketEngine) -> list[int]:
    eligible = [item for item in engine._private_suppliers_for_qa() if item.eligible]
    eligible.sort(key=lambda item: (-item.failure_probability, item.supplier_id))
    return [item.supplier_id for item in eligible[: engine.config.deal_size]]


def _build_artifact(
    *,
    policy: SelectionPolicy = _lowest_failure_suppliers,
    completed_deals: int = 100,
    seed: int = 7,
) -> dict[str, Any]:
    config = verify.MarketConfig()
    engine = MarketEngine(config)
    engine.reset(seed)
    attempts: list[dict[str, Any]] = []
    for attempt_id in range(1, completed_deals + 1):
        requested = policy(engine)
        step = engine.step(requested)
        attempts.append(
            {
                "attempt_id": attempt_id,
                "requested_supplier_ids": requested,
                "accepted": step.accepted,
                "error": step.error,
                "deal": _jsonable(step.deal),
                "broker_reward": step.broker_reward,
                "post_state": _post_state(step.observation),
            }
        )

    observation = engine.observe()
    result = engine.result()
    return {
        "schema_version": verify.EXPECTED["artifact_schema_version"],
        "artifact_kind": verify.EXPECTED["artifact_kind"],
        "engine": {
            "version": verify.EXPECTED["engine_version"],
            "upstream_revision": verify.EXPECTED["upstream_revision"],
            "sha256": verify.EXPECTED["engine_sha256"],
        },
        "seed": str(seed),
        "config": deepcopy(verify.EXPECTED["config"]),
        "attempts": attempts,
        "final_observation": _jsonable(observation),
        "final_result": _jsonable(result),
        "request_counts": {
            "total": len(attempts),
            "by_action": {"select": len(attempts)},
        },
        "finalized": True,
        "snapshot": {
            "authentication": verify.EXPECTED["snapshot_authentication"],
            "one_shot": True,
            "attempt_count": len(attempts),
            "completed_deals": result.completed_deals,
        },
    }


class VerifierContractTests(unittest.TestCase):
    def test_frozen_engine_is_an_exact_source_copy(self) -> None:
        verifier_engine = (TASK_ROOT / "tests" / "market_engine.py").read_bytes()
        sidecar_engine = (
            TASK_ROOT / "environment" / "market-sidecar" / "market_engine.py"
        ).read_bytes()

        self.assertEqual(verifier_engine, sidecar_engine)

    def test_valid_positive_complete_book(self) -> None:
        metrics, evidence = verify.verify_artifact(_build_artifact())

        self.assertEqual(metrics["completion"], 1)
        self.assertGreater(metrics["reward"], 0)
        self.assertIn("reliability_target_met", metrics)
        self.assertNotIn("sla_met", metrics)
        self.assertEqual(metrics["verifier_integrity"], 1)
        self.assertEqual(evidence["replayed_deals"], 100)

    def test_valid_negative_complete_book(self) -> None:
        artifact = _build_artifact(policy=_highest_failure_suppliers)
        metrics, _ = verify.verify_artifact(artifact)

        self.assertEqual(metrics["completion"], 1)
        self.assertLess(metrics["reward"], 0)
        self.assertGreater(metrics["failed_deals"], 5)

    def test_valid_incomplete_book_scores_agent_failure(self) -> None:
        metrics, evidence = verify.verify_artifact(_build_artifact(completed_deals=1))

        self.assertEqual(metrics["reward"], -1.0)
        self.assertEqual(metrics["completion"], 0)
        self.assertEqual(metrics["completed_deals"], 1)
        self.assertEqual(evidence["replayed_deals"], 1)

    def test_tampered_deal_is_an_infrastructure_failure(self) -> None:
        artifact = _build_artifact(completed_deals=1)
        artifact["attempts"][0]["deal"]["delivered"] = not artifact["attempts"][0][
            "deal"
        ]["delivered"]

        with self.assertRaises(verify.VerificationError):
            verify.verify_artifact(artifact)

    def test_tampered_seed_is_an_infrastructure_failure(self) -> None:
        artifact = _build_artifact()
        artifact["seed"] = "8"

        with self.assertRaises(verify.VerificationError):
            verify.verify_artifact(artifact)

    def test_tampered_config_is_an_infrastructure_failure(self) -> None:
        artifact = _build_artifact(completed_deals=1)
        artifact["config"]["horizon"] = 99

        with self.assertRaises(verify.VerificationError):
            verify.verify_artifact(artifact)

    def test_tampered_request_counts_are_an_infrastructure_failure(self) -> None:
        artifact = _build_artifact(completed_deals=1)
        artifact["request_counts"]["total"] = 2

        with self.assertRaises(verify.VerificationError):
            verify.verify_artifact(artifact)

    def test_tampered_final_result_is_an_infrastructure_failure(self) -> None:
        artifact = _build_artifact(completed_deals=1)
        artifact["final_result"]["primary_reward"] = 1.0

        with self.assertRaises(verify.VerificationError):
            verify.verify_artifact(artifact)

    def test_missing_artifact_removes_stale_reward_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reward = root / "reward.json"
            evidence = root / "evidence.json"
            details = root / "details.json"
            reward.write_text('{"reward": 1}\n')
            evidence.write_text("stale\n")
            details.write_text("stale\n")

            with self.assertRaises(verify.VerificationError):
                verify.run_verification(
                    artifact_path=root / "missing.json",
                    reward_path=reward,
                    evidence_path=evidence,
                    details_path=details,
                )

            self.assertFalse(reward.exists())
            self.assertFalse(evidence.exists())
            self.assertFalse(details.exists())

    def test_malformed_artifact_writes_no_reward(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_path = root / "state.json"
            reward_path = root / "reward.json"
            artifact_path.write_text('{"schema_version": NaN}\n')

            with self.assertRaises(verify.VerificationError):
                verify.run_verification(
                    artifact_path=artifact_path,
                    reward_path=reward_path,
                    evidence_path=root / "evidence.json",
                    details_path=root / "details.json",
                )

            self.assertFalse(reward_path.exists())

    def test_negative_reward_is_serialized_as_a_json_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_path = root / "state.json"
            reward_path = root / "reward.json"
            artifact = _build_artifact(policy=_highest_failure_suppliers)
            artifact_path.write_text(json.dumps(artifact, allow_nan=False))

            verify.run_verification(
                artifact_path=artifact_path,
                reward_path=reward_path,
                evidence_path=root / "evidence.json",
                details_path=root / "details.json",
            )

            serialized = reward_path.read_text()
            parsed = json.loads(serialized)
            self.assertEqual(set(parsed), {"reward"})
            self.assertIs(type(parsed["reward"]), float)
            self.assertLess(parsed["reward"], 0)
            self.assertIn('"reward": -', serialized)


if __name__ == "__main__":
    unittest.main()
