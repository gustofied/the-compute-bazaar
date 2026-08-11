from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from statistics import mean, median
from typing import Any

from common import AdjudicationError, load_json, sha256_file, write_json
from replay import (
    DEFAULT_COMMITMENT,
    DEFAULT_OUTPUT_ROOT,
    RAW_JOBS,
    REPO_ROOT,
    replay_key,
    validate_attempt_record,
    validate_commitment,
)


SCHEMA_VERSION = "compute-bazaar-bench.transactions.adjudication-analysis.v1"
DEFAULT_ATTEMPT = (
    DEFAULT_OUTPUT_ROOT
    / "transactions-comparison-v1-adjudication-replay-001"
    / "attempt-001"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "compute-bazaar-bench/jobs/reports"
    / "transactions-comparison-v1-adjudication-replay-001"
)
DEFAULT_MODAL_BILLING = (
    DEFAULT_ATTEMPT.parent / "modal-billing-snapshot-001.json"
)
DEFAULT_PROTOCOL_AMENDMENT = (
    Path(__file__).resolve().parent
    / "adjudication-replay-001.modal-amendment.json"
)
MODEL_ORDER = (
    "deepseek-v4-flash-0731",
    "gpt-5.6-luna",
    "glm-5.2",
)
MODEL_LABELS = {
    "deepseek-v4-flash-0731": "DeepSeek V4 Flash 0731",
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "glm-5.2": "GLM 5.2",
}
TASK_ORDER = (
    "normalize-buyer-mandate",
    "draft-capacity-data-room-population-plan",
    "compare-capacity-agreement-against-term-sheet",
)
TASK_LABELS = {
    "normalize-buyer-mandate": "Intake",
    "draft-capacity-data-room-population-plan": "Diligence",
    "compare-capacity-agreement-against-term-sheet": "Contracting",
}


def _semantic(details: dict[str, Any]) -> tuple[int, int, list[dict[str, Any]]]:
    criteria = [
        item
        for dimension, detail in details.items()
        if dimension != "output-integrity" and isinstance(detail, dict)
        for item in detail.get("criteria", [])
        if isinstance(item, dict)
    ]
    passes = sum(float(item.get("value", 0)) == 1.0 for item in criteria)
    return passes, len(criteria), criteria


def _phase_record(
    reward: dict[str, Any], details: dict[str, Any]
) -> dict[str, Any]:
    passes, count, criteria = _semantic(details)
    if count == 0:
        raise AdjudicationError("semantic adjudication has no criteria")
    return {
        "semantic_passes": passes,
        "semantic_criteria": count,
        "semantic_score": passes / count,
        "reward": reward["reward"],
        "all_pass": reward["all_pass"],
        "output_integrity": reward["output-integrity"],
        "criteria": criteria,
    }


def _criterion_transitions(
    original: list[dict[str, Any]], amended: list[dict[str, Any]]
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    original_by_id = {item["id"]: item for item in original}
    amended_by_id = {item["id"]: item for item in amended}
    if set(original_by_id) != set(amended_by_id):
        raise AdjudicationError("v1/v2 criterion IDs do not match")
    counts = {"fail_to_pass": 0, "pass_to_fail": 0, "unchanged_pass": 0, "unchanged_fail": 0}
    changes: list[dict[str, Any]] = []
    for criterion_id in sorted(original_by_id):
        before = float(original_by_id[criterion_id]["value"])
        after = float(amended_by_id[criterion_id]["value"])
        transition = (
            "fail_to_pass"
            if before == 0 and after == 1
            else "pass_to_fail"
            if before == 1 and after == 0
            else "unchanged_pass"
            if before == 1
            else "unchanged_fail"
        )
        counts[transition] += 1
        if before != after or (
            original_by_id[criterion_id].get("description")
            != amended_by_id[criterion_id].get("description")
        ):
            changes.append(
                {
                    "id": criterion_id,
                    "transition": transition,
                    "original_value": before,
                    "amended_value": after,
                    "original_description": original_by_id[criterion_id].get(
                        "description"
                    ),
                    "amended_description": amended_by_id[criterion_id].get(
                        "description"
                    ),
                    "original_reasoning": original_by_id[criterion_id].get(
                        "reasoning"
                    ),
                    "amended_reasoning": amended_by_id[criterion_id].get(
                        "reasoning"
                    ),
                }
            )
    return counts, changes


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "min": None, "max": None}
    return {
        "mean": mean(values),
        "median": median(values),
        "min": min(values),
        "max": max(values),
    }


def _phase_summary(records: list[dict[str, Any]], phase: str) -> dict[str, Any]:
    tasks: dict[str, Any] = {}
    total_passes = 0
    total_criteria = 0
    for task_name in TASK_ORDER:
        selected = [record for record in records if record["task"] == task_name]
        passes = sum(record[phase]["semantic_passes"] for record in selected)
        criteria = sum(record[phase]["semantic_criteria"] for record in selected)
        total_passes += passes
        total_criteria += criteria
        tasks[task_name] = {
            "retained": len(selected),
            "all_pass": sum(record[phase]["all_pass"] == 1 for record in selected),
            "semantic": _stats(
                [record[phase]["semantic_score"] for record in selected]
            ),
            "reward": _stats([float(record[phase]["reward"]) for record in selected]),
            "semantic_passes": passes,
            "semantic_criteria": criteria,
            "criterion_pass_rate": passes / criteria if criteria else None,
            "attempt_values": [
                record[phase]["semantic_score"] for record in selected
            ],
        }
    task_means = [
        tasks[task]["semantic"]["mean"]
        for task in TASK_ORDER
        if tasks[task]["semantic"]["mean"] is not None
    ]
    return {
        "tasks": tasks,
        "retained": len(records),
        "all_pass": sum(record[phase]["all_pass"] == 1 for record in records),
        "strict_all_pass_rate": (
            sum(record[phase]["all_pass"] == 1 for record in records) / len(records)
            if records
            else None
        ),
        "macro_semantic_mean": mean(task_means) if task_means else None,
        "criterion_pass_rate": total_passes / total_criteria if total_criteria else None,
        "semantic_passes": total_passes,
        "semantic_criteria": total_criteria,
    }


def _transition_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    totals: defaultdict[str, int] = defaultdict(int)
    by_task: dict[str, dict[str, int]] = {}
    for task_name in TASK_ORDER:
        task_totals: defaultdict[str, int] = defaultdict(int)
        for record in records:
            if record["task"] != task_name:
                continue
            for key, value in record["criterion_transitions"].items():
                task_totals[key] += value
                totals[key] += value
        by_task[task_name] = dict(task_totals)
    return {"total": dict(totals), "by_task": by_task}


def _gate_cost(
    pre_gate: Path, post_gate: Path, modal_billing_path: Path
) -> dict[str, Any]:
    before = load_json(pre_gate)
    after = load_json(post_gate)
    if before.get("record_kind") != "openrouter_spend_gate" or after.get(
        "record_kind"
    ) != "openrouter_spend_gate":
        raise AdjudicationError("cost snapshots are not OpenRouter spend gates")
    before_usage = Decimal(str(before["account"]["total_usage_usd"]))
    after_usage = Decimal(str(after["account"]["total_usage_usd"]))
    key_before = Decimal(str(before["account"]["key_usage_usd"]))
    key_after = Decimal(str(after["account"]["key_usage_usd"]))
    account_delta = after_usage - before_usage
    key_delta = key_after - key_before
    if account_delta != key_delta or account_delta < 0:
        raise AdjudicationError("OpenRouter account/key cost deltas do not reconcile")
    modal_billing = load_json(modal_billing_path)
    if modal_billing.get("modal_app_id") != "ap-vI0CFF4ufNOsjk8TaXDOXB":
        raise AdjudicationError("Modal billing observation uses the wrong app")
    return {
        "openrouter_judge_usd": float(account_delta),
        "openrouter_judge_usd_exact": format(account_delta.normalize(), "f"),
        "attribution": (
            "Difference in both account usage and this key's usage between the "
            "immediate pre-run and post-run snapshots; OpenRouter did not retain "
            "per-judge-call usage in RewardKit output."
        ),
        "pre_gate": {"path": str(pre_gate), "sha256": sha256_file(pre_gate)},
        "post_gate": {"path": str(post_gate), "sha256": sha256_file(post_gate)},
        "modal_usd": None,
        "modal_note": (
            "Modal exposes hourly application billing, but sandbox tags were absent "
            "and the final billing interval was unsettled at analysis time; no exact "
            "replay-only dollar amount is claimed."
        ),
        "modal_billing_observation": {
            "path": str(modal_billing_path),
            "sha256": sha256_file(modal_billing_path),
            "settled_app_cost_usd": modal_billing.get("settled_app_cost_usd"),
            "scope": modal_billing.get("scope"),
            "attribution_limit": modal_billing.get("attribution_limit"),
        },
    }


def validate_protocol_amendment(
    amendment_path: Path,
    commitment_path: Path,
    run_path: Path,
    run: dict[str, Any],
) -> dict[str, Any]:
    amendment = load_json(amendment_path)
    if amendment.get("record_kind") != "adjudication_replay_protocol_amendment":
        raise AdjudicationError("invalid adjudication protocol amendment")

    parent = amendment.get("parent_commitment") or {}
    parent_path = (amendment_path.parent / parent.get("path", "")).resolve()
    if parent_path != commitment_path.resolve() or parent.get("sha256") != sha256_file(
        commitment_path
    ):
        raise AdjudicationError("protocol amendment does not bind the commitment")

    completed = amendment.get("completed_run") or {}
    completed_path = (REPO_ROOT / completed.get("path", "")).resolve()
    if completed_path != run_path.resolve() or completed.get("sha256") != sha256_file(
        run_path
    ):
        raise AdjudicationError("protocol amendment does not bind the completed run")
    if completed.get("status") != run.get("status") or completed.get(
        "valid_grades"
    ) != run.get("valid"):
        raise AdjudicationError("protocol amendment run summary does not reconcile")

    runtime_change = amendment.get("runtime_change") or {}
    if runtime_change.get("backend") != "modal_sandbox":
        raise AdjudicationError("protocol amendment does not authorize Modal")
    if runtime_change.get("modal_app_id") != "ap-vI0CFF4ufNOsjk8TaXDOXB":
        raise AdjudicationError("protocol amendment uses the wrong Modal app")

    implementation = amendment.get("implementation") or {}
    for path_key, hash_key in (
        ("modal_backend_path", "modal_backend_sha256"),
        ("replay_path", "replay_sha256"),
    ):
        source_path = (amendment_path.parent / implementation.get(path_key, "")).resolve()
        if implementation.get(hash_key) != sha256_file(source_path):
            raise AdjudicationError(f"protocol amendment {path_key} hash mismatch")

    preflight = amendment.get("mocked_preflight") or {}
    preflight_path = (REPO_ROOT / preflight.get("path", "")).resolve()
    if preflight.get("sha256") != sha256_file(preflight_path):
        raise AdjudicationError("protocol amendment preflight hash mismatch")
    if preflight.get("status") != "passed" or preflight.get("paid_judge_calls") != 0:
        raise AdjudicationError("protocol amendment preflight did not pass cleanly")

    runtime_images = amendment.get("runtime_images") or {}
    run_builds = run.get("runtime_builds") or {}
    if set(runtime_images) != set(run_builds):
        raise AdjudicationError("protocol amendment runtime image set mismatch")
    for task_name, expected in runtime_images.items():
        actual = run_builds[task_name]
        if actual.get("backend") != "modal_sandbox" or any(
            actual.get(field) != expected.get(field)
            for field in ("modal_image_object_id", "context_tree_sha256")
        ):
            raise AdjudicationError(
                f"protocol amendment runtime identity mismatch: {task_name}"
            )
    return amendment


def analyze(
    commitment_path: Path,
    attempt_dir: Path,
    pre_gate: Path,
    post_gate: Path,
    modal_billing_path: Path,
    protocol_amendment_path: Path,
) -> dict[str, Any]:
    commitment = validate_commitment(commitment_path)
    run_path = attempt_dir / "adjudication-run.json"
    run = load_json(run_path)
    if run.get("status") != "complete" or run.get("valid") != 43:
        raise AdjudicationError("adjudication attempt is not a complete 43-output replay")
    if run.get("source_commitment_sha256") != sha256_file(commitment_path):
        raise AdjudicationError("adjudication run uses a different commitment")
    amendment = validate_protocol_amendment(
        protocol_amendment_path, commitment_path, run_path, run
    )

    source_analysis_path = REPO_ROOT / commitment["source_analysis"]["path"]
    source_analysis = load_json(source_analysis_path)
    source_records = {
        (model_key, record["trial"]): record
        for model_key, model in source_analysis["models"].items()
        if isinstance(model, dict)
        for record in model.get("records", [])
        if isinstance(record, dict)
    }
    records: list[dict[str, Any]] = []
    modal_wall_seconds = 0.0
    completed_semantic_judge_batches = 0
    for source in commitment["sources"]:
        record_dir = attempt_dir / "records" / replay_key(source)
        replay_record = validate_attempt_record(source, record_dir)
        if replay_record["status"] != "valid":
            raise AdjudicationError(f"non-valid replay record: {replay_key(source)}")
        original_reward_path = (
            RAW_JOBS
            / source["source_job"]
            / source["source_trial"]
            / "verifier/reward.json"
        )
        original_details_path = original_reward_path.with_name("reward-details.json")
        original = _phase_record(
            load_json(original_reward_path), load_json(original_details_path)
        )
        amended_details = load_json(record_dir / "reward-details.json")
        semantic_batches = sum(
            key != "output-integrity" and isinstance(detail, dict)
            for key, detail in amended_details.items()
        )
        expected_batches = commitment["judge"]["semantic_batches_per_output"]
        if semantic_batches != expected_batches:
            raise AdjudicationError(
                f"semantic judge batch count mismatch: {replay_key(source)}"
            )
        completed_semantic_judge_batches += semantic_batches
        amended = _phase_record(
            load_json(record_dir / "reward.json"), amended_details
        )
        transitions, changed_criteria = _criterion_transitions(
            original["criteria"], amended["criteria"]
        )
        source_record = source_records[
            (source["source_model_key"], source["source_trial"])
        ]
        sandbox = replay_record.get("runtime_identity", {}).get("last_sandbox") or {}
        modal_wall_seconds += float(sandbox.get("wall_seconds") or 0)
        records.append(
            {
                "replay_key": replay_key(source),
                "job": source["source_job"],
                "trial": source["source_trial"],
                "model_key": source["source_model_key"],
                "task": source["task"],
                "artifact_sha256": source["artifact"]["sha256"],
                "original_task_digest": source["original_task_digest"],
                "corrected_task_digest": source["corrected_task_digest"],
                "original": original,
                "amended": amended,
                "semantic_delta": amended["semantic_score"]
                - original["semantic_score"],
                "criterion_transitions": transitions,
                "changed_criteria": changed_criteria,
                "agent_seconds": source_record.get("agent_seconds"),
                "duration_seconds": source_record.get("duration_seconds"),
                "tokens": source_record.get("tokens"),
                "trajectory": source_record.get("trajectory"),
                "visual_review": source_record.get("visual_review"),
                "replay_wall_seconds": sandbox.get("wall_seconds"),
                "modal_image_object_id": replay_record.get("runtime_identity", {}).get(
                    "modal_image_object_id"
                ),
                "modal_sandbox_object_id": sandbox.get("sandbox_object_id"),
            }
        )

    models: dict[str, Any] = {}
    for model_key in MODEL_ORDER:
        selected = [record for record in records if record["model_key"] == model_key]
        source_model = source_analysis["models"][model_key]
        models[model_key] = {
            "label": MODEL_LABELS[model_key],
            "job": source_model["job"],
            "retained": len(selected),
            "original": _phase_summary(selected, "original"),
            "amended": _phase_summary(selected, "amended"),
            "criterion_transitions": _transition_summary(selected),
            "document_craft": source_model.get("visual"),
            "agent_latency": source_model.get("latency"),
            "agent_tokens": source_model.get("summary", {}).get("token_totals"),
            "agent_reported_cost_usd": source_model.get("costs", {}).get(
                "agent_reported_usd"
            ),
            "records": selected,
        }

    transition_totals: defaultdict[str, int] = defaultdict(int)
    for model in models.values():
        for key, value in model["criterion_transitions"]["total"].items():
            transition_totals[key] += value
    criterion_decisions = sum(transition_totals.values())
    description_changes = {
        (record["task"], item["id"])
        for record in records
        for item in record["changed_criteria"]
        if item.get("original_description") != item.get("amended_description")
    }
    original_ranking = sorted(
        MODEL_ORDER,
        key=lambda key: models[key]["original"]["macro_semantic_mean"],
        reverse=True,
    )
    amended_ranking = sorted(
        MODEL_ORDER,
        key=lambda key: models[key]["amended"]["macro_semantic_mean"],
        reverse=True,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "adjudication_replay_analysis",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "labels": commitment["labels"],
        "adjudication_id": commitment["adjudication_id"],
        "agent_rerun": False,
        "source_commitment": {
            "path": str(commitment_path),
            "sha256": sha256_file(commitment_path),
        },
        "protocol_amendment": {
            "path": str(protocol_amendment_path),
            "sha256": sha256_file(protocol_amendment_path),
            "amendment_id": amendment["amendment_id"],
            "recording_timing": amendment["recording_timing"],
        },
        "run": {"path": str(run_path), "sha256": sha256_file(run_path)},
        "denominator": {
            "selected_official_slots": 45,
            "retained_outputs_replayed": 43,
            "original_infrastructure_exclusions": 2,
            "valid_amended_grades": 43,
            "replay_infrastructure_failures": 0,
            "replay_level_retries": 0,
            "completed_semantic_judge_batches": completed_semantic_judge_batches,
            "provider_internal_retries": None,
        },
        "costs": _gate_cost(pre_gate, post_gate, modal_billing_path),
        "replay_runtime": {
            "backend": "Modal sandbox",
            "total_sandbox_wall_seconds": modal_wall_seconds,
            "mean_sandbox_wall_seconds": modal_wall_seconds / len(records),
            "runtime_builds": run["runtime_builds"],
        },
        "models": models,
        "records": records,
        "semantic_review": {
            "original_all_pass": sum(
                model["original"]["all_pass"] for model in models.values()
            ),
            "amended_all_pass": sum(
                model["amended"]["all_pass"] for model in models.values()
            ),
            "criterion_decisions": criterion_decisions,
            "criterion_flips": transition_totals["fail_to_pass"]
            + transition_totals["pass_to_fail"],
            "criterion_decision_changes": transition_totals["fail_to_pass"]
            + transition_totals["pass_to_fail"],
            "criterion_flip_rate": (
                (
                    transition_totals["fail_to_pass"]
                    + transition_totals["pass_to_fail"]
                )
                / criterion_decisions
            ),
            "net_pass_change": transition_totals["fail_to_pass"]
            - transition_totals["pass_to_fail"],
            "criteria_with_description_changes": len(description_changes),
            "transition_totals": dict(transition_totals),
            "original_ranking": original_ranking,
            "amended_ranking": amended_ranking,
            "ranking_unchanged": original_ranking == amended_ranking,
            "ranking_metric": "equal_task_macro_semantic_mean",
            "interpretation": (
                "The equal-task macro-semantic ordering and broad task pattern "
                "survived correction, but individual criterion outcomes differed "
                "between adjudication procedures. Because criterion framing and "
                "evidence context changed and judging was unseeded, this disagreement "
                "does not measure judge repeatability or isolate the verifier repair."
            ),
        },
        "limitations": [
            "Only verifier evidence and criteria changed; no agent or model was rerun.",
            "The 43 DOCX artifacts, instructions, matter files, tools, and output contracts are byte-identical to the original comparison.",
            "GPT-5.4 judging remains unseeded and may vary between the original and amended calls.",
            "GPT-5.4 judged GPT-5.6 Luna outputs; possible same-family correlated bias was not measured.",
            "OpenRouter provider-internal retries and per-call identities were not retained; only completed semantic judge batches and replay-level retries are reported.",
            "The three tasks are linked checkpoints from one synthetic matter, not independent benchmark samples.",
            "Document craft, agent latency, and agent tokens are carried from the original run because the artifacts and trajectories did not change.",
        ],
    }


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def _number(value: float | None, digits: int = 4) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_report(analysis: dict[str, Any]) -> str:
    lines = [
        "# Transactions comparison v1: amended adjudication",
        "",
        "The original Harbor jobs and scores remain unchanged. The amended scores replay verifier v2 over the same 43 preserved DOCX outputs; no agent was rerun.",
        "",
        "The Gate 1 commitment named local Docker. Adam required Modal before Gate 2; the recorded protocol amendment binds that authorized runtime change to the completed run.",
        "",
        "## Results",
        "",
        "| Model | Retained | v1 all pass | v2 all pass | v1 macro | v2 macro | v2 criteria |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model_key in MODEL_ORDER:
        model = analysis["models"][model_key]
        original = model["original"]
        amended = model["amended"]
        lines.append(
            "| "
            + " | ".join(
                (
                    model["label"],
                    str(model["retained"]),
                    f"{original['all_pass']}/{model['retained']}",
                    f"{amended['all_pass']}/{model['retained']}",
                    _number(original["macro_semantic_mean"]),
                    _number(amended["macro_semantic_mean"]),
                    f"{amended['semantic_passes']}/{amended['semantic_criteria']} ({_pct(amended['criterion_pass_rate'])})",
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Strict all-pass remains the headline. Macro semantic and pooled criterion pass are diagnostics for these three linked checkpoints.",
            "",
            "## Task Diagnostics",
            "",
            "| Model | Task | v1 mean | v2 mean | Delta |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for model_key in MODEL_ORDER:
        model = analysis["models"][model_key]
        for task_name in TASK_ORDER:
            before = model["original"]["tasks"][task_name]["semantic"]["mean"]
            after = model["amended"]["tasks"][task_name]["semantic"]["mean"]
            delta = after - before if before is not None and after is not None else None
            lines.append(
                f"| {model['label']} | {TASK_LABELS[task_name]} | {_number(before)} | {_number(after)} | {_number(delta, 4)} |"
            )
    lines.extend(
        [
            "",
            "## Unchanged Run Evidence",
            "",
            "| Model | Craft good / mixed / poor (44 docs) | Median agent latency (43 trials) | Agent input / output tokens (43 trials) | Agent cost |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for model_key in MODEL_ORDER:
        model = analysis["models"][model_key]
        craft = model.get("document_craft") or {}
        latency = (model.get("agent_latency") or {}).get("agent_execution") or {}
        tokens = model.get("agent_tokens") or {}
        cost = model.get("agent_reported_cost_usd")
        lines.append(
            f"| {model['label']} | {craft.get('good', 0)} / {craft.get('mixed', 0)} / {craft.get('poor', 0)} | "
            f"{_number(latency.get('median'), 1)}s | {tokens.get('input', 0):,} / {tokens.get('output', 0):,} | "
            f"{'—' if cost is None else f'${cost:.4f}'} |"
        )
    lines.extend(
        [
            "",
            "Latency and token totals cover the 43 retained trials. Craft also includes one successfully collected Luna document from a later infrastructure-excluded trial.",
        ]
    )
    transitions: defaultdict[str, int] = defaultdict(int)
    for model in analysis["models"].values():
        for key, value in model["criterion_transitions"]["total"].items():
            transitions[key] += value
    costs = analysis["costs"]
    review = analysis["semantic_review"]
    lines.extend(
        [
            "",
            "## Adjudication Change",
            "",
            f"Across all criterion decisions, `{transitions['fail_to_pass']}` changed from fail to pass, `{transitions['pass_to_fail']}` changed from pass to fail, `{transitions['unchanged_pass']}` remained pass, and `{transitions['unchanged_fail']}` remained fail.",
            "",
            f"That is `{review['criterion_decision_changes']}/{review['criterion_decisions']}` decisions ({_pct(review['criterion_flip_rate'])}) differing between verifier v1 and v2 on byte-identical outputs, with a net gain of `{review['net_pass_change']}` passes. The equal-task macro-semantic ordering remains GLM, Luna, DeepSeek.",
            "",
            f"Verifier v2 replaces the unsupported C-058 test with a source-supported site-control test, changes the wording of `{review['criteria_with_description_changes']}` supported criteria, and gives each criterion complete normalized matter or precise cited evidence. The visible task surface and every submitted DOCX remain unchanged. Because criterion framing and evidence context changed and GPT-5.4 judging is unseeded, the 5.3% disagreement is not a judge-repeatability estimate and cannot isolate the effect of the verifier repairs.",
            "",
            "## Execution",
            "",
            f"The replay produced `{analysis['denominator']['valid_amended_grades']}/43` valid amended grades containing `{analysis['denominator']['completed_semantic_judge_batches']}` completed GPT-5.4 semantic judge batches. There were no replay-level retries or recorded judge errors; OpenRouter provider-internal retries and per-call identities were not retained. The OpenRouter key/account differential was `${costs['openrouter_judge_usd']:.6f}`. Exact replay-only Modal dollars are unavailable and remain null.",
            "",
            f"Protocol amendment: `{analysis['protocol_amendment']['amendment_id']}` (`{analysis['protocol_amendment']['sha256']}`).",
            "",
            "Labels:",
            "",
            f"- **{analysis['labels']['original']}**",
            f"- **{analysis['labels']['amended']}**",
            "",
            "## Limits",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in analysis["limitations"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze verifier-v2 replay results.")
    parser.add_argument("--commitment", type=Path, default=DEFAULT_COMMITMENT)
    parser.add_argument("--attempt", type=Path, default=DEFAULT_ATTEMPT)
    parser.add_argument(
        "--pre-gate",
        type=Path,
        default=DEFAULT_ATTEMPT.parent / "spend-gates/openrouter-gate-002.json",
    )
    parser.add_argument(
        "--post-gate",
        type=Path,
        default=DEFAULT_ATTEMPT.parent / "spend-gates/openrouter-gate-007.json",
    )
    parser.add_argument(
        "--modal-billing", type=Path, default=DEFAULT_MODAL_BILLING
    )
    parser.add_argument(
        "--protocol-amendment",
        type=Path,
        default=DEFAULT_PROTOCOL_AMENDMENT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    analysis = analyze(
        args.commitment,
        args.attempt,
        args.pre_gate,
        args.post_gate,
        args.modal_billing,
        args.protocol_amendment,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "analysis.json", analysis)
    (args.output / "report.md").write_text(render_report(analysis))
    print(
        f"wrote {len(analysis['records'])} amended adjudications to {args.output}"
    )


if __name__ == "__main__":
    main()
