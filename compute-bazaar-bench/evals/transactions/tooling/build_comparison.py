"""Build the normalized Transactions comparison artifact."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any


BENCH_ROOT = Path(__file__).resolve().parents[3]
if str(BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCH_ROOT))

from viewer.comparisons import (  # noqa: E402
    agent_display,
    default_telemetry_columns,
    format_duration,
    format_integer,
    read_harbor_trials,
    read_object,
    slugify,
    write_comparison,
)
from viewer.job_sources import (  # noqa: E402
    TRANSACTIONS_ADJUDICATION_SCHEMA,
    JobSource,
    discover_job_sources,
    load_public_release_summary,
)
from viewer.schema import (  # noqa: E402
    ComparisonAgent,
    ComparisonAttempt,
    ComparisonCell,
    ComparisonCountColumn,
    ComparisonMeasure,
    ComparisonMetricDefinition,
    ComparisonPresentation,
    ComparisonProvenance,
    ComparisonTask,
    ComparisonTelemetryRow,
)
from viewer.task_catalog import discover_task_definitions  # noqa: E402


REPORTS_ROOT = BENCH_ROOT / "jobs" / "reports"
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent / "comparisons/transactions.comparison.json"
)


def build_comparison() -> ComparisonPresentation:
    release = load_public_release_summary(BENCH_ROOT, REPORTS_ROOT)
    if release is None:
        raise RuntimeError("Transactions public release summary is unavailable")
    summary = release["summary"]
    managed_tasks = [str(item) for item in release["managed_tasks"]]
    rows = summary.get("rows")
    release_id = summary.get("release_id")
    if not isinstance(rows, list) or not isinstance(release_id, str):
        raise RuntimeError("Transactions release summary is incomplete")

    tasks = discover_task_definitions(BENCH_ROOT)
    job_sources = discover_job_sources(BENCH_ROOT, REPORTS_ROOT)
    comparison_tasks = [
        ComparisonTask(
            slug=slug,
            label=tasks[slug].name if slug in tasks else display_name(slug),
        )
        for slug in managed_tasks
    ]
    agents: list[ComparisonAgent] = []
    cells: list[ComparisonCell] = []
    attempts: list[ComparisonAttempt] = []
    telemetry: list[ComparisonTelemetryRow] = []
    provenance_sources = [
        "evals/transactions/tooling/public-view.json",
        "evals/transactions/tooling/transactions.summary.json",
    ]

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        job_id = str(row.get("job") or "")
        model = str(row.get("model") or f"Agent {index + 1}")
        agent_id = str(row.get("model_key") or slugify(model))
        source = first_job_source(job_sources, managed_tasks, job_id)
        harness = job_harness(source.raw_dir if source else None)
        agents.append(
            ComparisonAgent(
                id=agent_id,
                label=f"{harness} + {model}" if harness else model,
                model=model,
                harness=harness,
            )
        )
        provenance_sources.append(f"jobs/{job_id}")

        criterion_evaluation = row.get("criterion_evaluation")
        scored = int(row.get("scored") or 0)
        planned = int(row.get("planned") or 0)
        strict = int(row.get("strict_all_pass") or 0)
        cells.append(
            ComparisonCell(
                agent_id=agent_id,
                primary=strict_measure(strict, scored, criterion_evaluation),
                secondary=[coverage_measure(number(row.get("criterion_pass_rate")))],
                counts={
                    "planned": planned,
                    "scored": scored,
                    "strict": strict,
                    "invalid": int(row.get("invalid_output") or 0),
                    "excluded": int(row.get("infrastructure") or 0),
                },
                attempt_values=all_task_values(row.get("tasks")),
                job_id=job_id,
            )
        )

        row_tasks = row.get("tasks")
        for task_slug in managed_tasks:
            task_result = (
                row_tasks.get(task_slug) if isinstance(row_tasks, dict) else None
            )
            if not isinstance(task_result, dict):
                continue
            retained = int(task_result.get("retained") or 0)
            task_strict = int(task_result.get("all_pass") or 0)
            raw_count = len(
                read_harbor_trials(source.raw_dir if source else None, task_slug)
            )
            attempted = max(retained, raw_count)
            semantic = task_result.get("semantic")
            task_coverage = number(
                task_result.get("criterion_pass_rate")
                if task_result.get("criterion_pass_rate") is not None
                else semantic.get("mean")
                if isinstance(semantic, dict)
                else None
            )
            attempt_values = [
                float(value)
                for value in task_result.get("attempt_values", [])
                if isinstance(value, (int, float))
            ]
            cells.append(
                ComparisonCell(
                    agent_id=agent_id,
                    task_slug=task_slug,
                    primary=strict_measure(task_strict, retained, criterion_evaluation),
                    secondary=[coverage_measure(task_coverage)],
                    counts={
                        "planned": attempted,
                        "scored": retained,
                        "strict": task_strict,
                        "invalid": 0,
                        "excluded": max(attempted - retained, 0),
                    },
                    attempt_values=attempt_values,
                    job_id=job_id,
                )
            )

        row_telemetry = row.get("telemetry")
        row_telemetry = row_telemetry if isinstance(row_telemetry, dict) else {}
        telemetry.append(
            ComparisonTelemetryRow(
                agent_id=agent_id,
                values={
                    "agent_time": format_duration(
                        row_telemetry.get("median_agent_seconds")
                    ),
                    "input": format_integer(row_telemetry.get("median_input_tokens")),
                    "cached": format_integer(row_telemetry.get("median_cache_tokens")),
                    "output": format_integer(row_telemetry.get("median_output_tokens")),
                },
            )
        )
        attempts.extend(
            transaction_attempts(
                agent_id=agent_id,
                job_id=job_id,
                source=source,
                task_slugs=managed_tasks,
            )
        )

    return ComparisonPresentation(
        id=release_id,
        label="Transactions",
        description="Five attempts per task across intake, diligence, and contracting.",
        primary_metric=ComparisonMetricDefinition(
            key="strict_all_pass",
            label="Strict all-pass",
            description="Output integrity and every semantic criterion must pass.",
        ),
        secondary_metric=ComparisonMetricDefinition(
            key="criterion_coverage",
            label="Criterion coverage",
            description="Share of semantic criteria passed.",
        ),
        tasks=comparison_tasks,
        agents=agents,
        cells=cells,
        count_columns=[
            ComparisonCountColumn(key="planned", label="Planned"),
            ComparisonCountColumn(key="scored", label="Scored"),
            ComparisonCountColumn(key="strict", label="Strict pass"),
            ComparisonCountColumn(key="invalid", label="Invalid output"),
            ComparisonCountColumn(key="excluded", label="Excluded"),
        ],
        telemetry_columns=default_telemetry_columns(),
        telemetry=telemetry,
        attempts=attempts,
        notes=[
            "Scores come from saved Harbor outputs graded with the final checklist.",
            "Strict all-pass is the release result; criterion coverage explains near misses.",
            "Excluded attempts remain in the denominator and receive no semantic score.",
            "Time and token values are medians for scored attempts.",
        ],
        provenance=ComparisonProvenance(
            generator="transactions.tooling.build-comparison.v1",
            sources=list(dict.fromkeys(provenance_sources)),
        ),
    )


def transaction_attempts(
    *,
    agent_id: str,
    job_id: str,
    source: JobSource | None,
    task_slugs: list[str],
) -> list[ComparisonAttempt]:
    if source is None or source.report_dir is None:
        return []
    analysis = read_object(source.report_dir / "analysis.json")
    if analysis.get("schema_version") != TRANSACTIONS_ADJUDICATION_SCHEMA:
        return []
    model_run = next(
        (
            value
            for value in (analysis.get("models") or {}).values()
            if isinstance(value, dict) and value.get("job") == job_id
        ),
        None,
    )
    if not isinstance(model_run, dict):
        return []

    raw_by_trial = {
        record["trial_id"]: record
        for task_slug in task_slugs
        for record in read_harbor_trials(source.raw_dir, task_slug)
    }
    attempts = []
    retained_ids = set()
    for record in model_run.get("records", []):
        if not isinstance(record, dict):
            continue
        task_slug = str(record.get("task") or "")
        trial_id = str(record.get("trial") or "")
        amended = record.get("amended")
        if task_slug not in task_slugs or not trial_id or not isinstance(amended, dict):
            continue
        retained_ids.add(trial_id)
        semantic = number(amended.get("semantic_score"))
        passed = amended.get("all_pass") == 1
        raw = raw_by_trial.get(trial_id, {})
        attempts.append(
            ComparisonAttempt(
                agent_id=agent_id,
                task_slug=task_slug,
                job_id=job_id,
                trial_id=trial_id,
                status="Strict pass" if passed else "Criteria missing",
                tone="good" if passed else "warn",
                primary="Pass" if passed else "Did not pass",
                secondary=f"{100 * semantic:.1f}%" if semantic is not None else "—",
                duration_seconds=number(record.get("duration_seconds"))
                or raw.get("duration"),
                input_tokens=nested_int(record, "tokens", "input")
                or raw.get("input_tokens"),
                output_tokens=nested_int(record, "tokens", "output")
                or raw.get("output_tokens"),
            )
        )
    for trial_id, raw in raw_by_trial.items():
        if trial_id in retained_ids:
            continue
        attempts.append(
            ComparisonAttempt(
                agent_id=agent_id,
                task_slug=raw["task_slug"],
                job_id=job_id,
                trial_id=trial_id,
                status="Excluded",
                primary="—",
                secondary="—",
                duration_seconds=raw.get("duration"),
                input_tokens=raw.get("input_tokens"),
                output_tokens=raw.get("output_tokens"),
            )
        )
    return sorted(attempts, key=lambda item: (item.task_slug, item.trial_id))


def first_job_source(
    job_sources: dict[str, dict[str, JobSource]], task_slugs: list[str], job_id: str
) -> JobSource | None:
    return next(
        (
            job_sources[task_slug][job_id]
            for task_slug in task_slugs
            if job_id in job_sources.get(task_slug, {})
        ),
        None,
    )


def job_harness(job_dir: Path | None) -> str:
    if job_dir is None:
        return ""
    lock = read_object(job_dir / "lock.json")
    harnesses = {
        agent_display(trial.get("agent") if isinstance(trial, dict) else {})
        for trial in lock.get("trials", [])
        if isinstance(trial, dict)
    }
    harnesses.discard("—")
    return next(iter(harnesses)) if len(harnesses) == 1 else ""


def strict_measure(passed: int, scored: int, evaluation: Any) -> ComparisonMeasure:
    if evaluation == "not_run_output_gate":
        return ComparisonMeasure(
            label="strict all-pass", value="Not judged", detail="output gate"
        )
    return ComparisonMeasure(
        label="strict passes",
        value=f"{passed}/{scored}",
        raw=passed / scored if scored else None,
        tone="good" if passed else "neutral",
    )


def coverage_measure(value: float | None) -> ComparisonMeasure:
    return ComparisonMeasure(
        label="criterion coverage",
        value=f"{100 * value:.1f}%" if value is not None else "—",
        raw=value,
    )


def all_task_values(value: Any) -> list[float]:
    if not isinstance(value, dict):
        return []
    return [
        float(item)
        for task in value.values()
        if isinstance(task, dict)
        for item in task.get("attempt_values", [])
        if isinstance(item, (int, float))
    ]


def nested_int(value: dict[str, Any], outer: str, key: str) -> int | None:
    nested = value.get(outer)
    item = nested.get(key) if isinstance(nested, dict) else None
    return int(item) if isinstance(item, (int, float)) else None


def number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def display_name(value: str) -> str:
    return value.replace("-", " ").title()


def main() -> int:
    parser = argparse.ArgumentParser(prog="build-transactions-comparison")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    write_comparison(args.output, build_comparison())
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
