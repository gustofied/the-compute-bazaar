"""Load normalized comparisons and build temporary comparisons from Harbor jobs."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
from statistics import mean, median
from typing import Any

from pydantic import ValidationError

from .job_sources import JobSource
from .schema import (
    ComparisonAgent,
    ComparisonAttempt,
    ComparisonCell,
    ComparisonCountColumn,
    ComparisonMeasure,
    ComparisonMetricDefinition,
    ComparisonPresentation,
    ComparisonProvenance,
    ComparisonReference,
    ComparisonTask,
    ComparisonTelemetryColumn,
    ComparisonTelemetryRow,
    TaskInfo,
)


COMPARISON_SCHEMA = "compute-bazaar.viewer.comparison.v1"


def discover_comparisons(bench_root: Path) -> dict[str, ComparisonPresentation]:
    """Load complete comparison artifacts without interpreting benchmark results."""
    comparisons: dict[str, ComparisonPresentation] = {}
    for path in sorted((bench_root / "evals").glob("**/*.comparison.json")):
        document = read_object(path)
        try:
            comparison = ComparisonPresentation.model_validate(document)
        except ValidationError as exc:
            raise RuntimeError(f"invalid comparison artifact {path}: {exc}") from exc
        if comparison.schema_version != COMPARISON_SCHEMA:
            raise RuntimeError(f"unsupported comparison schema: {path}")
        if comparison.id in comparisons:
            raise RuntimeError(f"duplicate comparison ID {comparison.id}: {path}")
        comparisons[comparison.id] = comparison
    return comparisons


def write_comparison(path: Path, comparison: ComparisonPresentation) -> None:
    """Write one deterministic, fully normalized comparison artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(comparison.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )


def comparison_references(
    comparisons: dict[str, ComparisonPresentation],
) -> list[ComparisonReference]:
    return [
        ComparisonReference(
            id=item.id,
            label=item.label,
            description=item.description,
            task_slugs=[task.slug for task in item.tasks],
            agent_count=len(item.agents),
            primary_metric=item.primary_metric.label,
        )
        for item in comparisons.values()
    ]


def task_comparison_references(
    comparisons: dict[str, ComparisonPresentation], task_slug: str
) -> list[ComparisonReference]:
    return [
        reference
        for reference in comparison_references(comparisons)
        if task_slug in reference.task_slugs
    ]


def build_job_comparison(
    task: TaskInfo,
    selected_jobs: list[JobSource],
) -> ComparisonPresentation:
    """Compare selected raw Harbor jobs for one task without inventing a pass rule."""
    if len(selected_jobs) < 2:
        raise ValueError("select at least two jobs")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    agents: dict[str, ComparisonAgent] = {}
    source_ids: list[str] = []
    for source in selected_jobs:
        if source.raw_dir is None:
            continue
        source_ids.append(source.job_id)
        for trial in read_harbor_trials(source.raw_dir, task.slug):
            agent_id = "::".join((source.job_id, trial["harness"], trial["model"]))
            grouped[agent_id].append({**trial, "job_id": source.job_id})
            agents.setdefault(
                agent_id,
                ComparisonAgent(
                    id=agent_id,
                    label=f"{trial['harness']} + {trial['model']}",
                    model=trial["model"],
                    harness=trial["harness"],
                    execution_origin=source.job_id,
                ),
            )
    if len(grouped) < 2:
        raise ValueError("selected jobs resolve to fewer than two agent configurations")

    cells: list[ComparisonCell] = []
    attempts: list[ComparisonAttempt] = []
    telemetry: list[ComparisonTelemetryRow] = []
    for agent_id, records in grouped.items():
        rewards = [
            float(record["reward"])
            for record in records
            if isinstance(record.get("reward"), (int, float))
        ]
        errors = sum(record["status"] == "Error" for record in records)
        cells.append(
            ComparisonCell(
                agent_id=agent_id,
                task_slug=task.slug,
                primary=ComparisonMeasure(
                    label="mean Harbor reward",
                    value=f"{mean(rewards):.4f}" if rewards else "Not scored",
                    raw=mean(rewards) if rewards else None,
                    detail=f"{len(rewards)} scored of {len(records)} observed",
                ),
                counts={
                    "observed": len(records),
                    "scored": len(rewards),
                    "errors": errors,
                },
                attempt_values=rewards,
                job_id=records[0]["job_id"],
            )
        )
        telemetry.append(
            ComparisonTelemetryRow(
                agent_id=agent_id,
                values={
                    "agent_time": format_duration(median_number(records, "duration")),
                    "input": format_integer(median_number(records, "input_tokens")),
                    "cached": format_integer(median_number(records, "cached_tokens")),
                    "output": format_integer(median_number(records, "output_tokens")),
                },
            )
        )
        for record in records:
            reward = record.get("reward")
            attempts.append(
                ComparisonAttempt(
                    agent_id=agent_id,
                    task_slug=task.slug,
                    job_id=record["job_id"],
                    trial_id=record["trial_id"],
                    status=record["status"],
                    tone="bad" if record["status"] == "Error" else "neutral",
                    primary=(
                        f"{float(reward):.4f}"
                        if isinstance(reward, (int, float))
                        else "—"
                    ),
                    duration_seconds=record.get("duration"),
                    input_tokens=record.get("input_tokens"),
                    output_tokens=record.get("output_tokens"),
                )
            )

    return ComparisonPresentation(
        id="selected-jobs",
        label="Selected jobs",
        description="Direct comparison of the selected Harbor jobs.",
        primary_metric=ComparisonMetricDefinition(
            key="reward",
            label="Mean Harbor reward",
            description="Mean across trials where the verifier produced a reward.",
        ),
        tasks=[ComparisonTask(slug=task.slug, label=task.name)],
        agents=list(agents.values()),
        cells=cells,
        count_columns=[
            ComparisonCountColumn(key="observed", label="Observed"),
            ComparisonCountColumn(key="scored", label="Scored"),
            ComparisonCountColumn(key="errors", label="Errors"),
        ],
        telemetry_columns=default_telemetry_columns(),
        telemetry=telemetry,
        attempts=attempts,
        notes=[
            "No pass threshold is inferred from reward.",
            "Each configuration keeps the identity of its source job.",
        ],
        provenance=ComparisonProvenance(
            generator="viewer.raw-harbor.v1",
            sources=source_ids,
        ),
    )


def read_harbor_trials(job_dir: Path | None, task_slug: str) -> list[dict[str, Any]]:
    """Read common execution facts from raw Harbor trial directories."""
    if job_dir is None or not job_dir.is_dir():
        return []
    records = []
    for trial_dir in sorted(path for path in job_dir.iterdir() if path.is_dir()):
        if not (trial_dir / "lock.json").is_file():
            continue
        lock = read_object(trial_dir / "lock.json")
        if task_slug_from_lock(lock.get("task")) != task_slug:
            continue
        result_path = trial_dir / "result.json"
        result = read_object(result_path) if result_path.is_file() else {}
        agent = result.get("agent_info") or agent_from_lock(lock)
        agent = agent if isinstance(agent, dict) else {}
        model_info = agent.get("model_info")
        model_info = model_info if isinstance(model_info, dict) else {}
        usage = result.get("agent_result")
        usage = usage if isinstance(usage, dict) else {}
        exception = result.get("exception_info")
        reward = reward_from_trial(result, trial_dir)
        status = (
            "Error"
            if exception
            else "Completed"
            if result
            else "Scored"
            if reward is not None
            else "In progress"
        )
        records.append(
            {
                "trial_id": trial_dir.name,
                "task_slug": task_slug,
                "harness": agent_display(agent),
                "model": model_display(agent, model_info),
                "status": status,
                "reward": reward,
                "duration": elapsed_seconds(
                    result.get("started_at"), result.get("finished_at")
                ),
                "input_tokens": integer_or_none(usage.get("n_input_tokens")),
                "cached_tokens": integer_or_none(usage.get("n_cache_tokens")),
                "output_tokens": integer_or_none(usage.get("n_output_tokens")),
            }
        )
    return records


def default_telemetry_columns() -> list[ComparisonTelemetryColumn]:
    return [
        ComparisonTelemetryColumn(key="agent_time", label="Median agent time"),
        ComparisonTelemetryColumn(key="input", label="Median input"),
        ComparisonTelemetryColumn(key="cached", label="Median cached"),
        ComparisonTelemetryColumn(key="output", label="Median output"),
    ]


def median_number(records: list[dict[str, Any]], key: str) -> float | None:
    values = [
        float(record[key])
        for record in records
        if isinstance(record.get(key), (int, float))
    ]
    return median(values) if values else None


def task_slug_from_lock(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    name = str(value.get("name") or "").rsplit("/", 1)[-1]
    path = value.get("path")
    if name == "task" and isinstance(path, str):
        package = Path(path)
        if package.name in {"task", "harbor"}:
            return package.parent.name
    return name


def agent_from_lock(lock: dict[str, Any]) -> dict[str, Any]:
    agent = lock.get("agent")
    if not isinstance(agent, dict):
        return {}
    model_name = str(agent.get("model_name") or "")
    provider, _, name = model_name.partition("/")
    kwargs = agent.get("kwargs") or {}
    return {
        **agent,
        "version": kwargs.get("version") if isinstance(kwargs, dict) else None,
        "model_info": {"provider": provider, "name": name or provider},
    }


def agent_display(agent: Any) -> str:
    if not isinstance(agent, dict):
        return "—"
    name = str(agent.get("name") or "—")
    name = "OpenCode" if name.lower() == "opencode" else name
    kwargs = agent.get("kwargs")
    version = agent.get("version") or (
        kwargs.get("version") if isinstance(kwargs, dict) else None
    )
    return f"{name} {version}" if version else name


def model_display(agent: dict[str, Any], model_info: dict[str, Any]) -> str:
    provider = str(model_info.get("provider") or "")
    name = str(model_info.get("name") or agent.get("model_name") or "—")
    if provider and "/" not in name:
        return f"{provider}/{name}"
    return name


def reward_from_trial(result: dict[str, Any], trial_dir: Path) -> float | None:
    verifier = result.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    value = rewards.get("reward") if isinstance(rewards, dict) else None
    reward_path = trial_dir / "verifier" / "reward.json"
    if not isinstance(value, (int, float)) and reward_path.is_file():
        value = read_object(reward_path).get("reward")
    return float(value) if isinstance(value, (int, float)) else None


def elapsed_seconds(start: Any, finish: Any) -> float | None:
    if not isinstance(start, str) or not isinstance(finish, str):
        return None
    try:
        return (
            datetime.fromisoformat(finish.replace("Z", "+00:00"))
            - datetime.fromisoformat(start.replace("Z", "+00:00"))
        ).total_seconds()
    except ValueError:
        return None


def integer_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def format_integer(value: Any) -> str:
    return f"{int(value):,}" if isinstance(value, (int, float)) else "—"


def format_duration(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    seconds = float(value)
    if seconds >= 60:
        return f"{int(seconds // 60)}m {seconds % 60:.0f}s"
    return f"{seconds:.1f}s"


def slugify(value: str) -> str:
    return "-".join(
        "".join(
            character.lower() if character.isalnum() else " " for character in value
        ).split()
    )


def read_object(path: Path) -> dict[str, Any]:
    value = read_json(path)
    return value if isinstance(value, dict) else {}


def read_list(path: Path) -> list[Any]:
    value = read_json(path)
    if not isinstance(value, list):
        raise RuntimeError(f"expected a JSON list: {path}")
    return value


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read comparison data {path}: {exc}") from exc
