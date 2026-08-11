"""Validate and summarize the frozen Transactions multi-model comparison."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from statistics import mean
import sys
from typing import Any

from analysis import (
    ANALYSIS_SCHEMA_VERSION,
    AnalysisError,
    aggregate,
    classify_trial,
    expected_tasks,
    load_object,
    repeated_misses,
    seconds,
    sha256,
    stats,
    validate_lock,
)


COMPARISON_SCHEMA_VERSION = "compute-bazaar-bench.transactions.comparison-analysis.v1"
CANARY_SCHEMA_VERSION = "compute-bazaar-bench.transactions.canary-analysis.v1"
PRECOMMIT_GIT_COMMIT = "7890fd06b1c6d2284af693124b61b61e85399be6"
REPAIR_GIT_COMMIT = "a8495f0fab6546d9be49e59333081927a6a6fac1"
REPAIR_FIXTURES = {
    "compute-bazaar-bench/evals/transactions/draft-capacity-data-room-population-plan/environment/documents/evidence-register.xlsx": "3358dffa8a4974266397e961a4c2ef513e1dc88045a81c6f4e8e994f324e85ef",
    "compute-bazaar-bench/evals/transactions/compare-capacity-agreement-against-term-sheet/environment/documents/buyer-risk-checklist.xlsx": "0d3678bd76eba3c3c38d25fe9b7b43df707e18a5e36c6111c4df244f28cf5072",
}


def validate_commitment(path: Path) -> dict[str, Any]:
    protocol = load_object(path)
    if protocol.get("protocol_id") != "transactions-comparison-v1":
        raise AnalysisError("unexpected comparison protocol ID")
    tasks = expected_tasks(protocol)
    models = protocol.get("models")
    if not isinstance(models, list) or not models:
        raise AnalysisError("comparison protocol needs models")
    keys = [model.get("key") for model in models if isinstance(model, dict)]
    if len(keys) != len(models) or len(keys) != len(set(keys)):
        raise AnalysisError("comparison model keys are missing or duplicated")
    agent_models = [model.get("agent_model") for model in models]
    if len(agent_models) != len(set(agent_models)):
        raise AnalysisError("comparison agent models are duplicated")
    for model in models:
        agent_model = model.get("agent_model")
        if not isinstance(agent_model, str) or not agent_model.startswith(
            "openrouter/"
        ):
            raise AnalysisError(f"invalid OpenRouter model for {model.get('key')}")
        if not agent_model.endswith(":exacto") or "latest" in agent_model.lower():
            raise AnalysisError(f"model routing is not frozen for {model.get('key')}")
        canonical = model.get("canonical_slug")
        if not isinstance(canonical, str) or canonical not in agent_model:
            raise AnalysisError(f"canonical model mismatch for {model.get('key')}")

    catalog = protocol.get("catalog") or {}
    selection_path = path.parent / str(catalog.get("selection_path", ""))
    if sha256(selection_path) != catalog.get("selection_sha256"):
        raise AnalysisError("OpenRouter catalog selection digest drift")
    selected = load_object(selection_path).get("models")
    if not isinstance(selected, list):
        raise AnalysisError("OpenRouter catalog selection has no models")
    selected_slugs = {
        item.get("canonical_slug") for item in selected if isinstance(item, dict)
    }
    if {model["canonical_slug"] for model in models} != selected_slugs:
        raise AnalysisError("comparison models do not match the catalog selection")

    visual = (protocol.get("reporting") or {}).get("visual_review") or {}
    rubric_path = path.parent / str(visual.get("rubric_path", ""))
    if sha256(rubric_path) != visual.get("rubric_sha256"):
        raise AnalysisError("document-craft rubric digest drift")

    official = protocol.get("official_run") or {}
    if official.get("planned_trials_total") != len(models) * len(tasks) * 5:
        raise AnalysisError("official comparison denominator is inconsistent")
    canaries = protocol.get("canaries") or {}
    if canaries.get("planned_trials_total") != len(models) * len(tasks):
        raise AnalysisError("canary denominator is inconsistent")
    return protocol


def model_by_key(protocol: dict[str, Any], key: str) -> dict[str, Any]:
    for model in protocol["models"]:
        if model["key"] == key:
            return model
    raise AnalysisError(f"unknown comparison model: {key}")


def model_job_protocol(
    protocol: dict[str, Any], model: dict[str, Any], attempts_per_task: int
) -> dict[str, Any]:
    return {
        "tasks": protocol["tasks"],
        "agent": {
            "name": protocol["agent"]["name"],
            "version": protocol["agent"]["version"],
            "model": model["agent_model"],
            "provider_host": protocol["routing"]["provider_host"],
        },
        "environment": {
            "name": protocol["harbor"]["environment"],
            "modal_vm_runtime": protocol["harbor"]["modal_vm_runtime"],
        },
        "attempts_per_task": attempts_per_task,
        "planned_trials": len(protocol["tasks"]) * attempts_per_task,
    }


def task_name_from_result(result: dict[str, Any]) -> str:
    return str(result.get("task_name", "")).removeprefix("gustofied/")


def enrich_spend_and_trace(
    record: dict[str, Any], trial_dir: Path, task: dict[str, Any], agent: dict[str, Any]
) -> None:
    try:
        result = load_object(trial_dir / "result.json")
    except AnalysisError:
        return
    usage = result.get("agent_result") or {}
    record.setdefault(
        "tokens",
        {
            "input": usage.get("n_input_tokens"),
            "cache": usage.get("n_cache_tokens"),
            "output": usage.get("n_output_tokens"),
        },
    )
    record.setdefault("reported_cost_usd", usage.get("cost_usd"))
    environment_setup = result.get("environment_setup") or {}
    agent_setup = result.get("agent_setup") or {}
    record.setdefault(
        "environment_setup_seconds",
        seconds(
            environment_setup.get("started_at"),
            environment_setup.get("finished_at"),
        ),
    )
    record.setdefault(
        "agent_setup_seconds",
        seconds(agent_setup.get("started_at"), agent_setup.get("finished_at")),
    )
    if (
        "trajectory" not in record
        and (trial_dir / "agent" / "trajectory.json").exists()
    ):
        from analysis import inspect_trajectory

        try:
            record["trajectory"] = inspect_trajectory(
                trial_dir / "agent" / "trajectory.json",
                task["deliverable"],
                agent,
                task.get("matter_documents", ()),
            )
        except AnalysisError:
            pass
    trajectory = record.get("trajectory")
    if isinstance(trajectory, dict):
        trajectory["visual_render_marker_observed"] = bool(
            trajectory.get("attempted_visual_render")
        )
        trajectory["attempted_visual_render"] = bool(
            trajectory.get("output_visual_render_invocation")
        )


def missing_result(task: str, index: int) -> dict[str, Any]:
    return {
        "trial": f"unstarted::{task}::{index}",
        "task": task,
        "infrastructure_error": "planned trial has no result record",
        "agent_invalid_output": False,
        "artifact_status_ok": False,
    }


def analyze_job(
    job_dir: Path,
    protocol: dict[str, Any],
    model: dict[str, Any],
    attempts_per_task: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    job_protocol = model_job_protocol(protocol, model, attempts_per_task)
    tasks = expected_tasks(job_protocol)
    validate_terminal_job(job_dir, len(tasks) * attempts_per_task)
    validate_lock(load_object(job_dir / "lock.json"), job_protocol, tasks)

    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for result_path in sorted(job_dir.glob("*/result.json")):
        trial_dir = result_path.parent
        result = load_object(result_path)
        name = task_name_from_result(result)
        if name not in tasks:
            raise AnalysisError(f"unexpected task result in {trial_dir}: {name}")
        counts[name] += 1
        if counts[name] > attempts_per_task:
            raise AnalysisError(f"too many results for {name} in {job_dir}")
        record = classify_trial(
            trial_dir,
            tasks[name],
            job_protocol["agent"],
            missing_artifact_as_invalid=True,
        )
        record["model_key"] = model["key"]
        record["job"] = job_dir.name
        enrich_spend_and_trace(record, trial_dir, tasks[name], job_protocol["agent"])
        records.append(record)

    for task in tasks:
        for index in range(counts[task] + 1, attempts_per_task + 1):
            record = missing_result(task, index)
            record["model_key"] = model["key"]
            record["job"] = job_dir.name
            records.append(record)

    records.sort(key=lambda row: (row["task"], row["trial"]))
    return records, aggregate(records, tasks)


def validate_terminal_job(job_dir: Path, planned_trials: int) -> dict[str, Any]:
    result = load_object(job_dir / "result.json")
    if result.get("finished_at") is None:
        raise AnalysisError(f"Harbor job is not terminal: {job_dir}")
    if result.get("n_total_trials") != planned_trials:
        raise AnalysisError(f"Harbor job denominator mismatch: {job_dir}")
    job_stats = result.get("stats")
    if not isinstance(job_stats, dict):
        raise AnalysisError(f"Harbor job lacks terminal stats: {job_dir}")
    keys = (
        "n_completed_trials",
        "n_errored_trials",
        "n_running_trials",
        "n_pending_trials",
        "n_cancelled_trials",
        "n_retries",
    )
    if any(not isinstance(job_stats.get(key), int) for key in keys):
        raise AnalysisError(f"Harbor job stats are malformed: {job_dir}")
    if job_stats["n_running_trials"] or job_stats["n_pending_trials"]:
        raise AnalysisError(f"Harbor job still has active trials: {job_dir}")
    if job_stats["n_completed_trials"] != planned_trials:
        raise AnalysisError(f"Harbor terminal count mismatch: {job_dir}")
    if job_stats["n_errored_trials"] > job_stats["n_completed_trials"]:
        raise AnalysisError(f"Harbor error count exceeds terminal count: {job_dir}")
    if job_stats["n_cancelled_trials"] > job_stats["n_completed_trials"]:
        raise AnalysisError(
            f"Harbor cancellation count exceeds terminal count: {job_dir}"
        )
    if job_stats["n_retries"] != 0:
        raise AnalysisError(f"Harbor job violates no-retry protocol: {job_dir}")
    return result


def canary_failures(records: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for record in records:
        prefix = f"{record['model_key']}/{record['task']}/{record['trial']}"
        if record["infrastructure_error"] is not None:
            failures.append(f"{prefix}: {record['infrastructure_error']}")
            continue
        if (
            not record.get("artifact_status_ok")
            or record.get("output_integrity") != 1.0
        ):
            failures.append(f"{prefix}: required DOCX did not pass output integrity")
        trajectory = record.get("trajectory") or {}
        if not trajectory.get("complete_atif"):
            failures.append(f"{prefix}: incomplete ATIF")
        if record.get("agent_seconds") is None:
            failures.append(f"{prefix}: missing agent latency")
        tokens = record.get("tokens") or {}
        if not isinstance(tokens.get("input"), int) or not isinstance(
            tokens.get("output"), int
        ):
            failures.append(f"{prefix}: missing token telemetry")
        cost = record.get("reported_cost_usd")
        if cost is not None and not isinstance(cost, (int, float)):
            failures.append(f"{prefix}: malformed cost telemetry")
    return failures


def cost_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    costs = [
        row.get("reported_cost_usd")
        for row in records
        if isinstance(row.get("reported_cost_usd"), (int, float))
    ]
    token_totals: dict[str, int] = {}
    for key in ("input", "cache", "output"):
        values = [
            row.get("tokens", {}).get(key)
            for row in records
            if isinstance(row.get("tokens", {}).get(key), int)
        ]
        token_totals[key] = sum(values)
    return {
        "agent_reported_usd": (
            sum(costs) if costs and len(costs) == len(records) else None
        ),
        "agent_reported_usd_partial": (
            sum(costs) if costs and len(costs) != len(records) else None
        ),
        "agent_cost_coverage": len(costs),
        "planned_trials": len(records),
        "tokens": token_totals,
    }


def behavior_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in records if isinstance(row.get("trajectory"), dict)]
    retained = [row for row in rows if row["infrastructure_error"] is None]
    coverage = [
        row["trajectory"].get("matter_document_coverage")
        for row in retained
        if row["trajectory"].get("matter_document_coverage") is not None
    ]
    return {
        "trials_with_trajectory": len(rows),
        "retained_trajectories": len(retained),
        "infrastructure_trajectories": len(rows) - len(retained),
        "mean_matter_document_coverage": mean(coverage) if coverage else None,
        "post_draft_validation": sum(
            bool(row["trajectory"].get("post_draft_validation")) for row in retained
        ),
        "revision_after_validation": sum(
            bool(row["trajectory"].get("revision_after_validation"))
            for row in retained
        ),
        "returned_to_sources_after_draft": sum(
            bool(row["trajectory"].get("returned_to_sources_after_draft"))
            for row in retained
        ),
        "attempted_visual_render": sum(
            bool(row["trajectory"].get("attempted_visual_render"))
            for row in retained
        ),
        "trials_with_execution_errors": sum(
            int(row["trajectory"].get("error_observations", 0)) > 0
            for row in retained
        ),
    }


def latency_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    retained = [row for row in records if row["infrastructure_error"] is None]
    return {
        key: stats(
            row[field]
            for row in retained
            if isinstance(row.get(field), (int, float))
        )
        for key, field in (
            ("environment_setup", "environment_setup_seconds"),
            ("agent_setup", "agent_setup_seconds"),
            ("agent_execution", "agent_seconds"),
            ("verifier", "verifier_seconds"),
            ("whole_trial", "duration_seconds"),
        )
    }


def attach_visual_review(
    model_runs: dict[str, dict[str, Any]],
    review_path: Path,
    rubric: dict[str, Any],
) -> dict[str, Any]:
    review = load_object(review_path)
    items = review.get("trials")
    if not isinstance(items, dict):
        raise AnalysisError("comparison visual review must contain a trials object")
    known = {
        f"{model_key}/{record['trial']}"
        for model_key, run in model_runs.items()
        for record in run["records"]
    }
    required = {
        f"{model_key}/{record['trial']}"
        for model_key, run in model_runs.items()
        for record in run["records"]
        if record.get("artifact_status_ok")
    }
    if not required.issubset(items) or not set(items).issubset(known):
        raise AnalysisError(
            "visual review trial mismatch; "
            f"missing={sorted(required - set(items))}, "
            f"extra={sorted(set(items) - known)}"
        )
    allowed = {"good", "mixed", "poor"}
    criteria = rubric.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise AnalysisError("document-craft rubric has no criteria")
    criterion_ids = {item.get("id") for item in criteria if isinstance(item, dict)}
    critical_ids = {
        item["id"]
        for item in criteria
        if isinstance(item, dict) and item.get("critical")
    }
    for model_key, run in model_runs.items():
        for record in run["records"]:
            key = f"{model_key}/{record['trial']}"
            if key not in items:
                continue
            item = items[key]
            if (
                not isinstance(item, dict)
                or item.get("practical_usability") not in allowed
            ):
                raise AnalysisError(f"invalid visual review for {key}")
            if not isinstance(item.get("page_count"), int) or item["page_count"] < 1:
                raise AnalysisError(f"invalid page count for {key}")
            values = item.get("criterion_values")
            if not isinstance(values, dict) or set(values) != criterion_ids:
                raise AnalysisError(f"criterion mismatch in visual review for {key}")
            if any(not isinstance(value, bool) for value in values.values()):
                raise AnalysisError(f"non-boolean craft criterion for {key}")
            failed = {
                criterion_id for criterion_id, value in values.items() if not value
            }
            expected_rating = (
                "poor" if failed & critical_ids else "mixed" if failed else "good"
            )
            if item["practical_usability"] != expected_rating:
                raise AnalysisError(f"craft rating does not follow rubric for {key}")
            record["visual_review"] = item
    return review


def visual_summary(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows = [row for row in records if "visual_review" in row]
    if not rows:
        return None
    ratings = Counter(row["visual_review"]["practical_usability"] for row in rows)
    pages = [row["visual_review"]["page_count"] for row in rows]
    return {
        "reviewed": len(rows),
        "good": ratings["good"],
        "mixed": ratings["mixed"],
        "poor": ratings["poor"],
        "page_count": stats(pages),
        "clipping": sum(bool(row["visual_review"].get("clipping")) for row in rows),
        "overlap": sum(bool(row["visual_review"].get("overlap")) for row in rows),
    }


def validate_run_record(
    record: dict[str, Any],
    protocol_path: Path,
    protocol: dict[str, Any],
    *,
    jobs_root: Path | None = None,
) -> None:
    if record.get("protocol_id") != protocol["protocol_id"]:
        raise AnalysisError("comparison run record protocol mismatch")
    if record.get("protocol_sha256") != sha256(protocol_path):
        raise AnalysisError("comparison run record protocol digest mismatch")
    if record.get("precommit_git_commit") != PRECOMMIT_GIT_COMMIT:
        raise AnalysisError("comparison run record precommit mismatch")
    repair = record.get("reproducibility_repair") or {}
    if repair.get("git_commit") != REPAIR_GIT_COMMIT:
        raise AnalysisError("comparison reproducibility repair commit mismatch")
    if repair.get("fixtures") != REPAIR_FIXTURES:
        raise AnalysisError("comparison reproducibility fixture manifest mismatch")
    repo_root = protocol_path.resolve().parents[4]
    for relative, expected_hash in REPAIR_FIXTURES.items():
        if sha256(repo_root / relative) != expected_hash:
            raise AnalysisError(f"reproducibility fixture drift: {relative}")
    canaries = record.get("canary_jobs") or {}
    canary_history = record.get("canary_history") or {}
    official = record.get("official_jobs") or {}
    official_history = record.get("official_history") or {}
    for model in protocol["models"]:
        key = model["key"]
        history = canary_history.get(key)
        if not isinstance(history, list) or not history:
            raise AnalysisError(f"canary history missing for {key}")
        expected_first = model["canary_job"]
        if history[0].get("job") != expected_first:
            raise AnalysisError(f"initial canary job mismatch for {key}")
        canary_pattern = re.compile(
            rf"^{re.escape(expected_first[:-3])}[0-9]{{3}}$"
        )
        jobs = [item.get("job") for item in history if isinstance(item, dict)]
        if len(jobs) != len(history) or len(jobs) != len(set(jobs)):
            raise AnalysisError(f"malformed or duplicate canary history for {key}")
        if any(not isinstance(job, str) or not canary_pattern.fullmatch(job) for job in jobs):
            raise AnalysisError(f"invalid versioned canary job for {key}")
        statuses = [item.get("status") for item in history]
        if any(status not in {"accepted", "failed"} for status in statuses):
            raise AnalysisError(f"invalid canary status for {key}")
        accepted = [item["job"] for item in history if item["status"] == "accepted"]
        if len(accepted) > 1:
            raise AnalysisError(f"multiple accepted canaries for {key}")
        if any(
            item["status"] == "failed" and not item.get("failure")
            for item in history
        ):
            raise AnalysisError(f"failed canary lacks failure evidence for {key}")
        if jobs_root is not None:
            for item in history:
                report_path = item.get("report_path")
                report_hash = item.get("report_sha256")
                if not isinstance(report_path, str) or not isinstance(
                    report_hash, str
                ):
                    raise AnalysisError(f"canary report provenance missing for {key}")
                full_report_path = repo_root / report_path
                if sha256(full_report_path) != report_hash:
                    raise AnalysisError(
                        f"canary report digest mismatch for {item['job']}"
                    )
                report = load_object(full_report_path)
                if report.get("job") != item["job"]:
                    raise AnalysisError(
                        f"canary report job mismatch for {item['job']}"
                    )
                if bool(report.get("passed")) != (item["status"] == "accepted"):
                    raise AnalysisError(
                        f"canary report status mismatch for {item['job']}"
                    )
        if accepted:
            if accepted[0] != canaries.get(key):
                raise AnalysisError(f"accepted canary mismatch for {key}")
            if history[-1]["status"] != "accepted":
                raise AnalysisError(f"accepted canary is not final for {key}")
            history = official_history.get(key)
            if not isinstance(history, list) or not history:
                raise AnalysisError(f"official history missing for {key}")
            expected_first = model["official_job"]
            if history[0].get("job") != expected_first:
                raise AnalysisError(f"initial official job mismatch for {key}")
            official_pattern = re.compile(
                rf"^{re.escape(expected_first[:-3])}[0-9]{{3}}$"
            )
            official_history_jobs = [
                item.get("job") for item in history if isinstance(item, dict)
            ]
            if len(official_history_jobs) != len(history) or len(
                official_history_jobs
            ) != len(set(official_history_jobs)):
                raise AnalysisError(f"malformed official history for {key}")
            if any(
                not isinstance(job, str) or not official_pattern.fullmatch(job)
                for job in official_history_jobs
            ):
                raise AnalysisError(f"invalid versioned official job for {key}")
            statuses = [item.get("status") for item in history]
            if any(status not in {"accepted", "invalidated"} for status in statuses):
                raise AnalysisError(f"invalid official status for {key}")
            selected = [
                item["job"] for item in history if item["status"] == "accepted"
            ]
            if len(selected) > 1:
                raise AnalysisError(f"multiple accepted official jobs for {key}")
            if selected:
                if selected[0] != official.get(key):
                    raise AnalysisError(f"accepted official job mismatch for {key}")
                if history[-1]["status"] != "accepted":
                    raise AnalysisError(f"accepted official job is not final for {key}")
            elif official.get(key) is not None:
                raise AnalysisError(f"invalidated official job selected for {key}")
            if any(
                item["status"] == "invalidated" and not item.get("failure")
                for item in history
            ):
                raise AnalysisError(f"invalidated official job lacks evidence for {key}")
        else:
            if canaries.get(key) is not None:
                raise AnalysisError(f"blocked model has selected canary for {key}")
            if official.get(key) is not None:
                raise AnalysisError(f"blocked model has official job for {key}")
            if official_history.get(key):
                raise AnalysisError(f"blocked model has official history for {key}")
    launched_order = [
        key
        for key in protocol["official_run"]["job_order"]
        if official_history.get(key)
    ]
    if record.get("official_launch_order") != launched_order:
        raise AnalysisError("official launch order mismatch")
    lock_hashes = record.get("official_lock_sha256") or {}
    if set(lock_hashes) != set(launched_order):
        raise AnalysisError("official lock manifest mismatch")
    if jobs_root is not None:
        for key in launched_order:
            history = official_history[key]
            job_name = official.get(key) or history[-1]["job"]
            lock_path = jobs_root / job_name / "lock.json"
            if sha256(lock_path) != lock_hashes[key]:
                raise AnalysisError(f"official lock digest mismatch for {key}")

    accounting = record.get("official_accounting") or {}
    attempts_per_model = (
        len(protocol["tasks"])
        * protocol["official_run"]["attempts_per_task"]
    )
    expected_accounting = {
        "frozen_planned_trials": protocol["official_run"]["planned_trials_total"],
        "withheld_after_canary": (
            len(protocol["models"]) - len(launched_order)
        )
        * attempts_per_model,
        "launched_trials": len(launched_order) * attempts_per_model,
        "invalidated_job_trials": (
            len(launched_order) - len(official)
        )
        * attempts_per_model,
        "selected_official_trials": len(official) * attempts_per_model,
    }
    if accounting != expected_accounting:
        raise AnalysisError("official accounting mismatch")


def comparison_summary(
    model_runs: dict[str, dict[str, Any]], run_record: dict[str, Any]
) -> dict[str, Any]:
    accounting = run_record["official_accounting"]
    selected = sum(len(run["records"]) for run in model_runs.values())
    infra = sum(
        row["infrastructure_error"] is not None
        for run in model_runs.values()
        for row in run["records"]
    )
    invalid = sum(
        row["infrastructure_error"] is None and row["agent_invalid_output"]
        for run in model_runs.values()
        for row in run["records"]
    )
    return {
        "planned": accounting["frozen_planned_trials"],
        "launched": accounting["launched_trials"],
        "withheld_after_canary": accounting["withheld_after_canary"],
        "invalidated_job_trials": accounting["invalidated_job_trials"],
        "selected_official_trials": accounting["selected_official_trials"],
        "selected_terminal_trials": selected,
        "retained": selected - infra,
        "infrastructure_errors": infra,
        "agent_invalid_outputs": invalid,
        "canary_blocked_models": sum(
            run.get("status") == "canary_blocked" for run in model_runs.values()
        ),
        "invalidated_official_models": sum(
            run.get("status") == "official_invalidated"
            for run in model_runs.values()
        ),
    }


def fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def fmt_raw(values: list[float]) -> str:
    return "[" + ", ".join(f"{value:.4f}" for value in values) + "]"


def unscored_status_label(status: str) -> str:
    if status == "canary_blocked":
        return "Canary blocked"
    if status == "official_invalidated":
        return "Official job invalidated; unscored"
    raise AnalysisError(f"unknown unscored model status: {status}")


def render_report(
    protocol: dict[str, Any],
    run_record: dict[str, Any],
    model_runs: dict[str, dict[str, Any]],
    overall: dict[str, Any],
) -> str:
    lines = [
        "# Transactions OpenRouter comparison v1",
        "",
        (
            "Five unseeded attempts were planned for each of three linked checkpoints "
            "from synthetic opportunity CB-2026-041. Canary trials are excluded. "
            "Only complete accepted official jobs are scored."
        ),
        "",
        "## Strict all-pass",
        "",
        "| Model | Retained | Valid DOCX | All pass | Macro semantic | Criterion pass | Agent cost |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in protocol["models"]:
        run = model_runs[model["key"]]
        if run["status"] != "official":
            lines.append(
                f"| {model['display_name']} | {unscored_status_label(run['status'])} "
                "| - | - | - | - | - |"
            )
            continue
        summary = run["summary"]
        records = run["records"]
        retained = [row for row in records if row["infrastructure_error"] is None]
        valid = sum(not row["agent_invalid_output"] for row in retained)
        all_pass = sum(row.get("all_pass") == 1.0 for row in retained)
        costs = run["costs"]
        cost = costs["agent_reported_usd"]
        cost_text = "-" if cost is None else f"${cost:.4f}"
        lines.append(
            f"| {model['display_name']} | {len(retained)}/15 | {valid}/{len(retained)} | "
            f"{all_pass}/{len(retained)} | {fmt(summary['macro_semantic_mean'])} | "
            f"{summary['semantic_passes']}/{summary['semantic_criteria']} "
            f"({fmt(summary['micro_semantic_rate'])}) | {cost_text} |"
        )

    lines.extend(
        [
            "",
            "## Tasks",
            "",
            "| Model | Intake | Diligence | Contracting |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    task_names = [task["name"] for task in protocol["tasks"]]
    for model in protocol["models"]:
        run = model_runs[model["key"]]
        if run["status"] != "official":
            lines.append(f"| {model['display_name']} | - | - | - |")
            continue
        summary = run["summary"]
        values = []
        for name in task_names:
            task = summary["tasks"][name]
            values.append(
                f"{fmt(task['semantic']['mean'])} {fmt_raw(task['attempt_values'])}"
            )
        lines.append(f"| {model['display_name']} | {' | '.join(values)} |")

    lines.extend(["", "## Denominator", ""])
    lines.append(
        f"- Originally planned: `{overall['planned']}`; withheld after the Mistral "
        f"canary: `{overall['withheld_after_canary']}`; launched: "
        f"`{overall['launched']}`; excluded with the complete Claude job: "
        f"`{overall['invalidated_job_trials']}`; selected official slots: "
        f"`{overall['selected_official_trials']}`."
    )
    lines.append(
        f"- Selected trials: `{overall['selected_terminal_trials']}` terminal; "
        f"`{overall['retained']}` retained after `{overall['infrastructure_errors']}` "
        f"trial-level infrastructure exclusions; malformed agent outputs: "
        f"`{overall['agent_invalid_outputs']}`."
    )
    blocked = [
        model["display_name"]
        for model in protocol["models"]
        if model_runs[model["key"]]["status"] == "canary_blocked"
    ]
    if blocked:
        lines.append(
            "- Canary blocked: " + ", ".join(f"`{name}`" for name in blocked) + "."
        )
    invalidated = [
        model["display_name"]
        for model in protocol["models"]
        if model_runs[model["key"]]["status"] == "official_invalidated"
    ]
    if invalidated:
        lines.append(
            "- Official job invalidated and unscored after the evaluation budget was "
            "exhausted: "
            + ", ".join(f"`{name}`" for name in invalidated)
            + ". No completed trials from that job enter the comparison."
        )
    lines.append(f"- Precommit: `{run_record['precommit_git_commit']}`.")
    canary = run_record["canary_accounting"]
    lines.append(
        f"- Canaries: `{canary['planned_trials']}` planned; "
        f"`{canary['retained_trials']}` trial records preserved across "
        f"`{canary['retained_jobs']}` versioned jobs after infrastructure reruns; "
        "all excluded."
    )

    lines.extend(["", "## Usage and latency", ""])
    lines.append(
        "| Model | Input | Cache | Output | Agent cost | Cost coverage | "
        "Env setup | Agent setup | Agent run | Verifier | Whole trial |"
    )
    lines.append(
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    for model in protocol["models"]:
        run = model_runs[model["key"]]
        if run["status"] != "official":
            lines.append(
                f"| {model['display_name']} | - | - | - | - | - | - | - | - | - | - |"
            )
            continue
        costs = run["costs"]
        latency = run["latency"]
        cost = costs["agent_reported_usd"]
        cost_text = "-" if cost is None else f"${cost:.4f}"
        tokens = costs["tokens"]
        lines.append(
            f"| {model['display_name']} | {tokens['input']:,} | {tokens['cache']:,} | "
            f"{tokens['output']:,} | {cost_text} | "
            f"{costs['agent_cost_coverage']}/{costs['planned_trials']} | "
            f"{fmt(latency['environment_setup']['mean'])}s | "
            f"{fmt(latency['agent_setup']['mean'])}s | "
            f"{fmt(latency['agent_execution']['mean'])}s | "
            f"{fmt(latency['verifier']['mean'])}s | "
            f"{fmt(latency['whole_trial']['mean'])}s |"
        )
    lines.append("")
    lines.append(
        "Agent cost is null without complete harness-reported coverage. Judge and Modal "
        "dollar cost are unavailable and remain null. Latencies above are means over "
        "retained trials; token totals cover all recorded executions, including failures."
    )

    lines.extend(["", "## Document craft", ""])
    lines.append("| Model | Reviewed | Good | Mixed | Poor | Clipping | Overlap |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for model in protocol["models"]:
        if model_runs[model["key"]]["status"] != "official":
            lines.append(f"| {model['display_name']} | 0 | - | - | - | - | - |")
            continue
        visual = model_runs[model["key"]]["visual"]
        if visual is None:
            lines.append(f"| {model['display_name']} | 0 | - | - | - | - | - |")
        else:
            lines.append(
                f"| {model['display_name']} | {visual['reviewed']} | {visual['good']} | "
                f"{visual['mixed']} | {visual['poor']} | {visual['clipping']} | "
                f"{visual['overlap']} |"
            )
    lines.append("")
    lines.append(
        "Craft covers every successfully collected official DOCX, including a document "
        "from a trial later excluded for infrastructure. It is not a semantic denominator."
    )

    lines.extend(["", "## Observed command indicators", ""])
    lines.append(
        "Command patterns are harness-observed indicators, not proof of intent, "
        "reasoning, or unobserved behavior."
    )
    lines.append("")
    lines.append(
        "| Model | Retained traces | Infra traces | Matter coverage | Validated draft | Revised after check | Rendered output | Returned to sources |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for model in protocol["models"]:
        run = model_runs[model["key"]]
        if run["status"] != "official":
            lines.append(f"| {model['display_name']} | 0 | 0 | - | - | - | - | - |")
            continue
        behavior = run["behavior"]
        lines.append(
            f"| {model['display_name']} | {behavior['retained_trajectories']} | "
            f"{behavior['infrastructure_trajectories']} | "
            f"{fmt(behavior['mean_matter_document_coverage'])} | "
            f"{behavior['post_draft_validation']} | {behavior['revision_after_validation']} | "
            f"{behavior['attempted_visual_render']} | "
            f"{behavior['returned_to_sources_after_draft']} |"
        )

    lines.extend(
        [
            "",
            "## Historical baseline",
            "",
            (
                "The direct-provider Mistral Medium 3.5 v1 run remains an adjacent "
                "historical reference. It is not included in this comparison's aggregate "
                "or denominator."
            ),
            "",
            "## Limits",
            "",
            (
                "This is a descriptive comparison under one OpenCode harness on three "
                "linked checkpoints from one synthetic matter. Sampling is unseeded, "
                "reasoning compute is not equalized, and Exacto does not pin the backend "
                "provider. GPT-5.4 is the frozen judge, including for GPT-5.6 Luna. The "
                "result does not establish statistical significance, general model "
                "superiority, independent-matter accuracy, or broad compute-market competence."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_canary(args: argparse.Namespace) -> int:
    protocol_path = args.protocol.resolve()
    protocol = validate_commitment(protocol_path)
    model = model_by_key(protocol, args.model_key)
    records, summary = analyze_job(args.job_dir.resolve(), protocol, model, 1)
    failures = canary_failures(records)
    output = {
        "schema_version": CANARY_SCHEMA_VERSION,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(protocol_path),
        "model": model,
        "job": args.job_dir.resolve().name,
        "passed": not failures,
        "failures": failures,
        "summary": summary,
        "costs": cost_summary(records),
        "behavior": behavior_summary(records),
        "trials": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"canary_passed={not failures} failures={len(failures)}")
    return 0 if not failures else 3


def run_trace_sample(args: argparse.Namespace) -> int:
    protocol_path = args.protocol.resolve()
    protocol = validate_commitment(protocol_path)
    run_record = load_object(args.run_record)
    jobs_root = args.jobs_root.resolve()
    validate_run_record(
        run_record, protocol_path, protocol, jobs_root=jobs_root
    )
    selected: list[dict[str, Any]] = []
    for model in protocol["models"]:
        job_name = run_record["official_jobs"].get(model["key"])
        if job_name is None:
            continue
        job_dir = jobs_root / job_name
        validate_terminal_job(
            job_dir,
            len(protocol["tasks"])
            * protocol["official_run"]["attempts_per_task"],
        )
        results: dict[str, list[tuple[str, str]]] = {
            task["name"]: [] for task in protocol["tasks"]
        }
        for result_path in job_dir.glob("*/result.json"):
            result = load_object(result_path)
            task_name = task_name_from_result(result)
            if task_name in results:
                results[task_name].append(
                    (str(result.get("started_at") or ""), result_path.parent.name)
                )
        for task in protocol["tasks"]:
            candidates = sorted(results[task["name"]])
            if not candidates:
                raise AnalysisError(
                    f"no official trace candidate for {model['key']}/{task['name']}"
                )
            started_at, trial = candidates[0]
            selected.append(
                {
                    "model_key": model["key"],
                    "task": task["name"],
                    "job": job_name,
                    "trial": trial,
                    "started_at": started_at,
                }
            )
    output = {
        "schema_version": "compute-bazaar-bench.transactions.trace-sample.v1",
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(protocol_path),
        "run_record_sha256": sha256(args.run_record),
        "selection_rule": protocol["reporting"]["manual_trace_sample"],
        "outcome_fields_read": [],
        "trials": selected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"preregistered_trace_trials={len(selected)}")
    return 0


def run_official(args: argparse.Namespace) -> int:
    protocol_path = args.protocol.resolve()
    protocol = validate_commitment(protocol_path)
    run_record = load_object(args.run_record)
    jobs_root = args.jobs_root.resolve()
    validate_run_record(
        run_record, protocol_path, protocol, jobs_root=jobs_root
    )
    model_runs: dict[str, dict[str, Any]] = {}
    for model in protocol["models"]:
        key = model["key"]
        job_name = run_record["official_jobs"].get(key)
        if job_name is None:
            canary_accepted = any(
                item["status"] == "accepted"
                for item in run_record["canary_history"][key]
            )
            history = run_record.get("official_history", {}).get(key) or []
            status = (
                "official_invalidated" if canary_accepted else "canary_blocked"
            )
            model_runs[key] = {
                "status": status,
                "job": history[-1]["job"] if history else None,
                "exclusion_reason": history[-1].get("failure") if history else None,
                "records": [],
                "summary": None,
                "costs": cost_summary([]),
                "latency": latency_summary([]),
                "behavior": behavior_summary([]),
                "visual": None,
                "repeated_misses": {},
            }
            continue
        records, summary = analyze_job(jobs_root / job_name, protocol, model, 5)
        model_runs[key] = {
            "status": "official",
            "job": job_name,
            "records": records,
            "summary": summary,
            "costs": cost_summary(records),
            "latency": latency_summary(records),
            "behavior": behavior_summary(records),
            "visual": None,
            "repeated_misses": repeated_misses(records),
        }

    visual_hash = None
    if args.visual_review is not None:
        visual_config = protocol["reporting"]["visual_review"]
        rubric = load_object(protocol_path.parent / visual_config["rubric_path"])
        attach_visual_review(model_runs, args.visual_review, rubric)
        visual_hash = sha256(args.visual_review)
        for run in model_runs.values():
            run["visual"] = visual_summary(run["records"])

    overall = comparison_summary(model_runs, run_record)
    output = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(protocol_path),
        "run_record_sha256": sha256(args.run_record),
        "visual_review_sha256": visual_hash,
        "overall": overall,
        "models": model_runs,
        "historical_baseline": protocol["reporting"]["historical_baseline"],
        "run_record": run_record,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "analysis.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "report.md").write_text(
        render_report(protocol, run_record, model_runs, overall), encoding="utf-8"
    )
    print(f"wrote {args.output_dir / 'analysis.json'}")
    print(f"wrote {args.output_dir / 'report.md'}")
    print(
        f"retained={overall['retained']} infrastructure_errors="
        f"{overall['infrastructure_errors']}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    canary = subparsers.add_parser("canary")
    canary.add_argument("job_dir", type=Path)
    canary.add_argument("--protocol", required=True, type=Path)
    canary.add_argument("--model-key", required=True)
    canary.add_argument("--output", required=True, type=Path)
    canary.set_defaults(handler=run_canary)

    trace_sample = subparsers.add_parser("trace-sample")
    trace_sample.add_argument("--jobs-root", required=True, type=Path)
    trace_sample.add_argument("--protocol", required=True, type=Path)
    trace_sample.add_argument("--run-record", required=True, type=Path)
    trace_sample.add_argument("--output", required=True, type=Path)
    trace_sample.set_defaults(handler=run_trace_sample)

    official = subparsers.add_parser("official")
    official.add_argument("--jobs-root", required=True, type=Path)
    official.add_argument("--protocol", required=True, type=Path)
    official.add_argument("--run-record", required=True, type=Path)
    official.add_argument("--output-dir", required=True, type=Path)
    official.add_argument("--visual-review", type=Path)
    official.set_defaults(handler=run_official)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AnalysisError as exc:
        print(f"comparison analysis error: {exc}", file=sys.stderr)
        raise SystemExit(2)
