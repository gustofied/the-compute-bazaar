"""Build task comparison charts from curated results and multi-agent jobs."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from viewer.harbor_jobs import summarize_harbor_job
from viewer.job_sources import (
    TRANSACTIONS_RELEASE_SUMMARY_SCHEMA,
    JobSource,
)
from viewer.schema import (
    BenchmarkChart,
    BenchmarkLegendItem,
    BenchmarkRow,
    BenchmarkSegment,
    ComparisonGroup,
)


COMPARISON_GROUP_SCHEMA = "compute-bazaar-bench.comparison-group.v1"


def discover_comparison_groups(
    bench_root: Path,
    public_release: dict[str, Any] | None,
    job_sources: dict[str, dict[str, JobSource]],
) -> dict[str, list[ComparisonGroup]]:
    """Load curated groups and finished top-level multi-agent Harbor jobs."""
    groups: dict[str, list[ComparisonGroup]] = {}

    if public_release:
        summary = public_release.get("summary")
        managed_tasks = public_release.get("managed_tasks")
        release_id = summary.get("release_id") if isinstance(summary, dict) else None
        if (
            isinstance(summary, dict)
            and isinstance(managed_tasks, list)
            and isinstance(release_id, str)
        ):
            charts = _transaction_charts(summary, managed_tasks, job_sources)
            for task_slug, chart in charts.items():
                groups.setdefault(task_slug, []).append(
                    ComparisonGroup(
                        id=release_id,
                        label=_display_group_name(release_id),
                        chart=chart,
                    )
                )

    comparison_paths = sorted(
        (bench_root / "evals").glob("**/comparisons/*.comparison.json")
    )
    for path in comparison_paths:
        document = _read_json(path)
        if document.get("schema_version") != COMPARISON_GROUP_SCHEMA:
            raise RuntimeError(f"invalid comparison group schema: {path}")
        group_id = document.get("id")
        label = document.get("label")
        tasks = document.get("tasks")
        source = document.get("source")
        if not isinstance(group_id, str) or not group_id:
            raise RuntimeError(f"comparison group has no ID: {path}")
        if not isinstance(label, str) or not label:
            raise RuntimeError(f"comparison group has no label: {path}")
        if not isinstance(tasks, list) or not all(
            isinstance(task, str) and task for task in tasks
        ):
            raise RuntimeError(f"comparison group has invalid tasks: {path}")
        if not isinstance(source, dict):
            raise RuntimeError(f"comparison group has no source: {path}")

        charts = _comparison_source_charts(tasks, source, job_sources, path)
        for task_slug, chart in charts.items():
            existing = groups.setdefault(task_slug, [])
            if any(group.id == group_id for group in existing):
                raise RuntimeError(
                    f"duplicate comparison group {group_id} for {task_slug}"
                )
            existing.append(ComparisonGroup(id=group_id, label=label, chart=chart))

    _add_multi_agent_job_groups(bench_root, job_sources, groups)

    return groups


def _add_multi_agent_job_groups(
    bench_root: Path,
    job_sources: dict[str, dict[str, JobSource]],
    groups: dict[str, list[ComparisonGroup]],
) -> None:
    """Treat each finished top-level job with multiple agents as a comparison."""
    jobs_root = (bench_root / "jobs").resolve()
    for task_slug, jobs in sorted(job_sources.items()):
        for job_id, job in sorted(jobs.items()):
            if job.raw_dir is None or job.raw_dir.parent.resolve() != jobs_root:
                continue
            if "-vs-" not in job_id.lower():
                continue
            summary = summarize_harbor_job(job.raw_dir, task_slug)
            if not summary.finished_at or len(summary.agent_configurations) < 2:
                continue
            existing = groups.setdefault(task_slug, [])
            if any(group.id == job_id for group in existing):
                continue
            chart, model_names = _raw_harbor_comparison_chart(
                job.raw_dir,
                task_slug,
            )
            if not chart.rows:
                continue
            label = (
                " vs ".join(model_names) if model_names else _display_group_name(job_id)
            )
            existing.append(
                ComparisonGroup(
                    id=job_id,
                    label=label,
                    chart=chart,
                )
            )


def _raw_harbor_comparison_chart(
    job_dir: Path,
    task_slug: str,
) -> tuple[BenchmarkChart, list[str]]:
    records = [
        record
        for trial_dir in sorted(path for path in job_dir.iterdir() if path.is_dir())
        if (record := _raw_trial_record(trial_dir, task_slug)) is not None
    ]
    model_names = list(dict.fromkeys(record["model_display"] for record in records))
    if any(record["market_result"] is not None for record in records):
        return _raw_reliability_chart(records), model_names
    return _raw_reward_chart(records), model_names


def _raw_reliability_chart(records: list[dict[str, Any]]) -> BenchmarkChart:
    grouped = _group_raw_records(records)
    rows = []
    for label, trials in grouped.items():
        observed = len(trials)
        completed_trials = [
            trial
            for trial in trials
            if isinstance(trial["market_result"], dict)
            and trial["market_result"].get("completion") == 1
        ]
        completed = len(completed_trials)
        target_met = sum(
            trial["market_result"].get("target_met") is True
            for trial in completed_trials
        )
        failure_rates = [
            float(trial["market_result"]["failure_rate"])
            for trial in completed_trials
            if isinstance(trial["market_result"].get("failure_rate"), (int, float))
        ]
        rate = f"{100 * mean(failure_rates):.1f}%" if failure_rates else "—"
        rows.append(
            BenchmarkRow(
                label=label,
                value=f"{target_met}/{observed} target met",
                detail=f"{completed}/{observed} completed · {rate} failure rate",
                segments=[
                    BenchmarkSegment(
                        label="Completed, target met",
                        value=target_met / observed,
                        tone="good",
                    ),
                    BenchmarkSegment(
                        label="Completed, target missed",
                        value=(completed - target_met) / observed,
                        tone="warn",
                    ),
                    BenchmarkSegment(
                        label="Did not complete",
                        value=(observed - completed) / observed,
                        tone="neutral",
                    ),
                ],
            )
        )
    return BenchmarkChart(
        title="Book completion and reliability target",
        description=(
            "Each bar separates books that completed 100 deals and met the 5% "
            "delivery-failure target, completed but missed it, or did not complete."
        ),
        rows=rows,
        legend=[
            BenchmarkLegendItem(label="Completed, target met", tone="good"),
            BenchmarkLegendItem(label="Completed, target missed", tone="warn"),
            BenchmarkLegendItem(label="Did not complete", tone="neutral"),
        ],
    )


def _raw_reward_chart(records: list[dict[str, Any]]) -> BenchmarkChart:
    rows = []
    for label, trials in _group_raw_records(records).items():
        rewards = [
            float(trial["reward"])
            for trial in trials
            if isinstance(trial.get("reward"), (int, float))
        ]
        average = mean(rewards) if rewards else None
        segments = (
            [
                BenchmarkSegment(
                    label="Mean reward",
                    value=average,
                    tone="info",
                )
            ]
            if average is not None and 0 <= average <= 1
            else []
        )
        rows.append(
            BenchmarkRow(
                label=label,
                value="—" if average is None else f"{average:.4f}",
                detail=f"{len(rewards)}/{len(trials)} scored trials",
                segments=segments,
            )
        )
    return BenchmarkChart(
        title="Harbor reward by agent",
        description="Mean task reward for each agent configuration in this job.",
        rows=rows,
        legend=[BenchmarkLegendItem(label="Mean reward", tone="info")],
    )


def _group_raw_records(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["agent_label"]), []).append(record)
    return grouped


def _raw_trial_record(
    trial_dir: Path,
    task_slug: str,
) -> dict[str, Any] | None:
    lock = _read_optional_json(trial_dir / "lock.json")
    if _raw_task_slug(lock) != task_slug:
        return None
    result = _read_optional_json(trial_dir / "result.json")
    agent = lock.get("agent") if isinstance(lock.get("agent"), dict) else {}
    model_name = str(agent.get("model_name") or "Unknown model")
    kwargs = agent.get("kwargs") if isinstance(agent.get("kwargs"), dict) else {}
    agent_name = str(agent.get("name") or "Agent")
    version = str(kwargs.get("version") or "")
    evidence = _read_optional_json(trial_dir / "verifier" / "evidence.json")
    market_result = evidence.get("result")
    if not isinstance(market_result, dict):
        market_result = None
    return {
        "agent_label": _agent_label(
            agent_name,
            version,
            _display_model_name(model_name),
        ),
        "model_display": _display_model_name(model_name),
        "market_result": market_result,
        "reward": _raw_reward(result, trial_dir),
    }


def _raw_task_slug(lock: dict[str, Any]) -> str:
    task = lock.get("task")
    if not isinstance(task, dict):
        return ""
    name = str(task.get("name") or "").rsplit("/", 1)[-1]
    path = task.get("path")
    if name == "task" and isinstance(path, str):
        package = Path(path)
        if package.name == "task":
            return package.parent.name
    return name


def _raw_reward(result: dict[str, Any], trial_dir: Path) -> float | None:
    verifier = result.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    reward = rewards.get("reward") if isinstance(rewards, dict) else None
    if not isinstance(reward, (int, float)):
        reward = _read_optional_json(trial_dir / "verifier" / "reward.json").get(
            "reward"
        )
    return float(reward) if isinstance(reward, (int, float)) else None


def _comparison_source_charts(
    tasks: list[str],
    source: dict[str, Any],
    job_sources: dict[str, dict[str, JobSource]],
    path: Path,
) -> dict[str, BenchmarkChart]:
    kind = source.get("kind")
    if kind != "reliability-is-blind-report":
        raise RuntimeError(f"unsupported comparison source {kind!r}: {path}")
    if len(tasks) != 1:
        raise RuntimeError(
            f"Reliability Is Blind comparison must name one task: {path}"
        )
    task_slug = tasks[0]
    job_id = source.get("job")
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError(f"comparison source has no job: {path}")
    job = job_sources.get(task_slug, {}).get(job_id)
    if job is None or job.report_dir is None:
        return {}
    return {task_slug: _reliability_chart(job.report_dir)}


def _reliability_chart(report_dir: Path) -> BenchmarkChart:
    protocol = _read_json(report_dir / "protocol.json")
    trials = _read_json_list(report_dir / "trials.json")
    model_rows = protocol.get("models")
    if not isinstance(model_rows, list):
        raise RuntimeError(
            f"Reliability Is Blind report has no model rows: {report_dir}"
        )

    chart_rows = []
    for model in model_rows:
        if not isinstance(model, dict):
            continue
        observed = int(model.get("observed_trials") or 0)
        completed = int(model.get("completed_rollouts") or 0)
        target_met = int(model.get("reliability_targets_met") or 0)
        if observed <= 0 or not 0 <= target_met <= completed <= observed:
            continue
        model_name = str(model.get("model") or "Unknown model")
        trial = next(
            (
                record.get("trial")
                for record in trials
                if isinstance(record, dict)
                and isinstance(record.get("trial"), dict)
                and record["trial"].get("model") == model_name
            ),
            None,
        )
        label = _agent_label_from_trial(trial, model_name)
        failure_rate = model.get("mean_completed_failure_rate")
        rate = (
            "—"
            if not isinstance(failure_rate, (int, float))
            else f"{100 * float(failure_rate):.1f}%"
        )
        chart_rows.append(
            BenchmarkRow(
                label=label,
                value=f"{target_met}/{observed} target met",
                detail=f"{completed}/{observed} completed · {rate} failure rate",
                segments=[
                    BenchmarkSegment(
                        label="Completed, target met",
                        value=target_met / observed,
                        tone="good",
                    ),
                    BenchmarkSegment(
                        label="Completed, target missed",
                        value=(completed - target_met) / observed,
                        tone="warn",
                    ),
                    BenchmarkSegment(
                        label="Did not complete",
                        value=(observed - completed) / observed,
                        tone="neutral",
                    ),
                ],
            )
        )

    return BenchmarkChart(
        eyebrow="",
        title="Book completion and reliability target",
        description=(
            "Each bar separates books that completed 100 deals and met the 5% "
            "delivery-failure target, completed 100 deals but missed it, or did "
            "not complete."
        ),
        rows=chart_rows,
        legend=[
            BenchmarkLegendItem(label="Completed, target met", tone="good"),
            BenchmarkLegendItem(label="Completed, target missed", tone="warn"),
            BenchmarkLegendItem(label="Did not complete", tone="neutral"),
        ],
    )


def _transaction_charts(
    summary: dict[str, Any],
    managed_tasks: list[Any],
    job_sources: dict[str, dict[str, JobSource]],
) -> dict[str, BenchmarkChart]:
    if summary.get("schema_version") != TRANSACTIONS_RELEASE_SUMMARY_SCHEMA:
        raise RuntimeError("invalid Transactions release summary for comparison")
    rows = summary.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("Transactions release summary has no agent rows")

    charts: dict[str, BenchmarkChart] = {}
    for task_slug in managed_tasks:
        if not isinstance(task_slug, str) or not task_slug:
            raise RuntimeError("Transactions release has an invalid managed task")
        ranked_rows: list[tuple[float, BenchmarkRow]] = []
        for agent_result in rows:
            if not isinstance(agent_result, dict):
                continue
            agent_tasks = agent_result.get("tasks")
            task = agent_tasks.get(task_slug) if isinstance(agent_tasks, dict) else None
            if not isinstance(task, dict):
                continue
            retained = int(task.get("retained") or 0)
            strict = int(task.get("all_pass") or 0)
            model_label = str(agent_result.get("model") or "Unknown model")
            job_id = str(agent_result.get("job") or "")
            job = job_sources.get(task_slug, {}).get(job_id)
            label = _agent_label_from_job(job, model_label)
            attempted = retained
            if job is not None and job.raw_dir is not None:
                attempted = max(
                    retained,
                    summarize_harbor_job(job.raw_dir, task_slug).trial_count,
                )
            output_gate = (
                agent_result.get("criterion_evaluation") == "not_run_output_gate"
            )
            if output_gate:
                ranked_rows.append(
                    (
                        -1.0,
                        BenchmarkRow(
                            label=label,
                            value="No reviewable documents",
                            detail=f"{attempted} attempts failed the output gate",
                        ),
                    )
                )
                continue
            semantic = task.get("semantic")
            mean = semantic.get("mean") if isinstance(semantic, dict) else None
            if not isinstance(mean, (int, float)):
                continue
            missed = max(retained - strict, 0)
            excluded = max(attempted - retained, 0)
            segments = []
            if attempted:
                if strict:
                    segments.append(
                        BenchmarkSegment(
                            label="Passed every requirement",
                            value=strict / attempted,
                            tone="good",
                        )
                    )
                if missed:
                    segments.append(
                        BenchmarkSegment(
                            label="Missed one or more requirements",
                            value=missed / attempted,
                            tone="warn",
                        )
                    )
                if excluded:
                    segments.append(
                        BenchmarkSegment(
                            label="Excluded",
                            value=excluded / attempted,
                            tone="neutral",
                        )
                    )
            detail_parts = [
                f"{100 * float(mean):.1f}% average requirements met across "
                f"{retained} scored documents"
            ]
            if excluded:
                detail_parts.append(f"{excluded} excluded")
            ranked_rows.append(
                (
                    float(mean),
                    BenchmarkRow(
                        label=label,
                        value=f"{strict} of {attempted} perfect",
                        detail=" · ".join(detail_parts),
                        segments=segments,
                    ),
                )
            )
        chart_rows = [
            row
            for _score, row in sorted(
                ranked_rows,
                key=lambda item: (-item[0], item[1].label),
            )
        ]
        charts[task_slug] = BenchmarkChart(
            eyebrow="Transactions",
            title="Document results",
            description=(
                "Each bar shows attempted documents. A perfect document passed "
                "every requirement; the percentage below is average requirement "
                "coverage across scored documents."
            ),
            rows=chart_rows,
            legend=[
                BenchmarkLegendItem(
                    label="Passed every requirement", tone="good"
                ),
                BenchmarkLegendItem(
                    label="Missed one or more", tone="warn"
                ),
                BenchmarkLegendItem(label="Excluded", tone="neutral"),
            ],
        )
    return charts


def _agent_label_from_job(job: JobSource | None, model_label: str) -> str:
    if job is None or job.raw_dir is None:
        return model_label
    lock = _read_json(job.raw_dir / "lock.json")
    trials = lock.get("trials")
    if not isinstance(trials, list):
        return model_label
    agents = set()
    for trial in trials:
        agent = trial.get("agent") if isinstance(trial, dict) else None
        if not isinstance(agent, dict):
            continue
        kwargs = agent.get("kwargs")
        version = kwargs.get("version") if isinstance(kwargs, dict) else None
        agents.add((str(agent.get("name") or "Agent"), str(version or "")))
    if len(agents) != 1:
        return model_label
    name, version = agents.pop()
    return _agent_label(name, version, model_label)


def _agent_label_from_trial(trial: Any, model_name: str) -> str:
    if not isinstance(trial, dict):
        return _display_model_name(model_name)
    return _agent_label(
        str(trial.get("agent") or "Agent"),
        str(trial.get("agent_version") or ""),
        _display_model_name(model_name),
    )


def _agent_label(name: str, version: str, model_label: str) -> str:
    display_name = "OpenCode" if name.lower() == "opencode" else name
    harness = f"{display_name} {version}" if version else display_name
    return f"{harness} + {model_label}"


def _display_model_name(model_name: str) -> str:
    normalized = model_name.removeprefix("openrouter/").removesuffix(":exacto")
    known = {
        "mistral/mistral-medium-3-5": "Mistral Medium 3.5",
        "mistral/mistral-small-2603": "Mistral Small 2603",
        "mistral/mistral-large-2512": "Mistral Large 2512",
        "mistralai/mistral-small-2603": "Mistral Small 2603",
        "deepseek/deepseek-v4-flash-20260731": "DeepSeek V4 Flash 0731",
        "tencent/hy3": "HY3",
        "z-ai/glm-5.2-20260616": "GLM 5.2",
    }
    if normalized in known:
        return known[normalized]
    return normalized.rsplit("/", 1)[-1].replace("-", " ").title()


def _display_group_name(group_id: str) -> str:
    return group_id.replace("-", " ").capitalize()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read comparison data {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"comparison data must be a JSON object: {path}")
    return value


def _read_json_list(path: Path) -> list[Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read comparison data {path}: {exc}") from exc
    if not isinstance(value, list):
        raise RuntimeError(f"comparison data must be a JSON list: {path}")
    return value


def _read_optional_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
