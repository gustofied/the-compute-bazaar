#!/usr/bin/env python3
"""Replay and score the protected Reliability Is Blind market ledger.

This verifier is intentionally deterministic and offline.  A missing or
inconsistent ledger is an infrastructure failure: no reward file is emitted.
A replayable but incomplete broker book is an agent outcome and receives the
engine's fail-closed reward.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

try:
    from market_engine import (
        ENGINE_VERSION,
        UPSTREAM_REVISION,
        MarketConfig,
        MarketEngine,
    )
except ModuleNotFoundError:  # Imported by the repository's unit-test package.
    from .market_engine import (  # type: ignore[no-redef]
        ENGINE_VERSION,
        UPSTREAM_REVISION,
        MarketConfig,
        MarketEngine,
    )


ARTIFACT_PATH = Path("/market-artifacts/state.json")
REWARD_PATH = Path("/logs/verifier/reward.json")
EVIDENCE_PATH = Path("/logs/verifier/evidence.json")
DETAILS_PATH = Path("/logs/verifier/details.json")
EXPECTED_PATH = Path(__file__).with_name("expected.json")
ENGINE_PATH = Path(__file__).with_name("market_engine.py")
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
SEED_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\Z")

EXPECTED: dict[str, Any] = json.loads(EXPECTED_PATH.read_text())
CONFIG_FIELDS = (
    "initial_supplier_count",
    "supplier_cap",
    "deal_size",
    "horizon",
    "initial_stake",
    "slash_amount",
    "target_failure_rate",
    "failure_distribution_alpha",
    "scheduled_arrival_interval",
    "invalid_action_limit",
    "randomness_version",
)


class VerificationError(RuntimeError):
    """The protected artifact cannot be safely scored."""


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value!r}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _loads_strict(payload: str) -> Any:
    return json.loads(
        payload,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_json_constant,
    )


def load_artifact(path: Path = ARTIFACT_PATH) -> tuple[dict[str, Any], str]:
    """Load a bounded, strict JSON artifact and return it with its digest."""

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise VerificationError("authoritative market ledger is missing") from exc
    if size > MAX_ARTIFACT_BYTES:
        raise VerificationError("authoritative market ledger exceeds the size limit")
    try:
        payload = path.read_bytes()
        state = _loads_strict(payload.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise VerificationError("authoritative market ledger is malformed") from exc
    if not isinstance(state, dict):
        raise VerificationError("authoritative market ledger must be a JSON object")
    return state, hashlib.sha256(payload).hexdigest()


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise VerificationError("replay produced a non-finite value")
    return value


def _require_exact_keys(value: Any, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VerificationError(f"{path} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise VerificationError(
            f"{path} keys mismatch (missing={missing}, extra={extra})"
        )
    return value


def _require_nonnegative_int(value: Any, path: str) -> int:
    if type(value) is not int or value < 0:
        raise VerificationError(f"{path} must be a non-negative integer")
    return value


def _strict_equal(actual: Any, expected: Any) -> bool:
    """JSON equality that does not treat booleans as integers."""

    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _strict_equal(actual[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _strict_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected, strict=True)
        )
    return bool(actual == expected)


def _assert_equal(actual: Any, expected: Any, path: str) -> None:
    if not _strict_equal(actual, expected):
        raise VerificationError(
            f"{path} does not match deterministic replay: "
            f"observed={actual!r}, expected={expected!r}"
        )


def _complete_config(config: MarketConfig) -> dict[str, Any]:
    values = _jsonable(asdict(config))
    values.update(
        {
            "reward_amount": config.reward_amount,
            "minimum_stake": config.minimum_stake,
            "maximum_stake": config.maximum_stake,
            "ruin_threshold": config.ruin_threshold,
            "incomplete_reward": config.incomplete_reward,
        }
    )
    return values


def _check_frozen_contract() -> None:
    actual_hash = hashlib.sha256(ENGINE_PATH.read_bytes()).hexdigest()
    _assert_equal(actual_hash, EXPECTED["engine_sha256"], "frozen engine hash")
    _assert_equal(ENGINE_VERSION, EXPECTED["engine_version"], "engine version")
    _assert_equal(
        UPSTREAM_REVISION,
        EXPECTED["upstream_revision"],
        "upstream revision",
    )
    _assert_equal(
        _complete_config(MarketConfig()),
        EXPECTED["config"],
        "pinned market config",
    )


def _parse_seed(raw_seed: Any) -> int:
    if not isinstance(raw_seed, str) or SEED_PATTERN.fullmatch(raw_seed) is None:
        raise VerificationError("seed must be a canonical unsigned decimal string")
    seed = int(raw_seed)
    if seed >= 2**256:
        raise VerificationError("seed exceeds the 256-bit contract")
    return seed


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


def _verify_request_counts(raw: Any, attempt_count: int) -> dict[str, Any]:
    counts = _require_exact_keys(raw, {"total", "by_action"}, "request_counts")
    total = _require_nonnegative_int(counts["total"], "request_counts.total")
    by_action = counts["by_action"]
    if not isinstance(by_action, dict):
        raise VerificationError("request_counts.by_action must be an object")
    allowed_actions = {"ping", "status", "history", "select", "result"}
    if any(
        not isinstance(action, str) or action not in allowed_actions
        for action in by_action
    ):
        raise VerificationError("request_counts.by_action has an unknown action")
    normalized: dict[str, int] = {}
    for action, count in by_action.items():
        normalized[action] = _require_nonnegative_int(
            count, f"request_counts.by_action.{action}"
        )
    if sum(normalized.values()) != total:
        raise VerificationError("request_counts total does not match its action counts")
    if normalized.get("select", 0) != attempt_count:
        raise VerificationError(
            "select request count does not match the attempt ledger"
        )
    return {"total": total, "by_action": normalized}


def _replay_attempts(engine: MarketEngine, raw_attempts: Any) -> int:
    if not isinstance(raw_attempts, list):
        raise VerificationError("attempts must be a list")
    maximum_attempts = engine.config.horizon + engine.config.invalid_action_limit - 1
    if len(raw_attempts) > maximum_attempts:
        raise VerificationError("attempt ledger exceeds the verifier limit")

    for position, raw_event in enumerate(raw_attempts, start=1):
        event = _require_exact_keys(
            raw_event,
            {
                "attempt_id",
                "requested_supplier_ids",
                "accepted",
                "error",
                "deal",
                "broker_reward",
                "post_state",
            },
            f"attempts[{position - 1}]",
        )
        if type(event["attempt_id"]) is not int or event["attempt_id"] != position:
            raise VerificationError("attempt IDs must be contiguous and one-indexed")
        requested = event["requested_supplier_ids"]
        if not isinstance(requested, list) or len(requested) > 128:
            raise VerificationError("requested_supplier_ids must be a bounded list")

        replayed = engine.step(requested)
        expected_event = {
            "attempt_id": position,
            "requested_supplier_ids": requested,
            "accepted": replayed.accepted,
            "error": replayed.error,
            "deal": _jsonable(replayed.deal),
            "broker_reward": replayed.broker_reward,
            "post_state": _post_state(replayed.observation),
        }
        _assert_equal(event, expected_event, f"attempts[{position - 1}]")
    return len(raw_attempts)


def verify_artifact(
    artifact: dict[str, Any], *, artifact_sha256: str = "in-memory"
) -> tuple[dict[str, float | int], dict[str, Any]]:
    """Replay one authoritative ledger and return Harbor metrics and evidence."""

    _check_frozen_contract()
    state = _require_exact_keys(
        artifact,
        {
            "schema_version",
            "artifact_kind",
            "engine",
            "seed",
            "config",
            "attempts",
            "final_observation",
            "final_result",
            "request_counts",
            "finalized",
            "snapshot",
        },
        "ledger",
    )
    _assert_equal(
        state["schema_version"],
        EXPECTED["artifact_schema_version"],
        "schema_version",
    )
    _assert_equal(state["artifact_kind"], EXPECTED["artifact_kind"], "artifact_kind")
    if state["finalized"] is not True:
        raise VerificationError("ledger was not finalized by the sidecar")

    engine_metadata = _require_exact_keys(
        state["engine"], {"version", "upstream_revision", "sha256"}, "engine"
    )
    _assert_equal(
        engine_metadata["version"], EXPECTED["engine_version"], "engine.version"
    )
    _assert_equal(
        engine_metadata["upstream_revision"],
        EXPECTED["upstream_revision"],
        "engine.upstream_revision",
    )
    _assert_equal(engine_metadata["sha256"], EXPECTED["engine_sha256"], "engine.sha256")
    _assert_equal(state["config"], EXPECTED["config"], "config")

    init_config = {key: state["config"][key] for key in CONFIG_FIELDS}
    try:
        config = MarketConfig(**init_config)
    except (TypeError, ValueError) as exc:
        raise VerificationError("pinned market config is invalid") from exc
    engine = MarketEngine(config)
    engine.reset(_parse_seed(state["seed"]))
    attempt_count = _replay_attempts(engine, state["attempts"])

    final_observation = _jsonable(engine.observe())
    final_result = _jsonable(engine.result())
    _assert_equal(state["final_observation"], final_observation, "final_observation")
    _assert_equal(state["final_result"], final_result, "final_result")

    counts = _verify_request_counts(state["request_counts"], attempt_count)
    snapshot = _require_exact_keys(
        state["snapshot"],
        {"authentication", "one_shot", "attempt_count", "completed_deals"},
        "snapshot",
    )
    _assert_equal(
        snapshot["authentication"],
        EXPECTED["snapshot_authentication"],
        "snapshot.authentication",
    )
    if snapshot["one_shot"] is not True:
        raise VerificationError("snapshot was not produced by the one-shot path")
    _assert_equal(snapshot["attempt_count"], attempt_count, "snapshot.attempt_count")
    _assert_equal(
        snapshot["completed_deals"],
        final_result["completed_deals"],
        "snapshot.completed_deals",
    )

    metrics: dict[str, float | int] = {
        "reward": float(final_result["primary_reward"]),
        "completion": int(final_result["completion"]),
        "delivery_rate": float(final_result["delivery_rate"]),
        "failure_rate": float(final_result["failure_rate"]),
        "reliability_target_met": int(final_result["target_met"]),
        "completed_deals": int(final_result["completed_deals"]),
        "delivered_deals": int(final_result["delivered_deals"]),
        "failed_deals": int(final_result["failed_deals"]),
        "eligible_suppliers": int(final_result["eligible_supplier_count"]),
        "verifier_integrity": 1,
    }
    evidence = {
        "verifier_schema_version": "reliability-is-blind.verifier.v1",
        "verifier_integrity": 1,
        "artifact_sha256": artifact_sha256,
        "replayed_attempts": attempt_count,
        "replayed_deals": final_result["completed_deals"],
        "request_counts": counts,
        "reward_calibration": {
            "success": config.reward_amount,
            "failure": -config.slash_amount,
            "target_failure_rate": config.target_failure_rate,
        },
        "result": final_result,
    }
    return metrics, evidence


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            value,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    )
    temporary_path = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def run_verification(
    *,
    artifact_path: Path = ARTIFACT_PATH,
    reward_path: Path = REWARD_PATH,
    evidence_path: Path = EVIDENCE_PATH,
    details_path: Path = DETAILS_PATH,
) -> tuple[dict[str, float | int], dict[str, Any]]:
    """Verify and atomically emit output, never leaving stale reward state."""

    for output_path in (reward_path, evidence_path, details_path):
        output_path.unlink(missing_ok=True)
    artifact, artifact_sha256 = load_artifact(artifact_path)
    metrics, evidence = verify_artifact(artifact, artifact_sha256=artifact_sha256)
    _atomic_json(evidence_path, evidence)
    _atomic_json(reward_path, {"reward": metrics["reward"]})
    return metrics, evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=ARTIFACT_PATH)
    parser.add_argument("--reward", type=Path, default=REWARD_PATH)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    parser.add_argument("--details", type=Path, default=DETAILS_PATH)
    args = parser.parse_args()
    try:
        run_verification(
            artifact_path=args.artifact,
            reward_path=args.reward,
            evidence_path=args.evidence,
            details_path=args.details,
        )
    except VerificationError as exc:
        print(f"verification infrastructure failure: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
