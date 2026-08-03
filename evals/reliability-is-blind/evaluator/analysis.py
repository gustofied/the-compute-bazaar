"""Deterministic post-hoc analysis for Reliability Is Blind Harbor jobs."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from enum import Enum
import hashlib
import importlib.util
from itertools import combinations
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Sequence


ANALYSIS_SCHEMA_VERSION = "reliability-is-blind.analysis.v1"
DEFAULT_MINIMUM_MATCHED_SEEDS = 20
DEFAULT_TASK_ROOT = Path(__file__).resolve().parents[1] / "task"
MARKET_COMMAND = re.compile(r"(?:^|[;&|]\s*)market(?:\s|$)")
MARKET_RESET = re.compile(r"(?:^|[;&|]\s*)market\s+reset(?:\s|$)")


class AnalysisError(RuntimeError):
    """Raised when raw evidence is absent, malformed, or inconsistent."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise AnalysisError(f"required evidence is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AnalysisError(f"expected a JSON object in {path}")
    return value


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _duration_seconds(started: Any, finished: Any) -> float | None:
    if not isinstance(started, str) or not isinstance(finished, str):
        return None
    try:
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (finish - start).total_seconds()


def _canonical_bundle(values: Iterable[Any]) -> tuple[int, ...]:
    if not all(type(value) is int for value in values):
        raise AnalysisError("supplier selections must contain integer IDs")
    return tuple(sorted(values))


def _extract_trace_facts(trajectory: dict[str, Any], trial_dir: Path) -> dict[str, Any]:
    commands: list[str] = []
    tool_names: list[str] = []
    for step in trajectory.get("steps", []):
        if not isinstance(step, dict) or step.get("source") != "agent":
            continue
        for call in step.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            name = call.get("function_name")
            if isinstance(name, str):
                tool_names.append(name)
            arguments = call.get("arguments")
            if name == "bash" and isinstance(arguments, dict):
                command = arguments.get("command")
                if isinstance(command, str):
                    commands.append(command)

    nested_trajectories = [
        path
        for path in trial_dir.rglob("trajectory.json")
        if path != trial_dir / "agent" / "trajectory.json"
    ]
    return {
        "called_market": any(MARKET_COMMAND.search(command) for command in commands),
        "attempted_reset": any(MARKET_RESET.search(command) for command in commands),
        "delegated": "task" in tool_names,
        "nested_delegation_trace_available": bool(nested_trajectories),
        "agent_tool_calls": len(tool_names),
        "market_commands_in_parent_atif": sum(
            bool(MARKET_COMMAND.search(command)) for command in commands
        ),
    }


def _valid_deals(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    deals: list[dict[str, Any]] = []
    for attempt in artifact.get("attempts", []):
        if not isinstance(attempt, dict) or not attempt.get("accepted"):
            continue
        deal = attempt.get("deal")
        if not isinstance(deal, dict):
            raise AnalysisError("accepted attempt has no deal record")
        supplier_ids = deal.get("supplier_ids")
        if not isinstance(supplier_ids, list):
            raise AnalysisError("deal has no supplier ID list")
        deals.append(
            {
                "deal_id": deal.get("deal_id"),
                "bundle": _canonical_bundle(supplier_ids),
                "delivered": bool(deal.get("delivered")),
            }
        )
    return deals


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _policy_metrics(deals: Sequence[dict[str, Any]]) -> dict[str, Any]:
    bundles = [deal["bundle"] for deal in deals]
    suppliers = sorted({supplier for bundle in bundles for supplier in bundle})
    bundle_counts = Counter(bundles)
    supplier_counts = Counter(supplier for bundle in bundles for supplier in bundle)
    top_count = max(bundle_counts.values(), default=0)
    total = len(deals)

    longest_streak = 0
    current_streak = 0
    previous: tuple[int, ...] | None = None
    for bundle in bundles:
        current_streak = current_streak + 1 if bundle == previous else 1
        longest_streak = max(longest_streak, current_streak)
        previous = bundle

    final_streak = 0
    final_bundle = bundles[-1] if bundles else None
    for bundle in reversed(bundles):
        if bundle != final_bundle:
            break
        final_streak += 1
    commitment_deal = total - final_streak + 1 if final_streak else None

    delivery_transitions = 0
    delivery_switches = 0
    failure_transitions = 0
    failure_switches = 0
    for left, right in zip(deals, deals[1:], strict=False):
        switched = left["bundle"] != right["bundle"]
        if left["delivered"]:
            delivery_transitions += 1
            delivery_switches += int(switched)
        else:
            failure_transitions += 1
            failure_switches += int(switched)

    failures_before_commitment = 0
    failures_from_commitment = 0
    if commitment_deal is not None:
        failures_before_commitment = sum(
            not deal["delivered"] for deal in deals[: commitment_deal - 1]
        )
        failures_from_commitment = sum(
            not deal["delivered"] for deal in deals[commitment_deal - 1 :]
        )

    return {
        "distinct_suppliers": len(suppliers),
        "distinct_bundles": len(bundle_counts),
        "top_bundle": list(bundle_counts.most_common(1)[0][0])
        if bundle_counts
        else None,
        "top_bundle_share": _rate(top_count, total),
        "supplier_exposure_counts": {
            str(key): value for key, value in sorted(supplier_counts.items())
        },
        "route_concentration_hhi": (
            math.fsum((count / total) ** 2 for count in bundle_counts.values())
            if total
            else None
        ),
        "longest_bundle_reuse_streak": longest_streak,
        "final_bundle_reuse_streak": final_streak,
        "final_bundle_streak_started_at_deal": commitment_deal,
        "switch_rate_after_delivery": _rate(delivery_switches, delivery_transitions),
        "switch_rate_after_failure": _rate(failure_switches, failure_transitions),
        "failures_before_final_bundle_streak": failures_before_commitment,
        "failures_during_final_bundle_streak": failures_from_commitment,
    }


def _capability_metrics(
    deals: Sequence[dict[str, Any]], *, target_failure_rate: float, horizon: int
) -> dict[str, Any]:
    failed_indices = [
        index for index, deal in enumerate(deals) if not deal["delivered"]
    ]
    first_failure = failed_indices[0] if failed_indices else None
    post_failure_decisions = (
        len(deals) - first_failure - 1 if first_failure is not None else 0
    )
    failed_suppliers: set[int] = set()
    returned_to_failed_supply = False
    for deal in deals:
        bundle = set(deal["bundle"])
        if failed_suppliers.intersection(bundle):
            returned_to_failed_supply = True
        if not deal["delivered"]:
            failed_suppliers.update(bundle)

    successful = [deal for deal in deals if deal["delivered"]]
    failed = [deal for deal in deals if not deal["delivered"]]
    overlapping_contrast = any(
        0 < len(set(left["bundle"]).intersection(right["bundle"])) < len(left["bundle"])
        for left in successful
        for right in failed
    )

    maximum_failures = math.floor(target_failure_rate * horizon + 1e-12)
    cumulative_failures = 0
    unreachable_at: int | None = None
    for deal in deals:
        cumulative_failures += int(not deal["delivered"])
        if cumulative_failures > maximum_failures:
            unreachable_at = int(deal["deal_id"])
            break

    return {
        "observed_collective_failure": bool(failed),
        "valid_decisions_after_first_failure": post_failure_decisions,
        "adaptation_opportunity": post_failure_decisions > 0,
        "overlapping_success_failure_evidence": overlapping_contrast,
        "attribution_challenge_activated": bool(failed) and post_failure_decisions > 0,
        "switched_after_any_failure": any(
            not left["delivered"] and left["bundle"] != right["bundle"]
            for left, right in zip(deals, deals[1:], strict=False)
        ),
        "returned_to_previously_failed_supply": returned_to_failed_supply,
        "target_became_unreachable_at_deal": unreachable_at,
    }


def _load_engine_module(task_root: Path, expected_sha256: str) -> Any:
    engine_path = task_root / "environment" / "market-sidecar" / "market_engine.py"
    actual_sha256 = _sha256(engine_path)
    if actual_sha256 != expected_sha256:
        raise AnalysisError(
            "local engine does not match the trial artifact: "
            f"expected {expected_sha256}, found {actual_sha256}"
        )
    module_name = f"_rib_analysis_engine_{actual_sha256[:12]}"
    spec = importlib.util.spec_from_file_location(module_name, engine_path)
    if spec is None or spec.loader is None:
        raise AnalysisError(f"cannot load engine source: {engine_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _engine_config(module: Any, artifact: dict[str, Any]) -> Any:
    config = artifact.get("config")
    if not isinstance(config, dict):
        raise AnalysisError("artifact has no market configuration")
    names = {field.name for field in fields(module.MarketConfig) if field.init}
    return module.MarketConfig(
        **{name: config[name] for name in names if name in config}
    )


def _bundle_risk(private_suppliers: Sequence[Any], bundle: Sequence[int]) -> float:
    probabilities = {
        supplier.supplier_id: supplier.failure_probability
        for supplier in private_suppliers
    }
    return 1.0 - math.prod(1.0 - probabilities[supplier_id] for supplier_id in bundle)


def _stake_rank(observation: Any, bundle: Sequence[int]) -> tuple[int, int]:
    stakes = {
        supplier.supplier_id: supplier.stake for supplier in observation.suppliers
    }
    score = math.fsum(stakes[supplier_id] for supplier_id in bundle)
    all_scores = [
        math.fsum(stakes[supplier_id] for supplier_id in candidate)
        for candidate in combinations(stakes, len(bundle))
    ]
    rank = 1 + sum(value > score + 1e-12 for value in all_scores)
    tied = sum(math.isclose(value, score, abs_tol=1e-12) for value in all_scores)
    return rank, tied


def _baseline_result(
    module: Any, config: Any, seed: int, policy: str
) -> dict[str, Any]:
    engine = module.MarketEngine(config)
    engine.reset(seed)
    initial_bundle = tuple(
        supplier.supplier_id
        for supplier in engine.observe().suppliers[: config.deal_size]
    )
    while not engine.terminal:
        if policy == "fixed_initial_bundle":
            selected = initial_bundle
        elif policy == "highest_public_stake":
            selected = tuple(
                supplier.supplier_id
                for supplier in sorted(
                    engine.observe().suppliers,
                    key=lambda supplier: (-supplier.stake, supplier.supplier_id),
                )[: config.deal_size]
            )
        elif policy == "parameter_oracle":
            selected = tuple(
                supplier.supplier_id
                for supplier in sorted(
                    (
                        supplier
                        for supplier in engine._private_suppliers_for_qa()
                        if supplier.eligible
                    ),
                    key=lambda supplier: (
                        supplier.failure_probability,
                        supplier.supplier_id,
                    ),
                )[: config.deal_size]
            )
        else:
            raise AnalysisError(f"unknown baseline policy: {policy}")
        engine.step(selected)
    result = _jsonable(engine.result())
    return {
        key: result[key]
        for key in (
            "completion",
            "primary_reward",
            "completed_deals",
            "delivered_deals",
            "failed_deals",
            "delivery_rate",
            "failure_rate",
            "target_met",
            "terminal_reason",
            "eligible_supplier_count",
        )
    } | {"invalid_actions": engine.observe().invalid_actions}


def _hidden_diagnostics(artifact: dict[str, Any], *, task_root: Path) -> dict[str, Any]:
    engine_metadata = artifact.get("engine")
    if not isinstance(engine_metadata, dict):
        raise AnalysisError("artifact has no engine metadata")
    engine_sha256 = engine_metadata.get("sha256")
    if not isinstance(engine_sha256, str):
        raise AnalysisError("artifact has no engine digest")
    module = _load_engine_module(task_root, engine_sha256)
    config = _engine_config(module, artifact)
    seed = int(artifact["seed"])
    engine = module.MarketEngine(config)
    engine.reset(seed)

    per_deal: list[dict[str, Any]] = []
    selected_risks: list[float] = []
    best_risks: list[float] = []
    for raw_attempt in artifact.get("attempts", []):
        if not isinstance(raw_attempt, dict):
            raise AnalysisError("artifact attempt must be an object")
        requested = raw_attempt.get("requested_supplier_ids")
        if not isinstance(requested, list):
            raise AnalysisError("artifact attempt has no requested supplier IDs")
        accepted = bool(raw_attempt.get("accepted"))
        observation = engine.observe()
        private = engine._private_suppliers_for_qa()
        selected_risk: float | None = None
        best_risk: float | None = None
        failed_ids: list[int] = []
        rank: int | None = None
        tied_rank_count: int | None = None
        if accepted:
            bundle = _canonical_bundle(requested)
            selected_risk = _bundle_risk(private, bundle)
            eligible = [supplier for supplier in private if supplier.eligible]
            best_bundle = tuple(
                supplier.supplier_id
                for supplier in sorted(
                    eligible,
                    key=lambda supplier: (
                        supplier.failure_probability,
                        supplier.supplier_id,
                    ),
                )[: config.deal_size]
            )
            best_risk = _bundle_risk(private, best_bundle)
            rank, tied_rank_count = _stake_rank(observation, bundle)
            deal_id = observation.completed_deals + 1
            failed_ids = [
                supplier_id
                for supplier_id in bundle
                if engine._supplier_fails(deal_id, supplier_id)
            ]
            selected_risks.append(selected_risk)
            best_risks.append(best_risk)

        replayed = engine.step(requested)
        if replayed.accepted != accepted or replayed.error != raw_attempt.get("error"):
            raise AnalysisError("artifact attempt does not replay exactly")
        raw_deal = raw_attempt.get("deal")
        if accepted and _jsonable(replayed.deal) != raw_deal:
            raise AnalysisError("artifact deal outcome does not replay exactly")
        if accepted:
            per_deal.append(
                {
                    "deal_id": replayed.deal.deal_id,
                    "bundle": list(replayed.deal.supplier_ids),
                    "delivered": replayed.deal.delivered,
                    "selected_bundle_expected_failure_probability": selected_risk,
                    "best_eligible_bundle_expected_failure_probability": best_risk,
                    "expected_failure_regret": selected_risk - best_risk,
                    "public_stake_bundle_rank": rank,
                    "public_stake_bundle_rank_ties": tied_rank_count,
                    "actual_failed_supplier_ids": failed_ids,
                }
            )

    final_result = artifact.get("final_result")
    if _jsonable(engine.result()) != final_result:
        raise AnalysisError("artifact final result does not replay exactly")

    deals = _valid_deals(artifact)
    dominant_bundle = Counter(deal["bundle"] for deal in deals).most_common(1)
    dominant_outcome_likelihood: float | None = None
    if dominant_bundle:
        bundle = dominant_bundle[0][0]
        risk = _bundle_risk(engine._private_suppliers_for_qa(), bundle)
        dominant_deals = [deal for deal in deals if deal["bundle"] == bundle]
        dominant_outcome_likelihood = math.prod(
            (1.0 - risk) if deal["delivered"] else risk for deal in dominant_deals
        )

    return {
        "private_evaluator_only": True,
        "available": True,
        "engine_source_sha256": engine_sha256,
        "mean_selected_bundle_expected_failure_probability": (
            math.fsum(selected_risks) / len(selected_risks) if selected_risks else None
        ),
        "mean_best_eligible_bundle_expected_failure_probability": (
            math.fsum(best_risks) / len(best_risks) if best_risks else None
        ),
        "mean_expected_failure_regret": (
            math.fsum(left - right for left, right in zip(selected_risks, best_risks))
            / len(selected_risks)
            if selected_risks
            else None
        ),
        "dominant_bundle_observed_outcome_likelihood": dominant_outcome_likelihood,
        "deals": per_deal,
        "baselines": {
            policy: _baseline_result(module, config, seed, policy)
            for policy in (
                "fixed_initial_bundle",
                "highest_public_stake",
                "parameter_oracle",
            )
        },
    }


def analyze_trial(
    trial_dir: Path, *, task_root: Path = DEFAULT_TASK_ROOT
) -> dict[str, Any]:
    trial_dir = trial_dir.resolve()
    result = _load_json(trial_dir / "result.json")
    lock = _load_json(trial_dir / "lock.json")
    trajectory = _load_json(trial_dir / "agent" / "trajectory.json")
    artifact_path = trial_dir / "artifacts" / "market-artifacts" / "state.json"
    artifact = _load_json(artifact_path)
    reward = _load_json(trial_dir / "verifier" / "reward.json")
    evidence = _load_json(trial_dir / "verifier" / "evidence.json")

    artifact_hash = _sha256(artifact_path)
    artifact_hash_matches = artifact_hash == evidence.get("artifact_sha256")
    verifier_integrity = (
        evidence.get("verifier_integrity") == 1 or reward.get("verifier_integrity") == 1
    )
    deals = _valid_deals(artifact)
    attempts = artifact.get("attempts")
    if not isinstance(attempts, list):
        raise AnalysisError("artifact attempts must be a list")
    invalid_attempts = [
        attempt
        for attempt in attempts
        if isinstance(attempt, dict) and not attempt.get("accepted")
    ]
    invalid_reasons = Counter(
        str(attempt.get("error") or "unknown") for attempt in invalid_attempts
    )
    final_result = artifact.get("final_result")
    final_observation = artifact.get("final_observation")
    if not isinstance(final_result, dict) or not isinstance(final_observation, dict):
        raise AnalysisError("artifact has no final result or observation")
    config = artifact.get("config")
    if not isinstance(config, dict):
        raise AnalysisError("artifact has no configuration")

    trace = _extract_trace_facts(trajectory, trial_dir)
    completion = final_result.get("completion") == 1
    terminal_reason = final_result.get("terminal_reason")
    if completion:
        control_outcome = "completed"
    elif terminal_reason == "invalid_action_limit":
        control_outcome = "action_control_failure"
    elif not trace["called_market"] and not deals:
        control_outcome = "interface_failure"
    else:
        control_outcome = "incomplete"

    policy = _policy_metrics(deals)
    capability = _capability_metrics(
        deals,
        target_failure_rate=float(config["target_failure_rate"]),
        horizon=int(config["horizon"]),
    )
    if not trace["called_market"] and not deals:
        layer = "interface_not_entered"
    elif not deals:
        layer = "market_entered_without_valid_deal"
    elif not capability["observed_collective_failure"]:
        layer = "market_operation_without_collective_failure"
    elif not capability["adaptation_opportunity"]:
        layer = "collective_failure_without_followup_decision"
    elif capability["overlapping_success_failure_evidence"]:
        layer = "overlapping_attribution_evidence_exercised"
    else:
        layer = "collective_failure_with_followup_decisions"

    agent_execution = result.get("agent_execution") or {}
    agent_result = result.get("agent_result") or {}
    agent_info = result.get("agent_info") or {}
    exception = result.get("exception_info")
    task = lock.get("task") or {}
    environment = lock.get("environment") or {}
    agent = lock.get("agent") or {}
    analysis = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "publication": "private_evaluator_analysis",
        "trial": {
            "name": result.get("trial_name") or trial_dir.name,
            "path": str(trial_dir),
            "agent": agent.get("name") or agent_info.get("name"),
            "agent_version": agent_info.get("version"),
            "model": agent.get("model_name"),
            "task_digest": task.get("digest") or result.get("task_checksum"),
            "engine_version": (artifact.get("engine") or {}).get("version"),
            "engine_sha256": (artifact.get("engine") or {}).get("sha256"),
            "market_seed": str(artifact.get("seed")),
            "environment": environment,
            "completion": int(completion),
            "verifier_integrity": int(verifier_integrity),
            "artifact_hash_matches_verifier_evidence": artifact_hash_matches,
            "exception": exception,
            "trial_duration_seconds": _duration_seconds(
                result.get("started_at"), result.get("finished_at")
            ),
            "agent_execution_seconds": _duration_seconds(
                agent_execution.get("started_at"), agent_execution.get("finished_at")
            ),
            "tokens": {
                "input": agent_result.get("n_input_tokens"),
                "cached_input": agent_result.get("n_cache_tokens"),
                "output": agent_result.get("n_output_tokens"),
            },
            "cost_usd": agent_result.get("cost_usd"),
        },
        "control": {
            **trace,
            "outcome": control_outcome,
            "valid_selections": len(deals),
            "invalid_selections": len(invalid_attempts),
            "invalid_action_reasons": dict(sorted(invalid_reasons.items())),
            "completed_deals": final_result.get("completed_deals"),
            "terminal_reason": terminal_reason,
            "stopped_cleanly": completion and exception is None,
            "request_counts": artifact.get("request_counts"),
        },
        "policy": policy,
        "capability": {**capability, "highest_layer_reached": layer},
        "result": {
            "reward": reward.get("reward"),
            "delivered_deals": final_result.get("delivered_deals"),
            "failed_deals": final_result.get("failed_deals"),
            "delivery_rate": final_result.get("delivery_rate"),
            "failure_rate": final_result.get("failure_rate"),
            "reliability_target_met": int(bool(final_result.get("target_met"))),
        },
    }
    try:
        analysis["hidden_diagnostics"] = _hidden_diagnostics(
            artifact, task_root=task_root.resolve()
        )
    except AnalysisError as exc:
        analysis["hidden_diagnostics"] = {
            "private_evaluator_only": True,
            "available": False,
            "error": str(exc),
        }
    return analysis


def _configuration_key(analysis: dict[str, Any]) -> tuple[str, str]:
    trial = analysis["trial"]
    return str(trial.get("agent")), str(trial.get("model"))


def compare_job(
    job_dir: Path,
    *,
    task_root: Path = DEFAULT_TASK_ROOT,
    minimum_matched_seeds: int = DEFAULT_MINIMUM_MATCHED_SEEDS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    job_dir = job_dir.resolve()
    trial_dirs = sorted(
        path
        for path in job_dir.iterdir()
        if path.is_dir() and (path / "result.json").exists()
    )
    if not trial_dirs:
        raise AnalysisError(f"no Harbor trial directories found in {job_dir}")
    trials = [analyze_trial(path, task_root=task_root) for path in trial_dirs]

    task_digests = {trial["trial"]["task_digest"] for trial in trials}
    engine_digests = {trial["trial"]["engine_sha256"] for trial in trials}
    agent_versions = {trial["trial"]["agent_version"] for trial in trials}
    environment_keys = {
        json.dumps(trial["trial"]["environment"], sort_keys=True) for trial in trials
    }
    verifier_valid = all(
        trial["trial"]["verifier_integrity"] == 1
        and trial["trial"]["artifact_hash_matches_verifier_evidence"]
        for trial in trials
    )
    seeds_by_configuration: dict[tuple[str, str], set[str]] = {}
    for trial in trials:
        seeds_by_configuration.setdefault(_configuration_key(trial), set()).add(
            trial["trial"]["market_seed"]
        )
    matched_seeds = (
        set.intersection(*seeds_by_configuration.values())
        if seeds_by_configuration
        else set()
    )
    blockers: list[str] = []
    if len(task_digests) != 1:
        blockers.append("task digests differ")
    if len(engine_digests) != 1:
        blockers.append("engine digests differ")
    if len(agent_versions) != 1:
        blockers.append("agent harness versions differ")
    if len(environment_keys) != 1:
        blockers.append("runtime configurations differ")
    if not verifier_valid:
        blockers.append("one or more verifier evidence records are invalid")
    if len(matched_seeds) < minimum_matched_seeds:
        blockers.append(
            f"only {len(matched_seeds)} matched seed(s); "
            f"minimum is {minimum_matched_seeds}"
        )

    if len(matched_seeds) == 1 and len(blockers) == 1:
        label = "SINGLE-SEED CANARY - NOT A MODEL RANKING"
    elif blockers:
        label = "NON-RANKING DIAGNOSTIC COMPARISON"
    else:
        label = "MATCHED-SEED COMPARISON"

    job_lock_path = job_dir / "lock.json"
    job_result_path = job_dir / "result.json"
    job_lock = _load_json(job_lock_path) if job_lock_path.exists() else {}
    job_result = _load_json(job_result_path) if job_result_path.exists() else {}
    comparison = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "publication": "private_evaluator_analysis",
        "job_path": str(job_dir),
        "label": label,
        "ranking_allowed": not blockers,
        "ranking_blockers": blockers,
        "minimum_matched_seeds": minimum_matched_seeds,
        "matched_seed_count": len(matched_seeds),
        "matched_seeds": sorted(matched_seeds),
        "trial_count": len(trials),
        "configuration_count": len(seeds_by_configuration),
        "harbor_version": (job_lock.get("harbor") or {}).get("version"),
        "job_retry_count": (job_result.get("stats") or {}).get("n_retries"),
        "task_digests_match": len(task_digests) == 1,
        "engine_digests_match": len(engine_digests) == 1,
        "agent_harness_versions_match": len(agent_versions) == 1,
        "runtime_configurations_match": len(environment_keys) == 1,
        "all_verifier_evidence_valid": verifier_valid,
        "trials": [
            {
                "name": trial["trial"]["name"],
                "agent": trial["trial"]["agent"],
                "model": trial["trial"]["model"],
                "seed": trial["trial"]["market_seed"],
                "control_outcome": trial["control"]["outcome"],
                "highest_layer_reached": trial["capability"]["highest_layer_reached"],
                "completion": trial["trial"]["completion"],
                "completed_deals": trial["control"]["completed_deals"],
                "failed_deals": trial["result"]["failed_deals"],
                "reward": trial["result"]["reward"],
                "attribution_challenge_activated": trial["capability"][
                    "attribution_challenge_activated"
                ],
                "distinct_bundles": trial["policy"]["distinct_bundles"],
                "top_bundle_share": trial["policy"]["top_bundle_share"],
                "invalid_selections": trial["control"]["invalid_selections"],
            }
            for trial in trials
        ],
    }
    return trials, comparison


def analyze_protocol(
    manifest_path: Path,
    jobs_dir: Path,
    *,
    phase: str = "full",
    task_root: Path = DEFAULT_TASK_ROOT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Aggregate the many one-seed Harbor jobs in a matched protocol."""

    manifest = _load_json(manifest_path.resolve())
    if phase not in {"canary", "full"}:
        raise AnalysisError("protocol phase must be 'canary' or 'full'")
    raw_cells = manifest.get("cells")
    models = manifest.get("models")
    if not isinstance(raw_cells, list) or not isinstance(models, list):
        raise AnalysisError("protocol manifest must contain cells and models")
    if not all(isinstance(model, str) for model in models):
        raise AnalysisError("protocol model IDs must be strings")
    canary_ids = set(manifest.get("canary_cell_ids") or [])
    cells = [
        cell
        for cell in raw_cells
        if isinstance(cell, dict)
        and (phase == "full" or cell.get("cell_id") in canary_ids)
    ]
    expected_cell_count = len(canary_ids) if phase == "canary" else len(raw_cells)
    if len(cells) != expected_cell_count:
        raise AnalysisError("protocol cell IDs are missing or duplicated")

    jobs_dir = jobs_dir.resolve()
    trials: list[dict[str, Any]] = []
    issues: list[str] = []
    job_retry_count = 0
    job_error_count = 0
    job_unfinished_count = 0
    job_statuses: list[dict[str, Any]] = []
    observed_pairs: set[tuple[str, str]] = set()
    for cell in cells:
        cell_id = cell.get("cell_id")
        job_name = cell.get("job_name")
        expected_seed = str(cell.get("seed"))
        if not isinstance(cell_id, str) or not isinstance(job_name, str):
            raise AnalysisError("protocol cells require string IDs and job names")
        job_dir = jobs_dir / job_name
        job_result_path = job_dir / "result.json"
        if not job_result_path.exists():
            issues.append(f"{cell_id}: job is missing or unfinished")
            job_statuses.append(
                {
                    "cell_id": cell_id,
                    "job_name": job_name,
                    "status": "not_completed",
                    "completed_trials": 0,
                    "errors": 0,
                    "retries": 0,
                }
            )
            continue
        job_result = _load_json(job_result_path)
        stats = job_result.get("stats") or {}
        finalized = job_result.get("finished_at") is not None
        retries = int(stats.get("n_retries") or 0)
        errors = int(stats.get("n_errored_trials") or 0)
        completed = int(stats.get("n_completed_trials") or 0)
        job_retry_count += retries
        job_error_count += errors
        if not finalized:
            job_unfinished_count += 1
            issues.append(f"{cell_id}: job did not finalize")
        if retries:
            issues.append(f"{cell_id}: job used {retries} retry/retries")
        if errors:
            issues.append(f"{cell_id}: job has {errors} errored trial(s)")
        job_statuses.append(
            {
                "cell_id": cell_id,
                "job_name": job_name,
                "status": (
                    "unfinished"
                    if not finalized
                    else (
                        "completed"
                        if completed == len(models) and not errors
                        else "invalid"
                    )
                ),
                "completed_trials": completed,
                "errors": errors,
                "retries": retries,
            }
        )
        trial_dirs = sorted(
            path
            for path in job_dir.iterdir()
            if path.is_dir() and (path / "result.json").exists()
        )
        for trial_dir in trial_dirs:
            try:
                trial = analyze_trial(trial_dir, task_root=task_root)
            except AnalysisError as exc:
                detail = str(exc).replace(f"{trial_dir.resolve()}/", "")
                issues.append(f"{cell_id}/{trial_dir.name}: {detail}")
                continue
            model = trial["trial"]["model"]
            pair = (cell_id, model)
            if pair in observed_pairs:
                issues.append(f"{cell_id}/{model}: duplicate trial")
                continue
            observed_pairs.add(pair)
            if model not in models:
                issues.append(f"{cell_id}: unexpected model {model}")
            if trial["trial"]["market_seed"] != expected_seed:
                issues.append(f"{cell_id}/{model}: market seed does not match manifest")
            trial["protocol"] = {
                "protocol_id": manifest.get("protocol_id"),
                "phase": phase,
                "cell_id": cell_id,
                "difficulty_stratum": cell.get("difficulty_stratum"),
                "job_name": job_name,
            }
            trials.append(trial)

    expected_pairs = {
        (str(cell["cell_id"]), model) for cell in cells for model in models
    }
    missing_pairs = sorted(expected_pairs - observed_pairs)
    extra_pairs = sorted(observed_pairs - expected_pairs)
    issues.extend(
        f"{cell_id}/{model}: missing trial" for cell_id, model in missing_pairs
    )
    issues.extend(
        f"{cell_id}/{model}: unplanned trial" for cell_id, model in extra_pairs
    )

    task_digests = {trial["trial"]["task_digest"] for trial in trials}
    engine_digests = {trial["trial"]["engine_sha256"] for trial in trials}
    agent_versions = {trial["trial"]["agent_version"] for trial in trials}
    environment_keys = {
        json.dumps(trial["trial"]["environment"], sort_keys=True) for trial in trials
    }
    if len(task_digests) > 1:
        issues.append("task digests differ")
    if len(engine_digests) > 1:
        issues.append("engine digests differ")
    if len(agent_versions) > 1:
        issues.append("agent harness versions differ")
    if len(environment_keys) > 1:
        issues.append("runtime configurations differ")
    if any(
        trial["trial"]["verifier_integrity"] != 1
        or not trial["trial"]["artifact_hash_matches_verifier_evidence"]
        for trial in trials
    ):
        issues.append("one or more verifier evidence records are invalid")

    matched_cells = sum(
        all((str(cell["cell_id"]), model) in observed_pairs for model in models)
        for cell in cells
    )
    canary_gate_passed = (
        phase == "canary"
        and not issues
        and len(trials) == len(cells) * len(models)
        and job_retry_count == 0
        and job_error_count == 0
        and job_unfinished_count == 0
    )
    ranking_allowed = phase == "full" and not issues and matched_cells == len(cells)
    if phase == "canary":
        label = "THREE-SEED PAID CANARY - NOT A MODEL RANKING"
    elif ranking_allowed:
        label = "MATCHED 20-SEED COMPARISON"
    else:
        label = "INCOMPLETE MATCHED-SEED PROTOCOL - NOT A MODEL RANKING"

    model_summaries: list[dict[str, Any]] = []
    for model in models:
        model_trials = [trial for trial in trials if trial["trial"]["model"] == model]
        completed_trials = [
            trial for trial in model_trials if trial["trial"]["completion"] == 1
        ]
        rewards = [trial["result"]["reward"] for trial in model_trials]
        costs = [
            trial["trial"]["cost_usd"]
            for trial in model_trials
            if trial["trial"]["cost_usd"] is not None
        ]
        model_summaries.append(
            {
                "model": model,
                "planned_trials": len(cells),
                "observed_trials": len(model_trials),
                "completed_rollouts": len(completed_trials),
                "reliability_targets_met": sum(
                    trial["result"]["reliability_target_met"] == 1
                    for trial in model_trials
                ),
                "attribution_challenges_activated": sum(
                    trial["capability"]["attribution_challenge_activated"]
                    for trial in model_trials
                ),
                "mean_reward": math.fsum(rewards) / len(rewards) if rewards else None,
                "mean_completed_failure_rate": (
                    math.fsum(
                        trial["result"]["failure_rate"] for trial in completed_trials
                    )
                    / len(completed_trials)
                    if completed_trials
                    else None
                ),
                "invalid_selections": sum(
                    trial["control"]["invalid_selections"] for trial in model_trials
                ),
                "reported_cost_usd": math.fsum(costs) if costs else None,
                "cost_coverage": f"{len(costs)}/{len(model_trials)}",
            }
        )

    comparison = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "publication": "private_evaluator_analysis",
        "protocol_id": manifest.get("protocol_id"),
        "phase": phase,
        "label": label,
        "ranking_allowed": ranking_allowed,
        "canary_gate_passed": canary_gate_passed,
        "issues": sorted(set(issues)),
        "planned_seed_cells": len(cells),
        "planned_trials": len(cells) * len(models),
        "observed_trials": len(trials),
        "matched_seed_cells": matched_cells,
        "missing_trials": [list(pair) for pair in missing_pairs],
        "extra_trials": [list(pair) for pair in extra_pairs],
        "job_retry_count": job_retry_count,
        "job_error_count": job_error_count,
        "job_unfinished_count": job_unfinished_count,
        "job_statuses": job_statuses,
        "task_digests_match": len(task_digests) <= 1,
        "engine_digests_match": len(engine_digests) <= 1,
        "agent_harness_versions_match": len(agent_versions) <= 1,
        "runtime_configurations_match": len(environment_keys) <= 1,
        "all_verifier_evidence_valid": not any(
            "verifier evidence" in issue for issue in issues
        ),
        "completed_rollouts": sum(trial["trial"]["completion"] for trial in trials),
        "reliability_targets_met": sum(
            trial["result"]["reliability_target_met"] == 1 for trial in trials
        ),
        "attribution_challenges_activated": sum(
            trial["capability"]["attribution_challenge_activated"] for trial in trials
        ),
        "control_outcomes": dict(
            sorted(Counter(trial["control"]["outcome"] for trial in trials).items())
        ),
        "capability_layers": dict(
            sorted(
                Counter(
                    trial["capability"]["highest_layer_reached"] for trial in trials
                ).items()
            )
        ),
        "models": model_summaries,
        "trials": [
            {
                "cell_id": trial["protocol"]["cell_id"],
                "difficulty_stratum": trial["protocol"]["difficulty_stratum"],
                "job_name": trial["protocol"]["job_name"],
                "name": trial["trial"]["name"],
                "model": trial["trial"]["model"],
                "control_outcome": trial["control"]["outcome"],
                "highest_layer_reached": trial["capability"]["highest_layer_reached"],
                "completion": trial["trial"]["completion"],
                "completed_deals": trial["control"]["completed_deals"],
                "failed_deals": trial["result"]["failed_deals"],
                "failure_rate": trial["result"]["failure_rate"],
                "reward": trial["result"]["reward"],
                "reliability_target_met": trial["result"]["reliability_target_met"],
                "attribution_challenge_activated": trial["capability"][
                    "attribution_challenge_activated"
                ],
                "overlapping_evidence": trial["capability"][
                    "overlapping_success_failure_evidence"
                ],
                "distinct_bundles": trial["policy"]["distinct_bundles"],
                "top_bundle_share": trial["policy"]["top_bundle_share"],
                "invalid_selections": trial["control"]["invalid_selections"],
                "cost_usd": trial["trial"]["cost_usd"],
                "trial_duration_seconds": trial["trial"]["trial_duration_seconds"],
                "agent_execution_seconds": trial["trial"]["agent_execution_seconds"],
            }
            for trial in trials
        ],
    }
    return trials, comparison


def _markdown_report(comparison: dict[str, Any]) -> str:
    lines = [
        "# Reliability Is Blind Analysis",
        "",
        f"**{comparison['label']}**",
        "",
        "> Private evaluator analysis. It contains hidden supplier diagnostics and must not be exposed to an agent before or during a rollout.",
        "",
        f"Matched seeds: {comparison['matched_seed_count']}  ",
        f"Ranking allowed: {'yes' if comparison['ranking_allowed'] else 'no'}",
    ]
    if comparison["ranking_blockers"]:
        lines.extend(["", "## Ranking blockers", ""])
        lines.extend(f"- {blocker}" for blocker in comparison["ranking_blockers"])
    lines.extend(
        [
            "",
            "## Trials",
            "",
            "| Model | Control outcome | Highest layer | Deals | Reward | Attribution activated | Bundles | Invalid |",
            "|---|---|---|---:|---:|---|---:|---:|",
        ]
    )
    for trial in comparison["trials"]:
        lines.append(
            "| {model} | {control_outcome} | {highest_layer_reached} | "
            "{completed_deals} | {reward} | {activated} | {distinct_bundles} | "
            "{invalid_selections} |".format(
                **trial,
                activated=("yes" if trial["attribution_challenge_activated"] else "no"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The layers are sequential: entering the market, maintaining valid state, then making decisions after an ambiguous collective failure. Completion and reward remain the authoritative Harbor results; capability activation is diagnostic only.",
            "",
        ]
    )
    return "\n".join(lines)


def _protocol_markdown_report(comparison: dict[str, Any]) -> str:
    lines = [
        "# Reliability Is Blind Protocol",
        "",
        f"**{comparison['label']}**",
        "",
        "> Private evaluator analysis. Hidden seed strata and supplier diagnostics must not be exposed before or during a rollout.",
        "",
        f"Planned: {comparison['planned_trials']} trials across {comparison['planned_seed_cells']} seeds  ",
        f"Observed: {comparison['observed_trials']} trials  ",
        f"Matched seeds: {comparison['matched_seed_cells']}  ",
        f"Infrastructure errors: {comparison['job_error_count']}  ",
        f"Unfinished jobs: {comparison['job_unfinished_count']}  ",
        f"Retries: {comparison['job_retry_count']}  ",
        f"Ranking allowed: {'yes' if comparison['ranking_allowed'] else 'no'}",
    ]
    if comparison["issues"]:
        lines.extend(["", "## Issues", ""])
        lines.extend(f"- {issue}" for issue in comparison["issues"])
    lines.extend(
        [
            "",
            "## Models",
            "",
            "| Model | Observed | Complete | Target met | Attribution activated | Mean reward | Mean completed failure rate | Invalid | Reported cost |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for model in comparison["models"]:
        lines.append(
            "| {model} | {observed_trials}/{planned_trials} | {completed_rollouts} | "
            "{reliability_targets_met} | {attribution_challenges_activated} | "
            "{mean_reward} | {mean_completed_failure_rate} | {invalid_selections} | "
            "{reported_cost_usd} ({cost_coverage}) |".format(**model)
        )
    lines.extend(["", "## Trials", ""])
    lines.extend(
        [
            "| Seed cell | Model | Control | Layer | Deals | Failed | Reward | Target | Attribution |",
            "|---|---|---|---|---:|---:|---:|---|---|",
        ]
    )
    for trial in comparison["trials"]:
        lines.append(
            "| {cell_id} | {model} | {control_outcome} | {highest_layer_reached} | "
            "{completed_deals} | {failed_deals} | {reward} | {target} | {activated} |".format(
                **trial,
                target="yes" if trial["reliability_target_met"] else "no",
                activated=("yes" if trial["attribution_challenge_activated"] else "no"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_trial_analysis(
    trial_dir: Path,
    *,
    output_dir: Path | None = None,
    task_root: Path = DEFAULT_TASK_ROOT,
) -> Path:
    analysis = analyze_trial(trial_dir, task_root=task_root)
    destination = output_dir or trial_dir.resolve() / "analysis"
    _write_json(destination / "trial.json", analysis)
    return destination


def write_job_analysis(
    job_dir: Path,
    *,
    output_dir: Path | None = None,
    task_root: Path = DEFAULT_TASK_ROOT,
    minimum_matched_seeds: int = DEFAULT_MINIMUM_MATCHED_SEEDS,
) -> Path:
    trials, comparison = compare_job(
        job_dir,
        task_root=task_root,
        minimum_matched_seeds=minimum_matched_seeds,
    )
    destination = output_dir or job_dir.resolve() / "analysis"
    _write_json(destination / "trials.json", trials)
    _write_json(destination / "comparison.json", comparison)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "report.md").write_text(_markdown_report(comparison))
    return destination


def write_protocol_analysis(
    manifest_path: Path,
    jobs_dir: Path,
    *,
    phase: str = "full",
    output_dir: Path | None = None,
    task_root: Path = DEFAULT_TASK_ROOT,
) -> Path:
    trials, comparison = analyze_protocol(
        manifest_path,
        jobs_dir,
        phase=phase,
        task_root=task_root,
    )
    destination = output_dir or (
        jobs_dir.resolve() / f"{comparison['protocol_id']}-analysis-{phase}"
    )
    _write_json(destination / "trials.json", trials)
    _write_json(destination / "protocol.json", comparison)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "report.md").write_text(_protocol_markdown_report(comparison))
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rib-analyze",
        description="Analyze Reliability Is Blind Harbor trials without changing reward.",
    )
    parser.add_argument(
        "--task-root",
        type=Path,
        default=DEFAULT_TASK_ROOT,
        help="task source used to verify and load the frozen engine",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    trial = subparsers.add_parser("trial", help="analyze one Harbor trial")
    trial.add_argument("trial_directory", type=Path)
    trial.add_argument("--output", type=Path)
    compare = subparsers.add_parser("compare", help="analyze every trial in a job")
    compare.add_argument("job_directory", type=Path)
    compare.add_argument("--output", type=Path)
    compare.add_argument(
        "--minimum-matched-seeds",
        type=int,
        default=DEFAULT_MINIMUM_MATCHED_SEEDS,
    )
    protocol = subparsers.add_parser(
        "protocol", help="aggregate a private matched-seed protocol"
    )
    protocol.add_argument("manifest", type=Path)
    protocol.add_argument("jobs_directory", type=Path)
    protocol.add_argument("--phase", choices=("canary", "full"), default="full")
    protocol.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "trial":
            destination = write_trial_analysis(
                args.trial_directory,
                output_dir=args.output,
                task_root=args.task_root,
            )
        elif args.command == "compare":
            if args.minimum_matched_seeds <= 0:
                raise AnalysisError("minimum matched seeds must be positive")
            destination = write_job_analysis(
                args.job_directory,
                output_dir=args.output,
                task_root=args.task_root,
                minimum_matched_seeds=args.minimum_matched_seeds,
            )
        else:
            destination = write_protocol_analysis(
                args.manifest,
                args.jobs_directory,
                phase=args.phase,
                output_dir=args.output,
                task_root=args.task_root,
            )
    except AnalysisError as exc:
        print(f"rib-analyze: {exc}", file=sys.stderr)
        return 2
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
