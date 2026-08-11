"""Present standard Harbor job files without eval-specific assumptions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from statistics import mean
from typing import Any

from .schema import (
    DataTable,
    DetailSection,
    JobPresentation,
    Metric,
    Notice,
    TableCell,
    TableColumn,
    TableRow,
    TaskInfo,
    TracePresentation,
    TraceStep,
    TraceToolCall,
    TrialPresentation,
)


@dataclass(frozen=True)
class HarborJobSummary:
    """Small task-scoped job summary that does not load artifacts or trajectories."""

    started_at: str
    finished_at: str
    agent_configurations: frozenset[tuple[str, str]]
    trial_count: int
    mean_reward: float | None


def summarize_harbor_job(job_dir: Path, task_slug: str) -> HarborJobSummary:
    """Read only the Harbor metadata needed by task and job indexes."""
    job_result = _object(job_dir / "result.json")
    agent_configurations: set[tuple[str, str]] = set()
    rewards = []
    trial_count = 0

    for path in sorted(child for child in job_dir.iterdir() if child.is_dir()):
        result = _object(path / "result.json")
        lock = _object(path / "lock.json")
        if _task_slug(result, lock) != task_slug:
            continue
        trial_count += 1

        agent = result.get("agent_info") or _agent_from_lock(lock)
        if not isinstance(agent, dict):
            agent = {}
        model = agent.get("model_info") or {}
        if not isinstance(model, dict):
            model = {}
        agent_name = str(agent.get("name") or "—")
        version = agent.get("version")
        agent_label = f"{agent_name} {version}" if version else agent_name
        provider = str(model.get("provider") or "")
        model_name = str(model.get("name") or agent.get("model_name") or "—")
        model_label = f"{provider}/{model_name}" if provider else model_name
        agent_configurations.add((agent_label, model_label))

        reward = _rewards(result, path).get("reward")
        if isinstance(reward, (int, float)):
            rewards.append(float(reward))

    return HarborJobSummary(
        started_at=str(job_result.get("started_at") or ""),
        finished_at=str(job_result.get("finished_at") or ""),
        agent_configurations=frozenset(agent_configurations),
        trial_count=trial_count,
        mean_reward=mean(rewards) if rewards else None,
    )


def present_harbor_job(job_dir: Path, task: TaskInfo, job_id: str) -> JobPresentation:
    """Build a task-scoped presentation directly from a Harbor job directory."""
    lock = _object(job_dir / "lock.json")
    job_result = _object(job_dir / "result.json")
    planned = _planned_trials(lock, task.slug)
    trials = [
        _trial(path, task.slug)
        for path in sorted(path for path in job_dir.iterdir() if path.is_dir())
    ]
    trials = [trial for trial in trials if trial is not None]

    trial_details = {trial["trial_id"]: _trial_presentation(trial) for trial in trials}
    numeric_rewards = [
        float(trial["reward"])
        for trial in trials
        if isinstance(trial.get("reward"), (int, float))
    ]
    completed = sum(trial["status"] == "completed" for trial in trials)
    errors = sum(trial["status"] == "error" for trial in trials)
    pending = max(planned - len(trials), 0)
    agents = _agent_rows(trials)
    retries = _job_stat(job_result, "n_retries")

    notices = []
    if errors or pending:
        notices.append(
            Notice(
                text=f"Run health: {errors} errors, {pending} not started or unfinished",
                tone="warn",
            )
        )

    return JobPresentation(
        task=task,
        job_id=job_id,
        started_at=str(job_result.get("started_at") or ""),
        finished_at=str(job_result.get("finished_at") or ""),
        agent_count=len(agents),
        trial_count=len(trials),
        primary_score=(
            Metric(
                label="Mean reward",
                value=_number(mean(numeric_rewards), 4),
                hint="Harbor verifier reward averaged across scored trials",
            )
            if numeric_rewards
            else None
        ),
        metrics=[
            Metric(label="Trials", value=f"{len(trials)}/{planned}"),
            Metric(label="Completed", value=str(completed)),
            Metric(
                label="Errors", value=str(errors), tone="bad" if errors else "neutral"
            ),
            Metric(label="Retries", value=str(retries)),
            Metric(label="Source", value="Harbor job"),
        ],
        notices=notices,
        agent_table=DataTable(
            title="Agents",
            description="Resolved harness, model, reward, usage, and cost from Harbor.",
            columns=[
                TableColumn(key="agent", label="Agent"),
                TableColumn(key="model", label="Model"),
                TableColumn(key="trials", label="Trials", align="right"),
                TableColumn(key="completed", label="Completed", align="right"),
                TableColumn(key="errors", label="Errors", align="right"),
                TableColumn(key="reward", label="Mean reward", align="right"),
                TableColumn(key="input", label="Input tokens", align="right"),
                TableColumn(key="output", label="Output tokens", align="right"),
                TableColumn(key="cost", label="Reported cost", align="right"),
            ],
            rows=agents,
        ),
        trial_table=DataTable(
            title="Trials",
            description="Each row is one Harbor trial for this task.",
            searchable=True,
            columns=[
                TableColumn(key="trial", label="Trial"),
                TableColumn(key="agent", label="Agent"),
                TableColumn(key="status", label="Status"),
                TableColumn(key="reward", label="Reward", align="right"),
                TableColumn(key="duration", label="Duration", align="right"),
                TableColumn(key="input", label="Input", align="right"),
                TableColumn(key="output", label="Output", align="right"),
                TableColumn(key="cost", label="Cost", align="right"),
            ],
            rows=[_trial_row(trial) for trial in trials],
        ),
        trials=trial_details,
    )


def _trial(path: Path, task_slug: str) -> dict[str, Any] | None:
    result = _object(path / "result.json")
    config = _object(path / "config.json")
    lock = _object(path / "lock.json")
    resolved_task = _task_slug(result, lock)
    if resolved_task != task_slug:
        return None

    rewards = _rewards(result, path)
    exception = result.get("exception_info") if result else None
    status = "error" if exception else "completed" if result else "in progress"
    agent = result.get("agent_info") or _agent_from_lock(lock)
    model = agent.get("model_info") if isinstance(agent, dict) else {}
    if not isinstance(model, dict):
        model = {}
    usage = result.get("agent_result") or {}
    if not isinstance(usage, dict):
        usage = {}
    artifact_manifest = _json(path / "artifacts" / "manifest.json")
    trajectory = _json(path / "agent" / "trajectory.json")
    reward = rewards.get("reward") if isinstance(rewards, dict) else None
    return {
        "trial_id": path.name,
        "status": status,
        "result": result,
        "config": config,
        "lock": lock,
        "rewards": rewards,
        "reward": reward,
        "exception": exception,
        "artifacts": artifact_manifest,
        "trajectory": trajectory,
        "agent": str(agent.get("name") or "—"),
        "agent_version": agent.get("version"),
        "provider": str(model.get("provider") or ""),
        "model": str(model.get("name") or agent.get("model_name") or "—"),
        "duration": _seconds(result.get("started_at"), result.get("finished_at")),
        "input_tokens": usage.get("n_input_tokens"),
        "cached_tokens": usage.get("n_cache_tokens"),
        "output_tokens": usage.get("n_output_tokens"),
        "cost": usage.get("cost_usd"),
    }


def _trial_row(trial: dict[str, Any]) -> TableRow:
    status = trial["status"]
    return TableRow(
        search=" ".join(
            str(trial.get(key, ""))
            for key in ("trial_id", "agent", "model", "provider", "status")
        ).lower(),
        cells={
            "trial": TableCell(value=trial["trial_id"], href=trial["trial_id"]),
            "agent": TableCell(value=_agent_label(trial)),
            "status": TableCell(
                value=status,
                tone="good"
                if status == "completed"
                else "bad"
                if status == "error"
                else "warn",
            ),
            "reward": TableCell(value=_number(trial.get("reward"), 4)),
            "duration": TableCell(value=_duration(trial.get("duration"))),
            "input": TableCell(value=_integer(trial.get("input_tokens"))),
            "output": TableCell(value=_integer(trial.get("output_tokens"))),
            "cost": TableCell(value=_money(trial.get("cost"))),
        },
    )


def _trial_presentation(trial: dict[str, Any]) -> TrialPresentation:
    sections = [
        DetailSection(title="Rewards", data=trial["rewards"] or {}),
        DetailSection(title="Timing", data=_timing(trial["result"])),
        DetailSection(title="Artifacts", data=trial["artifacts"] or []),
    ]
    sections.append(DetailSection(title="Resolved configuration", data=trial["lock"]))
    if trial["exception"] is not None:
        sections.insert(0, DetailSection(title="Error", data=trial["exception"]))
    return TrialPresentation(
        trial_id=trial["trial_id"],
        title=trial["trial_id"],
        summary=[
            Metric(label="Agent", value=_agent_label(trial)),
            Metric(label="Model", value=_model_label(trial)),
            Metric(label="Status", value=trial["status"]),
            Metric(label="Reward", value=_number(trial.get("reward"), 4)),
            Metric(label="Duration", value=_duration(trial.get("duration"))),
            Metric(label="Input tokens", value=_integer(trial.get("input_tokens"))),
            Metric(label="Output tokens", value=_integer(trial.get("output_tokens"))),
            Metric(label="Reported cost", value=_money(trial.get("cost"))),
        ],
        sections=sections,
        trace=_trace_presentation(trial["trajectory"]),
    )


def _trace_presentation(value: Any) -> TracePresentation | None:
    if not isinstance(value, dict):
        return None
    raw_steps = value.get("steps")
    if not isinstance(raw_steps, list):
        raw_steps = []
    steps = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            continue
        calls = []
        raw_calls = raw_step.get("tool_calls")
        if isinstance(raw_calls, list):
            for raw_call in raw_calls:
                if not isinstance(raw_call, dict):
                    continue
                calls.append(
                    TraceToolCall(
                        name=str(raw_call.get("function_name") or "tool"),
                        arguments=_trace_value(raw_call.get("arguments")),
                    )
                )
        source = str(raw_step.get("source") or "event")
        message = _trace_text(raw_step.get("message"), 8_000)
        observation = _trace_text(raw_step.get("observation"), 8_000)
        metrics = raw_step.get("metrics")
        steps.append(
            TraceStep(
                step_id=str(raw_step.get("step_id") or index),
                source=source,
                label=_trace_label(source, calls, message),
                message=message,
                tool_calls=calls,
                observation=observation,
                metrics=metrics if isinstance(metrics, dict) else {},
            )
        )
    final_metrics = value.get("final_metrics")
    return TracePresentation(
        schema_version=str(value.get("schema_version") or ""),
        step_count=len(steps),
        final_metrics=final_metrics if isinstance(final_metrics, dict) else {},
        steps=steps,
    )


def _trace_label(source: str, calls: list[TraceToolCall], message: str) -> str:
    if calls:
        return " · ".join(dict.fromkeys(call.name for call in calls))
    if source == "user":
        return "Instruction"
    if message:
        return "Response"
    return "Event"


def _trace_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _trace_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_trace_value(item) for item in value]
    if isinstance(value, str):
        return _trace_text(value, 4_000)
    return value


def _trace_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    has_binary_controls = any(
        ord(character) < 32 and character not in "\n\r\t" for character in text
    )
    if has_binary_controls:
        return f"[binary payload omitted · {len(text):,} characters]"
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n\n[… {omitted:,} characters omitted]"


def _agent_rows(trials: list[dict[str, Any]]) -> list[TableRow]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for trial in trials:
        grouped[
            (trial["agent"], str(trial.get("agent_version") or ""), _model_label(trial))
        ].append(trial)
    rows = []
    for (agent, version, model), items in sorted(grouped.items()):
        rewards = [
            float(item["reward"])
            for item in items
            if isinstance(item.get("reward"), (int, float))
        ]
        costs = [
            float(item["cost"])
            for item in items
            if isinstance(item.get("cost"), (int, float))
        ]
        rows.append(
            TableRow(
                search=f"{agent} {version} {model}".lower(),
                cells={
                    "agent": TableCell(value=f"{agent} {version}".strip()),
                    "model": TableCell(value=model),
                    "trials": TableCell(value=str(len(items))),
                    "completed": TableCell(
                        value=str(sum(item["status"] == "completed" for item in items))
                    ),
                    "errors": TableCell(
                        value=str(sum(item["status"] == "error" for item in items))
                    ),
                    "reward": TableCell(
                        value=_number(mean(rewards), 4) if rewards else "—"
                    ),
                    "input": TableCell(value=_integer(_sum(items, "input_tokens"))),
                    "output": TableCell(value=_integer(_sum(items, "output_tokens"))),
                    "cost": TableCell(value=_money(sum(costs)) if costs else "—"),
                },
            )
        )
    return rows


def _planned_trials(lock: dict[str, Any], task_slug: str) -> int:
    return sum(
        1
        for trial in lock.get("trials", [])
        if isinstance(trial, dict)
        and _task_from_spec(trial.get("task") or {}) == task_slug
    )


def _task_slug(result: dict[str, Any], lock: dict[str, Any]) -> str:
    result_name = _slug(result.get("task_name"))
    task = lock.get("task") or {}
    if result_name and result_name != "task":
        return result_name
    return _task_from_spec(task) or result_name


def _task_from_spec(task: dict[str, Any]) -> str:
    name = _slug(task.get("name"))
    path = task.get("path")
    if name == "task" and isinstance(path, str):
        package = Path(path)
        if package.name == "task" and package.parent.name:
            return package.parent.name
    return name


def _agent_from_lock(lock: dict[str, Any]) -> dict[str, Any]:
    agent = lock.get("agent") or {}
    model_name = str(agent.get("model_name") or "")
    provider, _, model = model_name.partition("/")
    return {
        "name": agent.get("name"),
        "version": (agent.get("kwargs") or {}).get("version"),
        "model_name": model_name,
        "model_info": {"provider": provider, "name": model or provider},
    }


def _rewards(result: dict[str, Any], trial_dir: Path) -> dict[str, Any]:
    verifier = result.get("verifier_result") or {}
    if isinstance(verifier, dict) and isinstance(verifier.get("rewards"), dict):
        return verifier["rewards"]
    reward_file = _object(trial_dir / "verifier" / "reward.json")
    return reward_file


def _timing(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "started_at": result.get("started_at"),
        "finished_at": result.get("finished_at"),
        "environment_setup": result.get("environment_setup"),
        "agent_setup": result.get("agent_setup"),
        "agent_execution": result.get("agent_execution"),
        "verifier": result.get("verifier"),
    }


def _job_stat(job_result: dict[str, Any], key: str) -> int:
    value = (job_result.get("stats") or {}).get(key, 0)
    return int(value) if isinstance(value, int) else 0


def _sum(items: list[dict[str, Any]], key: str) -> int | None:
    values = [item.get(key) for item in items if isinstance(item.get(key), int)]
    return sum(values) if values else None


def _agent_label(trial: dict[str, Any]) -> str:
    version = trial.get("agent_version")
    return f"{trial['agent']} {version}" if version else trial["agent"]


def _model_label(trial: dict[str, Any]) -> str:
    provider = trial.get("provider")
    return f"{provider}/{trial['model']}" if provider else trial["model"]


def _number(value: Any, digits: int = 3) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.{digits}f}"


def _integer(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) else "—"


def _money(value: Any) -> str:
    return f"${float(value):.4f}" if isinstance(value, (int, float)) else "—"


def _duration(value: Any) -> str:
    return f"{float(value):.1f}s" if isinstance(value, (int, float)) else "—"


def _seconds(start: Any, finish: Any) -> float | None:
    if not isinstance(start, str) or not isinstance(finish, str):
        return None
    try:
        return (
            datetime.fromisoformat(finish.replace("Z", "+00:00"))
            - datetime.fromisoformat(start.replace("Z", "+00:00"))
        ).total_seconds()
    except ValueError:
        return None


def _slug(value: Any) -> str:
    return str(value or "").rsplit("/", 1)[-1]


def _object(path: Path) -> dict[str, Any]:
    value = _json(path)
    return value if isinstance(value, dict) else {}


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
