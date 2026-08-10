"""Validate and summarize the frozen Transactions multi-model comparison."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
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
    sha256,
    stats,
    validate_lock,
)


COMPARISON_SCHEMA_VERSION = "compute-bazaar-bench.transactions.comparison-analysis.v1"
CANARY_SCHEMA_VERSION = "compute-bazaar-bench.transactions.canary-analysis.v1"


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
        "agent_reported_usd": sum(costs) if costs else None,
        "agent_cost_coverage": len(costs),
        "planned_trials": len(records),
        "tokens": token_totals,
    }


def behavior_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in records if isinstance(row.get("trajectory"), dict)]
    coverage = [
        row["trajectory"].get("matter_document_coverage")
        for row in rows
        if row["trajectory"].get("matter_document_coverage") is not None
    ]
    return {
        "trials_with_trajectory": len(rows),
        "mean_matter_document_coverage": mean(coverage) if coverage else None,
        "post_draft_validation": sum(
            bool(row["trajectory"].get("post_draft_validation")) for row in rows
        ),
        "revision_after_validation": sum(
            bool(row["trajectory"].get("revision_after_validation")) for row in rows
        ),
        "returned_to_sources_after_draft": sum(
            bool(row["trajectory"].get("returned_to_sources_after_draft"))
            for row in rows
        ),
        "attempted_visual_render": sum(
            bool(row["trajectory"].get("attempted_visual_render")) for row in rows
        ),
        "trials_with_execution_errors": sum(
            int(row["trajectory"].get("error_observations", 0)) > 0 for row in rows
        ),
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
    expected = {
        f"{model_key}/{record['trial']}"
        for model_key, run in model_runs.items()
        for record in run["records"]
        if record.get("artifact_status_ok")
    }
    if set(items) != expected:
        raise AnalysisError(
            "visual review trial mismatch; "
            f"missing={sorted(expected - set(items))}, extra={sorted(set(items) - expected)}"
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
    record: dict[str, Any], protocol_path: Path, protocol: dict[str, Any]
) -> None:
    if record.get("protocol_id") != protocol["protocol_id"]:
        raise AnalysisError("comparison run record protocol mismatch")
    if record.get("protocol_sha256") != sha256(protocol_path):
        raise AnalysisError("comparison run record protocol digest mismatch")
    if not record.get("precommit_git_commit"):
        raise AnalysisError("comparison run record lacks precommit git commit")
    canaries = record.get("canary_jobs") or {}
    official = record.get("official_jobs") or {}
    for model in protocol["models"]:
        if canaries.get(model["key"]) != model["canary_job"]:
            raise AnalysisError(f"canary job mismatch for {model['key']}")
        if official.get(model["key"]) != model["official_job"]:
            raise AnalysisError(f"official job mismatch for {model['key']}")


def comparison_summary(model_runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    attempted = sum(len(run["records"]) for run in model_runs.values())
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
        "planned": attempted,
        "retained": attempted - infra,
        "infrastructure_errors": infra,
        "agent_invalid_outputs": invalid,
    }


def fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


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
            "Five unseeded attempts on each of three linked checkpoints from synthetic "
            "opportunity CB-2026-041. Fifteen paid canaries are excluded."
        ),
        "",
        "## Strict all-pass",
        "",
        "| Model | Retained | Valid DOCX | All pass | Macro semantic | Criterion pass | Agent cost |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in protocol["models"]:
        run = model_runs[model["key"]]
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
        summary = model_runs[model["key"]]["summary"]
        values = [
            fmt(summary["tasks"][name]["semantic"]["mean"]) for name in task_names
        ]
        lines.append(f"| {model['display_name']} | {' | '.join(values)} |")

    lines.extend(["", "## Denominator", ""])
    lines.append(
        f"- Planned: `{overall['planned']}`; retained: `{overall['retained']}`; "
        f"infrastructure: `{overall['infrastructure_errors']}`; malformed: "
        f"`{overall['agent_invalid_outputs']}`."
    )
    lines.append(f"- Precommit: `{run_record['precommit_git_commit']}`.")

    lines.extend(["", "## Document craft", ""])
    lines.append("| Model | Reviewed | Good | Mixed | Poor | Clipping | Overlap |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for model in protocol["models"]:
        visual = model_runs[model["key"]]["visual"]
        if visual is None:
            lines.append(f"| {model['display_name']} | 0 | - | - | - | - | - |")
        else:
            lines.append(
                f"| {model['display_name']} | {visual['reviewed']} | {visual['good']} | "
                f"{visual['mixed']} | {visual['poor']} | {visual['clipping']} | "
                f"{visual['overlap']} |"
            )

    lines.extend(["", "## Behavior", ""])
    lines.append(
        "| Model | Traces | Matter coverage | Validated draft | Revised after check | Returned to sources |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for model in protocol["models"]:
        behavior = model_runs[model["key"]]["behavior"]
        lines.append(
            f"| {model['display_name']} | {behavior['trials_with_trajectory']} | "
            f"{fmt(behavior['mean_matter_document_coverage'])} | "
            f"{behavior['post_draft_validation']} | {behavior['revision_after_validation']} | "
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


def run_official(args: argparse.Namespace) -> int:
    protocol_path = args.protocol.resolve()
    protocol = validate_commitment(protocol_path)
    run_record = load_object(args.run_record)
    validate_run_record(run_record, protocol_path, protocol)
    jobs_root = args.jobs_root.resolve()
    model_runs: dict[str, dict[str, Any]] = {}
    for model in protocol["models"]:
        job_name = run_record["official_jobs"][model["key"]]
        records, summary = analyze_job(jobs_root / job_name, protocol, model, 5)
        model_runs[model["key"]] = {
            "job": job_name,
            "records": records,
            "summary": summary,
            "costs": cost_summary(records),
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

    overall = comparison_summary(model_runs)
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
