"""Build the Transactions release audit and public summary."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
TRANSACTIONS_ROOT = ROOT.parents[1]
TOOLING_ROOT = TRANSACTIONS_ROOT / "tooling"
if str(TOOLING_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLING_ROOT))

from analysis import (  # noqa: E402
    ANALYSIS_SCHEMA_VERSION,
    AnalysisError,
    aggregate,
    classify_trial,
    expected_tasks,
    load_object,
    repeated_misses,
    sha256,
    validate_lock,
)
from comparison import validate_terminal_job  # noqa: E402


RELEASE_SUMMARY_SCHEMA = "compute-bazaar-bench.transactions.release-summary.v1"


def job_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    runtime = protocol["runtime"]
    model = protocol["models"][0]
    attempts = int(protocol["official_run"]["attempts_per_task"])
    return {
        "tasks": protocol["tasks"],
        "agent": {
            "name": runtime["agent"],
            "version": runtime["agent_version"],
            "model": model["agent_model"],
            "provider_host": protocol["routing"]["provider_host"],
        },
        "environment": {
            "name": runtime["environment"],
            "modal_vm_runtime": runtime["modal_vm_runtime"],
        },
        "attempts_per_task": attempts,
        "planned_trials": int(protocol["official_run"]["planned_trials_total"]),
    }


def analyze_native_job(
    job_dir: Path,
    protocol_path: Path,
    craft_review_path: Path | None = None,
) -> dict[str, Any]:
    protocol = load_object(protocol_path)
    frozen = job_protocol(protocol)
    tasks = expected_tasks(frozen)
    validate_terminal_job(job_dir, frozen["planned_trials"])
    validate_lock(load_object(job_dir / "lock.json"), frozen, tasks)

    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for result_path in sorted(job_dir.glob("*/result.json")):
        trial_dir = result_path.parent
        result = load_object(result_path)
        task_name = str(result.get("task_name", "")).removeprefix("gustofied/")
        if task_name not in tasks:
            raise AnalysisError(f"unexpected task in {trial_dir}: {task_name}")
        counts[task_name] += 1
        record = classify_trial(
            trial_dir,
            tasks[task_name],
            frozen["agent"],
            missing_artifact_as_invalid=True,
        )
        record["job"] = job_dir.name
        record["model_key"] = protocol["models"][0]["key"]
        artifact_path = trial_dir / "artifacts" / "app" / tasks[task_name]["deliverable"]
        record["provenance"] = {
            "result_sha256": maybe_sha256(trial_dir / "result.json"),
            "artifact_manifest_sha256": maybe_sha256(
                trial_dir / "artifacts" / "manifest.json"
            ),
            "artifact_sha256": maybe_sha256(artifact_path),
            "trajectory_sha256": maybe_sha256(
                trial_dir / "agent" / "trajectory.json"
            ),
            "reward_sha256": maybe_sha256(trial_dir / "verifier" / "reward.json"),
            "reward_details_sha256": maybe_sha256(
                trial_dir / "verifier" / "reward-details.json"
            ),
        }
        if record.get("infrastructure_error") is None:
            trajectory = record.get("trajectory") or {}
            if not trajectory.get("complete_atif"):
                record["infrastructure_error"] = "ATIF trajectory is incomplete"
            elif record.get("agent_invalid_output"):
                details = load_object(trial_dir / "verifier" / "reward-details.json")
                record["invalid_output_reason"] = str(
                    details.get("message") or "invalid required DOCX"
                )
        records.append(record)

    expected_count = frozen["attempts_per_task"]
    expected_counts = Counter({name: expected_count for name in tasks})
    if counts != expected_counts:
        raise AnalysisError(
            f"task result counts do not match release protocol: {dict(counts)}"
        )

    craft_sha = None
    if craft_review_path is not None:
        attach_craft_review(records, craft_review_path, protocol)
        craft_sha = sha256(craft_review_path)

    summary = aggregate(records, tasks)
    output = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "release_summary_schema": RELEASE_SUMMARY_SCHEMA,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(protocol_path),
        "job": job_dir.name,
        "job_result_sha256": sha256(job_dir / "result.json"),
        "job_lock_sha256": sha256(job_dir / "lock.json"),
        "job_config_sha256": sha256(job_dir / "config.json"),
        "execution_origin": "fresh_native_harbor",
        "summary": summary,
        "counts": trial_counts(records, frozen["planned_trials"]),
        "visual_summary": craft_summary(records, tasks),
        "visual_review_sha256": craft_sha,
        "repeated_misses": repeated_misses(records),
        "trials": records,
    }
    return output


def maybe_sha256(path: Path) -> str | None:
    return sha256(path) if path.is_file() else None


def attach_craft_review(
    records: list[dict[str, Any]],
    path: Path,
    protocol: dict[str, Any],
) -> None:
    review = load_object(path)
    items = review.get("trials")
    if not isinstance(items, dict):
        raise AnalysisError("craft review must contain a trials object")
    expected = {
        str(record["trial"])
        for record in records
        if record.get("infrastructure_error") is None
        and not record.get("agent_invalid_output")
    }
    if set(items) != expected:
        raise AnalysisError(
            "craft review must cover exactly the valid DOCX artifacts; "
            f"missing={sorted(expected - set(items))} extra={sorted(set(items) - expected)}"
        )

    rubric_path = ROOT / protocol["reporting"]["craft_rubric_path"]
    rubric = load_object(rubric_path)
    rubric_ids = {item["id"] for item in rubric["criteria"]}
    critical = {item["id"] for item in rubric["criteria"] if item["critical"]}
    for record in records:
        item = items.get(str(record["trial"]))
        if item is None:
            continue
        values = item.get("criterion_values")
        if not isinstance(values, dict) or set(values) != rubric_ids:
            raise AnalysisError(f"craft criteria mismatch for {record['trial']}")
        if any(not isinstance(value, bool) for value in values.values()):
            raise AnalysisError(f"unfinished craft review for {record['trial']}")
        if not isinstance(item.get("page_count"), int) or item["page_count"] < 1:
            raise AnalysisError(f"invalid page count for {record['trial']}")
        failed = {criterion_id for criterion_id, value in values.items() if not value}
        expected_rating = "poor" if failed & critical else "mixed" if failed else "good"
        if item.get("practical_usability") != expected_rating:
            raise AnalysisError(f"craft rating mismatch for {record['trial']}")
        record["visual_review"] = {
            **item,
            "clipping": not values["no-clipping"],
            "overlap": not values["no-overlap"],
        }


def trial_counts(records: list[dict[str, Any]], planned: int) -> dict[str, int]:
    infrastructure = sum(record.get("infrastructure_error") is not None for record in records)
    invalid = sum(
        record.get("infrastructure_error") is None
        and bool(record.get("agent_invalid_output"))
        for record in records
    )
    return {
        "planned": planned,
        "completed": len(records),
        "scored": len(records) - infrastructure,
        "valid_docx": len(records) - infrastructure - invalid,
        "agent_invalid_output": invalid,
        "infrastructure": infrastructure,
    }


def craft_summary(
    records: list[dict[str, Any]], tasks: dict[str, dict[str, Any]]
) -> dict[str, dict[str, int]]:
    output: dict[str, dict[str, int]] = {}
    for task_name in tasks:
        ratings = Counter(
            str((record.get("visual_review") or {}).get("practical_usability"))
            for record in records
            if record.get("task") == task_name and record.get("visual_review")
        )
        output[task_name] = {
            "good": ratings["good"],
            "mixed": ratings["mixed"],
            "poor": ratings["poor"],
            "reviewed": ratings["good"] + ratings["mixed"] + ratings["poor"],
        }
    return output


def _numeric(values: Iterable[Any]) -> list[float]:
    return [float(value) for value in values if isinstance(value, (int, float))]


def _median(values: Iterable[Any]) -> float | None:
    items = _numeric(values)
    return median(items) if items else None


def _craft_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        str((record.get("visual_review") or {}).get("practical_usability"))
        for record in records
        if record.get("visual_review")
    )
    return {
        "good": counts["good"],
        "mixed": counts["mixed"],
        "poor": counts["poor"],
        "reviewed": counts["good"] + counts["mixed"] + counts["poor"],
    }


def _telemetry(records: list[dict[str, Any]]) -> dict[str, Any]:
    tokens = [record.get("tokens") or {} for record in records]
    costs = [record.get("reported_cost_usd") for record in records]
    complete_costs = bool(costs) and all(isinstance(value, (int, float)) for value in costs)
    return {
        "median_agent_seconds": _median(record.get("agent_seconds") for record in records),
        "median_input_tokens": _median(item.get("input") for item in tokens),
        "median_cache_tokens": _median(item.get("cache") for item in tokens),
        "median_output_tokens": _median(item.get("output") for item in tokens),
        "agent_cost_usd": sum(float(value) for value in costs) if complete_costs else None,
        "judge_cost_usd": None,
        "modal_cost_usd": None,
    }


def native_row(
    protocol: dict[str, Any], native: dict[str, Any]
) -> dict[str, Any]:
    records = [
        record
        for record in native["trials"]
        if record.get("infrastructure_error") is None
    ]
    summary = native["summary"]
    telemetry = _telemetry(records)
    if native["counts"]["valid_docx"] == 0:
        telemetry["judge_cost_usd"] = 0.0
    return {
        "model_key": protocol["models"][0]["key"],
        "model": protocol["models"][0]["display_name"],
        "job": native["job"],
        "execution_origin": "fresh_native_harbor",
        "execution_label": "Fresh Harbor run",
        "planned": native["counts"]["planned"],
        "completed": native["counts"]["completed"],
        "scored": native["counts"]["scored"],
        "valid_docx": native["counts"]["valid_docx"],
        "invalid_output": native["counts"]["agent_invalid_output"],
        "invalid_output_reasons": dict(
            sorted(
                Counter(
                    str(record.get("invalid_output_reason") or "invalid required DOCX")
                    for record in records
                    if record.get("agent_invalid_output")
                ).items()
            )
        ),
        "infrastructure": native["counts"]["infrastructure"],
        "strict_all_pass": sum(record.get("all_pass") == 1.0 for record in records),
        "strict_all_pass_rate": summary["strict_all_pass_rate"],
        "criterion_passes": summary["semantic_passes"],
        "criterion_total": summary["semantic_criteria"],
        "criterion_pass_rate": summary["micro_semantic_rate"],
        "criterion_evaluation": (
            "not_run_output_gate"
            if native["counts"]["valid_docx"] == 0
            and native["counts"]["scored"] > 0
            else "semantic_judge"
        ),
        "semantic_judge_batches": (
            0 if native["counts"]["valid_docx"] == 0 else None
        ),
        "equal_task_macro": summary["macro_semantic_mean"],
        "craft": _craft_counts(records),
        "telemetry": telemetry,
        "trajectory_observations": summary.get("trajectory", {}),
        "tasks": summary["tasks"],
    }


def replay_row(
    protocol: dict[str, Any],
    model_key: str,
    model_name: str,
    model_run: dict[str, Any],
) -> dict[str, Any]:
    records = [record for record in model_run["records"] if isinstance(record, dict)]
    amended = model_run["amended"]
    planned = int(protocol["official_run"]["planned_trials_per_model"])
    retained = int(amended["retained"])
    return {
        "model_key": model_key,
        "model": model_name,
        "job": model_run["job"],
        "execution_origin": "preserved_output_adjudication",
        "execution_label": "Earlier output, regraded",
        "planned": planned,
        "completed": planned,
        "scored": retained,
        "valid_docx": retained,
        "invalid_output": 0,
        "invalid_output_reasons": {},
        "infrastructure": planned - retained,
        "strict_all_pass": int(amended["all_pass"]),
        "strict_all_pass_rate": amended["strict_all_pass_rate"],
        "criterion_passes": int(amended["semantic_passes"]),
        "criterion_total": int(amended["semantic_criteria"]),
        "criterion_pass_rate": amended["criterion_pass_rate"],
        "criterion_evaluation": "semantic_judge",
        "semantic_judge_batches": None,
        "equal_task_macro": amended["macro_semantic_mean"],
        "craft": _craft_counts(records),
        "telemetry": _telemetry(records),
        "tasks": amended["tasks"],
    }


def build_release_summary(
    protocol_path: Path,
    native: dict[str, Any],
    adjudication_path: Path,
    *,
    native_analysis_path: Path | None = None,
    account_start_usd: float | None = None,
    account_end_usd: float | None = None,
) -> dict[str, Any]:
    protocol = load_object(protocol_path)
    expected_adjudication = protocol["preserved_adjudication"]
    if sha256(adjudication_path) != expected_adjudication["analysis_sha256"]:
        raise AnalysisError("preserved adjudication analysis digest drift")
    adjudication = load_object(adjudication_path)
    models = adjudication.get("models") or {}

    rows = [native_row(protocol, native)]
    display_names = {
        row["job"]: row["model"]
        for row in protocol["comparison_rows"]
        if row["execution_origin"] == "preserved_output_adjudication"
    }
    for row in protocol["comparison_rows"]:
        if row["execution_origin"] != "preserved_output_adjudication":
            continue
        match = next(
            (
                (key, value)
                for key, value in models.items()
                if isinstance(value, dict) and value.get("job") == row["job"]
            ),
            None,
        )
        if match is None:
            raise AnalysisError(f"missing preserved adjudication row for {row['job']}")
        key, model_run = match
        rows.append(replay_row(protocol, key, display_names[row["job"]], model_run))

    account_spend = None
    if account_start_usd is not None and account_end_usd is not None:
        if account_end_usd > account_start_usd:
            raise AnalysisError("OpenRouter account balance increased during official run")
        account_spend = account_start_usd - account_end_usd

    return {
        "schema_version": RELEASE_SUMMARY_SCHEMA,
        "release_id": protocol["protocol_id"],
        "protocol_sha256": sha256(protocol_path),
        "native_analysis_sha256": (
            sha256(native_analysis_path)
            if native_analysis_path is not None
            else canonical_sha256(native)
        ),
        "preserved_adjudication_sha256": sha256(adjudication_path),
        "scenario": protocol["scenario_pack"],
        "rows": rows,
        "account_observation": {
            "openrouter_balance_before_official_usd": account_start_usd,
            "openrouter_balance_after_official_usd": account_end_usd,
            "combined_openrouter_spend_usd": account_spend,
            "allocation": (
                "Combined account change only; agent and judge costs cannot be split "
                "reliably from the retained telemetry."
            ),
        },
        "preserved_replay_observation": {
            "semantic_judge_batches": (adjudication.get("denominator") or {}).get(
                "completed_semantic_judge_batches"
            ),
            "openrouter_judge_usd": (adjudication.get("costs") or {}).get(
                "openrouter_judge_usd"
            ),
            "modal_usd": (adjudication.get("costs") or {}).get("modal_usd"),
            "allocation": (
                "The replay judge total covers all three preserved-output rows and "
                "cannot be split reliably by model."
            ),
        },
        "limitations": protocol["limitations"],
    }


def canonical_sha256(value: Any) -> str:
    import hashlib

    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def build_trace_audit(native: dict[str, Any]) -> dict[str, Any]:
    records = native["trials"]
    selected = {
        str(record["trial"])
        for record in records
        if record.get("infrastructure_error") is not None
        or record.get("agent_invalid_output")
        or (record.get("visual_review") or {}).get("practical_usability")
        in {"mixed", "poor"}
    }
    for task_name in {str(record["task"]) for record in records}:
        eligible = [
            record
            for record in records
            if record["task"] == task_name
            and record.get("infrastructure_error") is None
            and not record.get("agent_invalid_output")
        ]
        if eligible:
            earliest = min(
                eligible,
                key=lambda record: (
                    str(record.get("started_at") or ""),
                    str(record["trial"]),
                ),
            )
            selected.add(str(earliest["trial"]))
            semantic = [
                record
                for record in eligible
                if isinstance(record.get("semantic_score"), (int, float))
            ]
            if semantic:
                selected.add(
                    str(min(semantic, key=lambda record: record["semantic_score"])["trial"])
                )
                selected.add(
                    str(max(semantic, key=lambda record: record["semantic_score"])["trial"])
                )

    audits = []
    for record in records:
        trajectory = record.get("trajectory") or {}
        audits.append(
            {
                "trial": record["trial"],
                "task": record["task"],
                "manual_review_selected": str(record["trial"]) in selected,
                "infrastructure_error": record.get("infrastructure_error"),
                "agent_invalid_output": bool(record.get("agent_invalid_output")),
                "invalid_output_reason": record.get("invalid_output_reason"),
                "complete_atif": trajectory.get("complete_atif"),
                "tool_calls": trajectory.get("tool_calls") or {},
                "output_write_events": trajectory.get("output_write_events"),
                "used_python_docx": trajectory.get("used_python_docx"),
                "post_draft_validation": trajectory.get("post_draft_validation"),
                "reopened_output": trajectory.get("reopened_output"),
                "attempted_visual_render": trajectory.get("attempted_visual_render"),
                "error_observations": trajectory.get("error_observations"),
                "raw_trial_path": (
                    "compute-bazaar-bench/jobs/raw/"
                    f"{native['job']}/{record['trial']}"
                ),
            }
        )
    return {
        "schema_version": "compute-bazaar-bench.transactions.release-trace-audit.v1",
        "release_id": native["protocol_id"],
        "job": native["job"],
        "machine_audited": len(audits),
        "manual_sample": sorted(selected),
        "selection_rule": (
            "Earliest valid trial per task, semantic min/max, every invalid output, "
            "every infrastructure failure, and every mixed or poor craft result."
        ),
        "trials": audits,
    }


def _percent(value: Any) -> str:
    return "-" if value is None else f"{100 * float(value):.1f}%"


def _seconds(value: Any) -> str:
    return "-" if value is None else f"{float(value):.1f}s"


def _tokens(left: Any, right: Any) -> str:
    if left is None or right is None:
        return "-"
    return f"{int(round(float(left))):,} / {int(round(float(right))):,}"


def _craft(value: dict[str, Any]) -> str:
    if not value.get("reviewed"):
        return "not reviewable"
    return f"{value['good']}/{value['mixed']}/{value['poor']} good/mixed/poor"


def _cost(value: Any) -> str:
    return "-" if value is None else f"${float(value):.3f}"


def _failed_at_output_gate(row: dict[str, Any]) -> bool:
    return row.get("criterion_evaluation") == "not_run_output_gate"


def _criterion_result(row: dict[str, Any]) -> str:
    if _failed_at_output_gate(row):
        return "not judged (output gate)"
    return "{passes}/{total} ({rate})".format(
        passes=row["criterion_passes"],
        total=row["criterion_total"],
        rate=_percent(row["criterion_pass_rate"]),
    )


def _equal_task_result(row: dict[str, Any]) -> str:
    value = _percent(row["equal_task_macro"])
    return f"{value} (output gate)" if _failed_at_output_gate(row) else value


def render_public_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Transactions release v1",
        "",
        (
            "Four models are shown on the same three linked synthetic compute-transaction "
            "tasks. Mistral Small was run fresh in Harbor. The DeepSeek, GPT-5.6 Luna, "
            "and GLM rows use their earlier saved documents, regraded with the same "
            "release grader; those agents were not rerun."
        ),
        "",
        (
            "Strict all-pass means one attempt passed every required check. Criterion "
            "pass is shown only when a usable document reached checklist review. A "
            "missing or invalid required file receives a benchmark zero at the output gate."
        ),
        "",
        (
            "The grader was corrected during private calibration. Every score shown "
            "here uses the frozen release grader."
        ),
        "",
        "## Results",
        "",
        (
            "| Model | How scored | Scored / planned | Strict all-pass | Criterion pass | "
            "Equal-task average | Document quality | Median agent time | Median input / output tokens | "
            "Agent cost | Judge cost | Modal cost |"
        ),
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["rows"]:
        craft = row["craft"]
        telemetry = row["telemetry"]
        lines.append(
            "| {model} | {origin} | {scored}/{planned} | {passed}/{scored} ({rate}) | "
            "{criterion_result} | {macro} | "
            "{craft} | {latency} | {tokens} | {agent_cost} | {judge_cost} | {modal_cost} |".format(
                model=row["model"],
                origin=row["execution_label"],
                scored=row["scored"],
                planned=row["planned"],
                passed=row["strict_all_pass"],
                rate=_percent(row["strict_all_pass_rate"]),
                criterion_result=_criterion_result(row),
                macro=_equal_task_result(row),
                craft=_craft(craft),
                latency=_seconds(telemetry["median_agent_seconds"]),
                tokens=_tokens(
                    telemetry["median_input_tokens"],
                    telemetry["median_output_tokens"],
                ),
                agent_cost=_cost(telemetry["agent_cost_usd"]),
                judge_cost=_cost(telemetry["judge_cost_usd"]),
                modal_cost=_cost(telemetry["modal_cost_usd"]),
            )
        )

    native = summary["rows"][0]
    lines.extend(
        [
            "",
            "## What this showed",
            "",
            (
                f"- Mistral Small produced {native['valid_docx']} usable DOCX files in "
                f"{native['planned']} attempts. {native['invalid_output']} attempts were "
                "scored as model-output failures, not hidden or discarded."
            ),
            (
                "- An invalid DOCX receives zero across the task checklist without a "
                "GPT-5.4 review of the mislabeled file. This tests whether the model "
                "and harness can deliver the requested work product; it does not prove "
                "that no useful analysis appeared in the underlying trace."
            ),
        ]
    )
    if native["infrastructure"]:
        lines.append(
            f"- {native['infrastructure']} Mistral attempt was excluded under the "
            "frozen one-hour timeout rule. A timeout does not identify its cause."
        )
    else:
        lines.append("- The fresh Mistral job had no infrastructure exclusions.")
    for reason, count in native.get("invalid_output_reasons", {}).items():
        noun = "attempt" if count == 1 else "attempts"
        lines.append(f"- {count} Mistral {noun}: {reason}")
    trajectory = native.get("trajectory_observations") or {}
    if trajectory:
        lines.append(
            "- Recorded tool calls show that {direct}/{trials} scored attempts tried "
            "to read an Office file directly, {errors}/{trials} encountered at least "
            "one tool error, and none reopened or existence-checked the final file. "
            "These are trace indicators, not proof of a single cause.".format(
                direct=trajectory.get("direct_binary_read", 0),
                errors=trajectory.get("trials_with_execution_errors", 0),
                trials=trajectory.get("trials", 0),
            )
        )
    lines.extend(
        [
            (
                "- The larger-model rows often passed most individual checks, while "
                "passing every check in one attempt remained rare."
            ),
            (
                "- Document quality is kept separate from task accuracy. A malformed or "
                "missing DOCX is an output failure and is not given a visual-quality rating."
            ),
            "",
            "## Per task",
            "",
            "| Model | Task | Scored | Strict all-pass | Mean criterion pass |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for row in summary["rows"]:
        for task_name, task in row["tasks"].items():
            retained = int(task["retained"])
            all_pass = int(task["all_pass"])
            semantic = task.get("semantic") or {}
            criterion_result = (
                "not judged (output gate)"
                if _failed_at_output_gate(row)
                else _percent(semantic.get("mean"))
            )
            lines.append(
                f"| {row['model']} | `{task_name}` | {retained} | {all_pass}/{retained} | "
                f"{criterion_result} |"
            )

    observation = summary["account_observation"]
    lines.extend(["", "## Cost", ""])
    if observation["combined_openrouter_spend_usd"] is None:
        lines.append(
            "Agent, judge, and Modal costs are unavailable in the retained per-trial telemetry."
        )
    else:
        lines.append(
            "The OpenRouter account balance fell by "
            f"`${observation['combined_openrouter_spend_usd']:.6f}` during the fresh official job. "
            "No Mistral document reached checklist review, so the fresh job made zero "
            "GPT-5.4 grading calls. Per-trial agent cost and Modal cost were "
            "not available."
        )
    replay = summary.get("preserved_replay_observation") or {}
    if replay.get("openrouter_judge_usd") is not None:
        lines.append(
            "The preserved-output replay used "
            f"`${float(replay['openrouter_judge_usd']):.6f}` across "
            f"{replay.get('semantic_judge_batches')} GPT-5.4 grading calls. That total "
            "covers DeepSeek, GPT-5.6 Luna, and GLM together and is not split by model."
        )

    lines.extend(
        [
            "",
            "## Limits",
            "",
            (
                "This is one synthetic transaction followed through three related tasks, "
                "with five unseeded attempts per task. It is a descriptive result for this "
                "fixed harness, not a general model ranking or a claim about broad "
                "compute-market competence."
            ),
            "",
            (
                "The table deliberately marks how each row was produced. Mistral is a fresh "
                "native Harbor run; the other rows are preserved documents regraded later "
                "with the same release grader."
            ),
            "",
            (
                "The Mistral route retained the requested Exacto model string, but "
                "OpenRouter did not expose the downstream backend identity. Sampling was "
                "unseeded, and GPT-5.4 made one judgment per checklist item."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--adjudication", required=True, type=Path)
    parser.add_argument("--native-output-dir", required=True, type=Path)
    parser.add_argument("--release-output-dir", required=True, type=Path)
    parser.add_argument("--public-summary", type=Path)
    parser.add_argument("--public-report", type=Path)
    parser.add_argument("--craft-review", type=Path)
    parser.add_argument("--account-start-usd", type=float)
    parser.add_argument("--account-end-usd", type=float)
    args = parser.parse_args()

    native = analyze_native_job(
        args.job_dir.resolve(),
        args.protocol.resolve(),
        args.craft_review.resolve() if args.craft_review else None,
    )
    args.native_output_dir.mkdir(parents=True, exist_ok=True)
    native_analysis_path = args.native_output_dir / "analysis.json"
    write_json(native_analysis_path, native)
    write_json(args.native_output_dir / "trace-audit.json", build_trace_audit(native))

    release = build_release_summary(
        args.protocol.resolve(),
        native,
        args.adjudication.resolve(),
        native_analysis_path=native_analysis_path,
        account_start_usd=args.account_start_usd,
        account_end_usd=args.account_end_usd,
    )
    args.release_output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.release_output_dir / "summary.json", release)
    rendered_report = render_public_report(release)
    (args.release_output_dir / "report.md").write_text(rendered_report, encoding="utf-8")
    if args.public_summary is not None:
        write_json(args.public_summary, release)
    if args.public_report is not None:
        args.public_report.parent.mkdir(parents=True, exist_ok=True)
        args.public_report.write_text(rendered_report, encoding="utf-8")
    print(f"native_analysis={args.native_output_dir / 'analysis.json'}")
    print(f"release_summary={args.release_output_dir / 'summary.json'}")
    print(f"release_report={args.release_output_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AnalysisError as exc:
        print(f"release analysis error: {exc}", file=sys.stderr)
        raise SystemExit(2)
