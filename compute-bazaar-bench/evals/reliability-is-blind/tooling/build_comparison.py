"""Build the normalized Reliability Is Blind comparison artifact."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from statistics import median
import sys
from typing import Any


BENCH_ROOT = Path(__file__).resolve().parents[3]
if str(BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCH_ROOT))

from viewer.comparisons import (  # noqa: E402
    default_telemetry_columns,
    format_duration,
    format_integer,
    read_object,
    slugify,
    write_comparison,
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


DEFAULT_REPORT = (
    BENCH_ROOT / "jobs/reports/reliability-is-blind/runs/"
    "reliability-is-blind-mistral-matched-20"
)
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent / "comparisons/mistral-matched-20.comparison.json"
)
MODEL_LABELS = {
    "mistral/mistral-medium-3-5": "Mistral Medium 3.5",
    "mistral/mistral-small-2603": "Mistral Small 2603",
    "mistral/mistral-large-2512": "Mistral Large 2512",
}


def build_comparison(report_dir: Path = DEFAULT_REPORT) -> ComparisonPresentation:
    protocol = read_object(report_dir / "protocol.json")
    trials = read_list(report_dir / "trials.json")
    model_rows = protocol.get("models")
    if not isinstance(model_rows, list):
        raise RuntimeError(f"Reliability report has no model rows: {report_dir}")

    trials_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in trials:
        trial = record.get("trial")
        if isinstance(trial, dict) and isinstance(trial.get("model"), str):
            trials_by_model[trial["model"]].append(record)

    agents: list[ComparisonAgent] = []
    cells: list[ComparisonCell] = []
    telemetry: list[ComparisonTelemetryRow] = []
    attempts: list[ComparisonAttempt] = []

    for row in model_rows:
        if not isinstance(row, dict) or not isinstance(row.get("model"), str):
            continue
        model = row["model"]
        model_trials = trials_by_model.get(model, [])
        agent_id = slugify(model)
        harness = harness_label(model_trials)
        label = MODEL_LABELS.get(model, model.rsplit("/", 1)[-1])
        agents.append(
            ComparisonAgent(
                id=agent_id,
                label=f"{harness} + {label}" if harness else label,
                model=model,
                harness=harness,
            )
        )

        planned = int(row.get("planned_trials") or 0)
        observed = int(row.get("observed_trials") or 0)
        completed = int(row.get("completed_rollouts") or 0)
        target_met = int(row.get("reliability_targets_met") or 0)
        activated = int(row.get("attribution_challenges_activated") or 0)
        failure_rate = number(row.get("mean_completed_failure_rate"))
        mean_reward = number(row.get("mean_reward"))
        cells.append(
            ComparisonCell(
                agent_id=agent_id,
                task_slug="reliability-is-blind",
                primary=ComparisonMeasure(
                    label="books meeting target",
                    value=f"{target_met}/{observed}",
                    raw=target_met / observed if observed else None,
                    tone="good" if target_met else "neutral",
                ),
                secondary=[
                    ComparisonMeasure(
                        label="completed",
                        value=f"{completed}/{observed}",
                        raw=completed / observed if observed else None,
                    ),
                    ComparisonMeasure(
                        label="failure rate",
                        value=(
                            f"{100 * failure_rate:.1f}%"
                            if failure_rate is not None
                            else "—"
                        ),
                        raw=failure_rate,
                    ),
                    ComparisonMeasure(
                        label="mean reward",
                        value=f"{mean_reward:.3f}" if mean_reward is not None else "—",
                        raw=mean_reward,
                    ),
                ],
                counts={
                    "planned": planned,
                    "observed": observed,
                    "completed": completed,
                    "target": target_met,
                    "activated": activated,
                    "not_completed": max(observed - completed, 0),
                },
                attempt_values=completed_failure_rates(model_trials),
                job_id=report_dir.name,
            )
        )
        telemetry.append(telemetry_row(agent_id, model_trials))
        attempts.extend(attempt_rows(agent_id, model_trials))

    return ComparisonPresentation(
        id="mistral-matched-20",
        label="Mistral matched 20",
        description="Twenty matched market seeds per agent across 100-deal books.",
        primary_metric=ComparisonMetricDefinition(
            key="reliability_target",
            label="Reliability target met",
            description="Completed books with no more than 5% failed deliveries.",
        ),
        secondary_metric=ComparisonMetricDefinition(
            key="failure_rate",
            label="Failure rate",
            description="Mean failed-delivery rate across completed books.",
            higher_is_better=False,
        ),
        tasks=[
            ComparisonTask(slug="reliability-is-blind", label="Reliability Is Blind")
        ],
        agents=agents,
        cells=cells,
        count_columns=[
            ComparisonCountColumn(key="planned", label="Planned"),
            ComparisonCountColumn(key="observed", label="Observed"),
            ComparisonCountColumn(key="completed", label="Completed"),
            ComparisonCountColumn(key="target", label="Target met"),
            ComparisonCountColumn(key="activated", label="Attribution activated"),
            ComparisonCountColumn(key="not_completed", label="Did not complete"),
        ],
        telemetry_columns=default_telemetry_columns(),
        telemetry=telemetry,
        attempts=sorted(attempts, key=lambda item: (item.trial_id, item.agent_id)),
        notes=[
            "Scores come from the matched-seed Harbor run.",
            "The primary denominator is every observed book, including books that did not finish.",
            "Failure rate is calculated only across completed books.",
            "Time and token values are medians across observed attempts.",
        ],
        provenance=ComparisonProvenance(
            generator="reliability-is-blind.tooling.build-comparison.v1",
            sources=[
                relative(report_dir / "protocol.json"),
                relative(report_dir / "trials.json"),
                "evals/reliability-is-blind/tooling/protocols/"
                "reliability-is-blind-mistral-matched-20.commitment.json",
            ],
        ),
    )


def harness_label(records: list[dict[str, Any]]) -> str:
    labels = {
        " ".join(
            part
            for part in (
                str(trial.get("agent") or "").replace("opencode", "OpenCode"),
                str(trial.get("agent_version") or ""),
            )
            if part
        )
        for record in records
        if isinstance((trial := record.get("trial")), dict)
    }
    labels.discard("")
    return next(iter(labels)) if len(labels) == 1 else ""


def telemetry_row(
    agent_id: str, records: list[dict[str, Any]]
) -> ComparisonTelemetryRow:
    return ComparisonTelemetryRow(
        agent_id=agent_id,
        values={
            "agent_time": format_duration(
                median_field(records, "trial", "agent_execution_seconds")
            ),
            "input": format_integer(median_field(records, "trial", "tokens", "input")),
            "cached": format_integer(
                median_field(records, "trial", "tokens", "cached_input")
            ),
            "output": format_integer(
                median_field(records, "trial", "tokens", "output")
            ),
        },
    )


def attempt_rows(
    agent_id: str, records: list[dict[str, Any]]
) -> list[ComparisonAttempt]:
    rows = []
    for record in records:
        trial = record.get("trial")
        result = record.get("result")
        if not isinstance(trial, dict) or not isinstance(result, dict):
            continue
        completed = trial.get("completion") == 1
        target_met = completed and result.get("reliability_target_met") == 1
        status = (
            "Target met"
            if target_met
            else "Target missed"
            if completed
            else "Did not complete"
        )
        trial_path = Path(str(trial.get("path") or ""))
        job_id = trial_path.parent.name if trial_path.name else ""
        failure_rate = number(result.get("failure_rate"))
        tokens = trial.get("tokens")
        tokens = tokens if isinstance(tokens, dict) else {}
        rows.append(
            ComparisonAttempt(
                agent_id=agent_id,
                task_slug="reliability-is-blind",
                job_id=job_id,
                trial_id=str(trial.get("name") or ""),
                status=status,
                tone="good" if target_met else "warn" if completed else "neutral",
                primary="Met" if target_met else "Missed" if completed else "—",
                secondary=(
                    f"{100 * failure_rate:.1f}%" if failure_rate is not None else "—"
                ),
                duration_seconds=number(trial.get("agent_execution_seconds")),
                input_tokens=integer(tokens.get("input")),
                output_tokens=integer(tokens.get("output")),
            )
        )
    return rows


def completed_failure_rates(records: list[dict[str, Any]]) -> list[float]:
    values = []
    for record in records:
        trial = record.get("trial")
        result = record.get("result")
        if (
            isinstance(trial, dict)
            and trial.get("completion") == 1
            and isinstance(result, dict)
            and isinstance(result.get("failure_rate"), (int, float))
        ):
            values.append(float(result["failure_rate"]))
    return values


def median_field(records: list[dict[str, Any]], *keys: str) -> float | None:
    values = []
    for record in records:
        value: Any = record
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, (int, float)):
            values.append(float(value))
    return median(values) if values else None


def read_list(path: Path) -> list[dict[str, Any]]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise RuntimeError(f"expected a list: {path}")
    return [item for item in value if isinstance(item, dict)]


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(BENCH_ROOT))
    except ValueError:
        return str(path)


def number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def integer(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def main() -> int:
    parser = argparse.ArgumentParser(prog="build-reliability-comparison")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    write_comparison(args.output, build_comparison(args.report))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
