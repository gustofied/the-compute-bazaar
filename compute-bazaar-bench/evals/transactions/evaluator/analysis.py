"""Validate and summarize a Transactions Harbor baseline job."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from statistics import mean, median
import sys
from typing import Any, Iterable


ANALYSIS_SCHEMA_VERSION = "compute-bazaar-bench.transactions.analysis.v1"

ERROR_MARKERS = (
    "traceback (most recent call last):",
    "command not found",
    "modulenotfounderror",
    "indentationerror",
    "syntaxerror",
    "attributeerror",
    "typeerror",
    "nameerror",
    "indexerror",
    "error: could not find",
)
VISUAL_RENDER_MARKERS = (
    "libreoffice",
    "soffice",
    "render_docx",
    "pdftoppm",
    "docx2pdf",
    "unoconv",
    "screenshot",
)


class AnalysisError(RuntimeError):
    """Raised when the run cannot be reconciled with its frozen protocol."""


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise AnalysisError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AnalysisError(f"expected an object in {path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nested_errors(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        if value.get("error"):
            errors.append(f"{path}: {value['error']}")
        for key, child in value.items():
            errors.extend(nested_errors(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(nested_errors(child, f"{path}[{index}]"))
    return errors


def seconds(start: Any, finish: Any) -> float | None:
    if not isinstance(start, str) or not isinstance(finish, str):
        return None
    try:
        left = datetime.fromisoformat(start.replace("Z", "+00:00"))
        right = datetime.fromisoformat(finish.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (right - left).total_seconds()


def expected_tasks(protocol: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = protocol.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise AnalysisError("protocol tasks must be a non-empty list")
    by_name: dict[str, dict[str, Any]] = {}
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("name"), str):
            raise AnalysisError("every protocol task needs a name")
        if task["name"] in by_name:
            raise AnalysisError(f"duplicate protocol task: {task['name']}")
        by_name[task["name"]] = task
    return by_name


def validate_lock(
    lock: dict[str, Any], protocol: dict[str, Any], tasks: dict[str, dict[str, Any]]
) -> None:
    trials = lock.get("trials")
    if not isinstance(trials, list):
        raise AnalysisError("job lock has no trials")
    if len(trials) != protocol["planned_trials"]:
        raise AnalysisError(
            f"job lock has {len(trials)} trials; expected {protocol['planned_trials']}"
        )

    counts: Counter[str] = Counter()
    for trial in trials:
        task = trial.get("task", {})
        name = task.get("name")
        if name not in tasks:
            raise AnalysisError(f"unexpected task in lock: {name}")
        if task.get("digest") != tasks[name]["digest"]:
            raise AnalysisError(f"task digest drift for {name}")
        counts[name] += 1

        agent = trial.get("agent", {})
        expected_agent = protocol["agent"]
        if agent.get("name") != expected_agent["name"]:
            raise AnalysisError(f"agent drift for {name}")
        if agent.get("model_name") != expected_agent["model"]:
            raise AnalysisError(f"model drift for {name}")
        if agent.get("kwargs", {}).get("version") != expected_agent["version"]:
            raise AnalysisError(f"agent version drift for {name}")
        if agent.get("extra_allowed_hosts") != [expected_agent["provider_host"]]:
            raise AnalysisError(f"agent network drift for {name}")

        environment = trial.get("environment", {})
        if environment.get("type") != protocol["environment"]["name"]:
            raise AnalysisError(f"environment drift for {name}")
        if environment.get("kwargs", {}).get("modal_vm_runtime") is not True:
            raise AnalysisError(f"Modal runtime drift for {name}")

    expected_count = protocol["attempts_per_task"]
    if counts != Counter({name: expected_count for name in tasks}):
        raise AnalysisError(f"task attempt counts do not match protocol: {dict(counts)}")


def validate_run_record(
    run_record: dict[str, Any],
    protocol: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    job_dir: Path,
) -> dict[str, Any]:
    if run_record.get("protocol_id") != protocol["protocol_id"]:
        raise AnalysisError("run record does not match protocol")
    if run_record.get("official_job") != job_dir.name:
        raise AnalysisError("run record does not identify this job as official")

    provenance = run_record.get("provenance") or {}
    if provenance.get("status") != "locally_predeclared" or not provenance.get("note"):
        raise AnalysisError("run record must disclose local predeclaration provenance")

    sampling = run_record.get("sampling") or {}
    if sampling.get("controlled_seed") is not False:
        raise AnalysisError("run record must disclose uncontrolled sampling seed")
    if sampling.get("judge_passes_per_submission") != 1:
        raise AnalysisError("unexpected judge-pass count in run record")

    costs = run_record.get("costs") or {}
    expected_judge_calls = (
        protocol["planned_trials"] * protocol["judge"]["semantic_batches_per_trial"]
    )
    if costs.get("judge_calls") != expected_judge_calls:
        raise AnalysisError("run record judge-call count does not match protocol")
    for key in ("agent_inference_usd", "judge_usd", "modal_compute_usd"):
        if key not in costs or costs[key] is not None:
            raise AnalysisError(f"run record must leave unreconciled {key} null")

    excluded = run_record.get("excluded_preflight_job") or {}
    excluded_name = excluded.get("name")
    if not isinstance(excluded_name, str) or not excluded.get("reason"):
        raise AnalysisError("run record needs an excluded preflight job and reason")
    preflight_dir = job_dir.parent / excluded_name
    validate_lock(load_object(preflight_dir / "lock.json"), protocol, tasks)
    preflight_trials = [
        load_object(path) for path in sorted(preflight_dir.glob("*/result.json"))
    ]
    if not preflight_trials:
        raise AnalysisError("excluded preflight job has no retained setup attempts")
    if any(
        trial.get("agent_execution") is not None
        or trial.get("agent_result") is not None
        for trial in preflight_trials
    ):
        raise AnalysisError("excluded preflight job contains agent execution")
    exception_types = Counter(
        str((trial.get("exception_info") or {}).get("exception_type", "unknown"))
        for trial in preflight_trials
    )

    enriched = dict(run_record)
    enriched["excluded_preflight_job"] = {
        **excluded,
        "planned_trials": protocol["planned_trials"],
        "setup_attempts": len(preflight_trials),
        "unstarted_trials": protocol["planned_trials"] - len(preflight_trials),
        "agent_executions": 0,
        "exception_types": dict(sorted(exception_types.items())),
    }
    return enriched


def exact_artifact_ok(manifest: Any, deliverable: str) -> bool:
    if not isinstance(manifest, list):
        return False
    matches = [
        item
        for item in manifest
        if isinstance(item, dict) and item.get("source") == f"/app/{deliverable}"
    ]
    return len(matches) == 1 and matches[0].get("status") == "ok"


def criteria_from_details(details: dict[str, Any]) -> list[dict[str, Any]]:
    criteria: list[dict[str, Any]] = []
    for dimension, value in details.items():
        if dimension == "output-integrity" or not isinstance(value, dict):
            continue
        items = value.get("criteria")
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                criteria.append(item)
    return criteria


def inspect_trajectory(
    path: Path, deliverable: str, expected_agent: dict[str, Any]
) -> dict[str, Any]:
    trajectory = load_object(path)
    agent = trajectory.get("agent") or {}
    if (
        agent.get("name") != expected_agent["name"]
        or agent.get("version") != expected_agent["version"]
        or agent.get("model_name") != expected_agent["model"]
    ):
        raise AnalysisError(f"trajectory agent does not match protocol in {path}")

    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        raise AnalysisError(f"trajectory has no steps in {path}")

    calls: list[dict[str, Any]] = []
    observations: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_calls = step.get("tool_calls") or []
        if isinstance(step_calls, list):
            calls.extend(call for call in step_calls if isinstance(call, dict))
        results = (step.get("observation") or {}).get("results") or []
        if isinstance(results, list):
            observations.extend(
                result.get("content", "")
                for result in results
                if isinstance(result, dict) and isinstance(result.get("content"), str)
            )

    commands = [
        str((call.get("arguments") or {}).get("command", "")) for call in calls
    ]
    lowered_commands = [command.lower() for command in commands]
    output_open_pattern = re.compile(
        rf"document\s*\(\s*(['\"])(?:/app/)?{re.escape(deliverable.lower())}\1"
    )
    tool_counts = Counter(str(call.get("function_name", "unknown")) for call in calls)
    binary_suffixes = (".docx", ".xlsx", ".pdf")
    direct_binary_read = any(
        call.get("function_name") == "read"
        and str((call.get("arguments") or {}).get("filePath", ""))
        .lower()
        .endswith(binary_suffixes)
        for call in calls
    )
    error_observations = sum(
        any(marker in content.lower() for marker in ERROR_MARKERS)
        for content in observations
    )

    return {
        "steps": len(steps),
        "tool_calls": dict(sorted(tool_counts.items())),
        "used_python_docx": any(
            "from docx" in command or "import docx" in command
            for command in lowered_commands
        ),
        "attempted_visual_render": any(
            marker in command
            for command in lowered_commands
            for marker in VISUAL_RENDER_MARKERS
        ),
        "reopened_output": any(
            output_open_pattern.search(command) is not None for command in lowered_commands
        ),
        "checked_output_exists": any(
            deliverable.lower() in command
            and any(check in command for check in ("ls ", "test -f", "stat "))
            for command in lowered_commands
        ),
        "attempted_package_install": any(
            marker in command
            for command in lowered_commands
            for marker in ("pip install", "pip3 install", "apt install", "apt-get install")
        ),
        "direct_binary_read": direct_binary_read,
        "error_observations": error_observations,
    }


def classify_trial(
    trial_dir: Path, task: dict[str, Any], expected_agent: dict[str, Any]
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "trial": trial_dir.name,
        "task": task["name"],
        "infrastructure_error": None,
        "agent_invalid_output": False,
    }
    try:
        result = load_object(trial_dir / "result.json")
    except AnalysisError as exc:
        record["infrastructure_error"] = str(exc)
        return record

    record["started_at"] = result.get("started_at")
    record["finished_at"] = result.get("finished_at")
    record["duration_seconds"] = seconds(
        result.get("started_at"), result.get("finished_at")
    )
    record["agent_seconds"] = seconds(
        result.get("agent_execution", {}).get("started_at"),
        result.get("agent_execution", {}).get("finished_at"),
    )
    record["verifier_seconds"] = seconds(
        result.get("verifier", {}).get("started_at"),
        result.get("verifier", {}).get("finished_at"),
    )

    agent_info = result.get("agent_info") or {}
    model_info = agent_info.get("model_info") or {}
    if (
        agent_info.get("name") != expected_agent["name"]
        or agent_info.get("version") != expected_agent["version"]
        or f"{model_info.get('provider')}/{model_info.get('name')}"
        != expected_agent["model"]
    ):
        record["infrastructure_error"] = "resolved agent does not match protocol"
        return record

    if result.get("exception_info") is not None:
        record["infrastructure_error"] = f"Harbor exception: {result['exception_info']}"
        return record

    try:
        manifest = json.loads((trial_dir / "artifacts" / "manifest.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        record["infrastructure_error"] = f"artifact manifest error: {exc}"
        return record
    record["artifact_status_ok"] = exact_artifact_ok(manifest, task["deliverable"])
    if not record["artifact_status_ok"]:
        record["infrastructure_error"] = "required artifact was not collected with status=ok"
        return record

    verifier_dir = trial_dir / "verifier"
    try:
        reward = load_object(verifier_dir / "reward.json")
        details = load_object(verifier_dir / "reward-details.json")
    except AnalysisError as exc:
        record["infrastructure_error"] = str(exc)
        return record

    errors = nested_errors(details)
    if errors:
        record["infrastructure_error"] = "; ".join(errors)
        return record

    required_rewards = {"reward", "all_pass", "output-integrity"}
    if not required_rewards.issubset(reward):
        record["infrastructure_error"] = "verifier output is missing required rewards"
        return record

    record["harbor_reward"] = float(reward["reward"])
    record["all_pass"] = float(reward["all_pass"])
    record["output_integrity"] = float(reward["output-integrity"])
    failure_kind = details.get("failure_kind")
    if failure_kind == "invalid_deliverable" or record["output_integrity"] != 1.0:
        record["agent_invalid_output"] = True
        record["semantic_passes"] = 0
        record["semantic_criteria"] = int(task["semantic_criteria"])
        record["semantic_score"] = 0.0
        record["criteria"] = []
    else:
        criteria = criteria_from_details(details)
        expected_count = int(task["semantic_criteria"])
        if len(criteria) != expected_count:
            record["infrastructure_error"] = (
                f"verifier returned {len(criteria)} semantic criteria; "
                f"expected {expected_count}"
            )
            return record
        ids = [item.get("id") for item in criteria]
        if len(ids) != len(set(ids)) or any(not isinstance(item, str) for item in ids):
            record["infrastructure_error"] = "semantic criterion IDs are missing or duplicated"
            return record
        values = [float(item.get("value")) for item in criteria]
        if any(value not in (0.0, 1.0) for value in values):
            record["infrastructure_error"] = "semantic criteria are not binary"
            return record
        record["semantic_passes"] = int(sum(values))
        record["semantic_criteria"] = expected_count
        record["semantic_score"] = sum(values) / expected_count
        record["criteria"] = [
            {
                "id": item["id"],
                "value": float(item["value"]),
                "description": item.get("description", ""),
                "reasoning": item.get("reasoning", ""),
            }
            for item in criteria
        ]

    usage = result.get("agent_result") or {}
    record["tokens"] = {
        "input": usage.get("n_input_tokens"),
        "cache": usage.get("n_cache_tokens"),
        "output": usage.get("n_output_tokens"),
    }
    record["reported_cost_usd"] = usage.get("cost_usd")
    try:
        record["trajectory"] = inspect_trajectory(
            trial_dir / "agent" / "trajectory.json", task["deliverable"], expected_agent
        )
    except AnalysisError as exc:
        record["infrastructure_error"] = str(exc)
    return record


def stats(values: Iterable[float]) -> dict[str, Any]:
    items = list(values)
    if not items:
        return {"mean": None, "median": None, "min": None, "max": None}
    return {
        "mean": mean(items),
        "median": median(items),
        "min": min(items),
        "max": max(items),
    }


def aggregate(records: list[dict[str, Any]], tasks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_task[record["task"]].append(record)

    task_rows: dict[str, Any] = {}
    total_passes = 0
    total_criteria = 0
    macro_values: list[float] = []
    for name in tasks:
        rows = by_task[name]
        retained = [row for row in rows if row["infrastructure_error"] is None]
        semantic_values = [row["semantic_score"] for row in retained]
        harbor_values = [row["harbor_reward"] for row in retained]
        semantic_stats = stats(semantic_values)
        if semantic_stats["mean"] is not None:
            macro_values.append(semantic_stats["mean"])
        total_passes += sum(row["semantic_passes"] for row in retained)
        total_criteria += sum(row["semantic_criteria"] for row in retained)
        task_rows[name] = {
            "attempted": len(rows),
            "retained": len(retained),
            "infrastructure_errors": len(rows) - len(retained),
            "valid_docx": sum(
                not row["agent_invalid_output"] for row in retained
            ),
            "all_pass": sum(row["all_pass"] == 1.0 for row in retained),
            "semantic": semantic_stats,
            "harbor_reward": stats(harbor_values),
            "attempt_values": semantic_values,
            "latency_seconds": {
                "agent": stats(
                    row["agent_seconds"]
                    for row in retained
                    if row.get("agent_seconds") is not None
                ),
                "verifier": stats(
                    row["verifier_seconds"]
                    for row in retained
                    if row.get("verifier_seconds") is not None
                ),
                "total": stats(
                    row["duration_seconds"]
                    for row in retained
                    if row.get("duration_seconds") is not None
                ),
            },
        }

    token_totals: dict[str, int | None] = {}
    for key in ("input", "cache", "output"):
        values = [
            row.get("tokens", {}).get(key)
            for row in records
            if row["infrastructure_error"] is None
        ]
        token_totals[key] = sum(value for value in values if isinstance(value, int))

    retained_records = [
        row for row in records if row["infrastructure_error"] is None
    ]
    tool_calls: Counter[str] = Counter()
    for row in retained_records:
        tool_calls.update(row["trajectory"]["tool_calls"])
    trajectory = {
        "trials": len(retained_records),
        "tool_calls": dict(sorted(tool_calls.items())),
        "used_python_docx": sum(
            row["trajectory"]["used_python_docx"] for row in retained_records
        ),
        "attempted_visual_render": sum(
            row["trajectory"]["attempted_visual_render"] for row in retained_records
        ),
        "reopened_output": sum(
            row["trajectory"]["reopened_output"] for row in retained_records
        ),
        "checked_output_exists": sum(
            row["trajectory"]["checked_output_exists"] for row in retained_records
        ),
        "attempted_package_install": sum(
            row["trajectory"]["attempted_package_install"] for row in retained_records
        ),
        "direct_binary_read": sum(
            row["trajectory"]["direct_binary_read"] for row in retained_records
        ),
        "trials_with_execution_errors": sum(
            row["trajectory"]["error_observations"] > 0 for row in retained_records
        ),
        "error_observations": sum(
            row["trajectory"]["error_observations"] for row in retained_records
        ),
    }

    return {
        "tasks": task_rows,
        "macro_semantic_mean": mean(macro_values) if macro_values else None,
        "micro_semantic_rate": total_passes / total_criteria if total_criteria else None,
        "semantic_passes": total_passes,
        "semantic_criteria": total_criteria,
        "strict_all_pass_rate": (
            sum(row.get("all_pass") == 1.0 for row in records if row["infrastructure_error"] is None)
            / sum(row["infrastructure_error"] is None for row in records)
            if any(row["infrastructure_error"] is None for row in records)
            else None
        ),
        "token_totals": token_totals,
        "trajectory": trajectory,
    }


def repeated_misses(records: list[dict[str, Any]], minimum: int = 3) -> dict[str, list[dict[str, Any]]]:
    misses: dict[str, Counter[str]] = defaultdict(Counter)
    descriptions: dict[tuple[str, str], str] = {}
    for record in records:
        if record["infrastructure_error"] is not None:
            continue
        for criterion in record.get("criteria", []):
            key = criterion["id"]
            descriptions[(record["task"], key)] = criterion["description"]
            if criterion["value"] == 0.0:
                misses[record["task"]][key] += 1
    return {
        task: [
            {
                "id": criterion_id,
                "misses": count,
                "description": descriptions[(task, criterion_id)],
            }
            for criterion_id, count in counter.most_common()
            if count >= minimum
        ]
        for task, counter in misses.items()
    }


def attach_visual_review(
    records: list[dict[str, Any]], review_path: Path
) -> dict[str, Any]:
    review = load_object(review_path)
    items = review.get("trials")
    if not isinstance(items, dict):
        raise AnalysisError("visual review must contain a trials object")

    expected = {record["trial"] for record in records}
    if set(items) != expected:
        missing = sorted(expected - set(items))
        extra = sorted(set(items) - expected)
        raise AnalysisError(
            f"visual review trial mismatch; missing={missing}, extra={extra}"
        )

    allowed = {"good", "mixed", "poor"}
    for record in records:
        item = items[record["trial"]]
        if not isinstance(item, dict):
            raise AnalysisError(f"invalid visual review for {record['trial']}")
        if item.get("practical_usability") not in allowed:
            raise AnalysisError(f"invalid usability rating for {record['trial']}")
        if not isinstance(item.get("page_count"), int) or item["page_count"] < 1:
            raise AnalysisError(f"invalid page count for {record['trial']}")
        record["visual_review"] = item
    return review


def visual_summary(
    records: list[dict[str, Any]], tasks: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    if not records or any("visual_review" not in record for record in records):
        return None
    output: dict[str, Any] = {}
    for task in tasks:
        rows = [record for record in records if record["task"] == task]
        ratings = Counter(
            record["visual_review"]["practical_usability"] for record in rows
        )
        page_counts = [record["visual_review"]["page_count"] for record in rows]
        output[task] = {
            "good": ratings["good"],
            "mixed": ratings["mixed"],
            "poor": ratings["poor"],
            "page_count": stats(page_counts),
            "clipping": sum(record["visual_review"]["clipping"] for record in rows),
            "overlap": sum(record["visual_review"]["overlap"] for record in rows),
        }
    return output


def fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def render_report(
    protocol: dict[str, Any],
    run_record: dict[str, Any],
    records: list[dict[str, Any]],
    summary: dict[str, Any],
    visuals: dict[str, Any] | None,
) -> str:
    excluded = run_record["excluded_preflight_job"]
    exception_types = ", ".join(
        f"{name} {count}" for name, count in excluded["exception_types"].items()
    )
    lines = [
        "# Transactions v1 local baseline",
        "",
        (
            "Five fresh Mistral Medium 3.5 attempts on each of three fixed checkpoints "
            "from synthetic opportunity CB-2026-041. Calibration canaries are excluded."
        ),
        "",
        "## Run record",
        "",
        f"- Sole scored job: `{run_record['official_job']}`.",
        (
            f"- Excluded preflight `{excluded['name']}`: {excluded['setup_attempts']} "
            f"setup attempts ({exception_types}), {excluded['unstarted_trials']} not "
            "started, and no agent execution."
        ),
        f"- Provenance: {run_record['provenance']['note']}",
        "",
        "## Results",
        "",
        "| Task | Retained | Valid DOCX | Mean semantic | Median | Range | All pass | Mean Harbor reward |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for task in protocol["tasks"]:
        row = summary["tasks"][task["name"]]
        semantic = row["semantic"]
        lines.append(
            "| {name} | {retained}/{attempted} | {valid}/{retained} | {mean} | {median} | "
            "{low}-{high} | {passed}/{retained} | {harbor} |".format(
                name=task["name"],
                retained=row["retained"],
                attempted=row["attempted"],
                valid=row["valid_docx"],
                mean=fmt(semantic["mean"]),
                median=fmt(semantic["median"]),
                low=fmt(semantic["min"]),
                high=fmt(semantic["max"]),
                passed=row["all_pass"],
                harbor=fmt(row["harbor_reward"]["mean"]),
            )
        )

    lines.extend(
        [
            "",
            "## Overall",
            "",
            f"- Equal-task macro semantic score: `{fmt(summary['macro_semantic_mean'])}`",
            (
                "- Pooled micro semantic rate: "
                f"`{summary['semantic_passes']}/{summary['semantic_criteria']}` "
                f"(`{fmt(summary['micro_semantic_rate'])}`)"
            ),
            f"- Strict all-pass rate: `{fmt(summary['strict_all_pass_rate'])}`",
            (
                "- Agent tokens: "
                f"`{summary['token_totals']['input']}` input, "
                f"`{summary['token_totals']['cache']}` cached, "
                f"`{summary['token_totals']['output']}` output"
            ),
            (
                f"- Judge calls: `{run_record['costs']['judge_calls']}` batched "
                f"{protocol['judge']['model']} calls."
            ),
            f"- Cost disclosure: {run_record['costs']['note']}",
            "",
            "## Attempts",
            "",
        ]
    )
    for task in protocol["tasks"]:
        row = summary["tasks"][task["name"]]
        values = ", ".join(f"{value:.4f}" for value in row["attempt_values"])
        lines.append(f"- `{task['name']}`: {values or 'no retained attempts'}")

    lines.extend(
        [
            "",
            "## Phase latency",
            "",
            "| Task | Agent mean | Agent median | Agent range | Verifier mean | Verifier range |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for task in protocol["tasks"]:
        latency = summary["tasks"][task["name"]]["latency_seconds"]
        agent = latency["agent"]
        verifier = latency["verifier"]
        lines.append(
            f"| {task['name']} | {agent['mean']:.1f}s | {agent['median']:.1f}s | "
            f"{agent['min']:.1f}-{agent['max']:.1f}s | {verifier['mean']:.1f}s | "
            f"{verifier['min']:.1f}-{verifier['max']:.1f}s |"
        )

    trajectory = summary["trajectory"]
    tool_calls = ", ".join(
        f"{name} {count}" for name, count in trajectory["tool_calls"].items()
    )
    lines.extend(
        [
            "",
            "## Execution behavior",
            "",
            (
                f"- `{trajectory['used_python_docx']}/{trajectory['trials']}` attempts "
                "generated the deliverable with python-docx."
            ),
            (
                f"- `{trajectory['reopened_output']}/{trajectory['trials']}` reopened "
                "the generated DOCX structurally; all checked that the output path existed."
            ),
            (
                f"- `{trajectory['attempted_visual_render']}/{trajectory['trials']}` "
                "rendered or visually inspected the DOCX before submission."
            ),
            (
                f"- `{trajectory['trials_with_execution_errors']}/{trajectory['trials']}` "
                "encountered at least one observed command or document-generation error "
                "and recovered to a valid artifact."
            ),
            (
                f"- `{trajectory['direct_binary_read']}/{trajectory['trials']}` "
                "attempted to pass a binary matter file through the text read tool."
            ),
            (
                f"- `{trajectory['attempted_package_install']}/{trajectory['trials']}` "
                "attempted a runtime package install."
            ),
            f"- Tool calls: {tool_calls}.",
        ]
    )

    if visuals is not None:
        lines.extend(
            [
                "",
                "## Document craft",
                "",
                "| Task | Good | Mixed | Poor | Page range | Clipping | Overlap |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for task in protocol["tasks"]:
            row = visuals[task["name"]]
            pages = row["page_count"]
            lines.append(
                f"| {task['name']} | {row['good']} | {row['mixed']} | {row['poor']} | "
                f"{int(pages['min'])}-{int(pages['max'])} | {row['clipping']} | "
                f"{row['overlap']} |"
            )
        lines.extend(["", "### Trial notes", ""])
        for record in records:
            review = record["visual_review"]
            lines.append(
                f"- `{record['trial']}` ({review['page_count']} pages, "
                f"{review['practical_usability']}): {review['notes']}"
            )

    misses = repeated_misses(records)
    lines.extend(["", "## Repeated misses", ""])
    for task in protocol["tasks"]:
        items = misses.get(task["name"], [])
        lines.append(f"### {task['name']}")
        lines.append("")
        if not items:
            lines.append("No criterion failed in at least three retained attempts.")
        else:
            for item in items:
                lines.append(
                    f"- `{item['id']}` failed {item['misses']}/5: {item['description']}"
                )
        lines.append("")

    infra = [row for row in records if row["infrastructure_error"] is not None]
    lines.extend(["## Run validity", ""])
    lines.append(f"- Infrastructure failures: `{len(infra)}`")
    for row in infra:
        lines.append(f"- `{row['trial']}`: {row['infrastructure_error']}")
    lines.extend(
        [
            "",
            "## Limits",
            "",
            "This is a three-checkpoint baseline on one synthetic transaction scenario. "
            "The attempts had no controlled sampling seed, and each semantic criterion "
            "received one frozen LLM-judge evaluation. They measure observed rollout and "
            "judge variation, not independent matter performance or scenario variability. "
            "The tasks are not independent matters, and the result is not a broad model "
            "ranking.",
            "",
            "Document craft is reviewed separately from extracted-text reward.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--run-record", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--visual-review", type=Path)
    args = parser.parse_args()

    protocol = load_object(args.protocol)
    tasks = expected_tasks(protocol)
    job_dir = args.job_dir.resolve()
    validate_lock(load_object(job_dir / "lock.json"), protocol, tasks)
    run_record = validate_run_record(
        load_object(args.run_record), protocol, tasks, job_dir
    )

    trial_dirs = sorted(
        path.parent
        for path in job_dir.glob("*/result.json")
        if path.parent != job_dir
    )
    if len(trial_dirs) != protocol["planned_trials"]:
        raise AnalysisError(
            f"found {len(trial_dirs)} trial results; expected {protocol['planned_trials']}"
        )

    records: list[dict[str, Any]] = []
    for trial_dir in trial_dirs:
        result = load_object(trial_dir / "result.json")
        name = str(result.get("task_name", "")).removeprefix("gustofied/")
        if name not in tasks:
            raise AnalysisError(f"unexpected task result in {trial_dir}: {name}")
        records.append(classify_trial(trial_dir, tasks[name], protocol["agent"]))

    review = None
    if args.visual_review is not None:
        review = attach_visual_review(records, args.visual_review)
    summary = aggregate(records, tasks)
    visuals = visual_summary(records, tasks)
    output = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(args.protocol),
        "run_record_sha256": sha256(args.run_record),
        "job": job_dir.name,
        "run_record": run_record,
        "summary": summary,
        "visual_summary": visuals,
        "visual_review_sha256": sha256(args.visual_review) if review else None,
        "repeated_misses": repeated_misses(records),
        "trials": records,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "analysis.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "report.md").write_text(
        render_report(protocol, run_record, records, summary, visuals), encoding="utf-8"
    )

    infra = sum(record["infrastructure_error"] is not None for record in records)
    print(f"wrote {args.output_dir / 'analysis.json'}")
    print(f"wrote {args.output_dir / 'report.md'}")
    print(f"retained={len(records) - infra} infrastructure_errors={infra}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AnalysisError as exc:
        print(f"analysis error: {exc}", file=sys.stderr)
        raise SystemExit(2)
