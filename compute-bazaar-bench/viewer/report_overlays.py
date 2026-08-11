"""Add reviewed, task-specific analysis to a raw Harbor presentation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .job_sources import (
    TRANSACTIONS_ADJUDICATION_SCHEMA,
    TRANSACTIONS_COMPARISON_SCHEMA,
    TRANSACTIONS_SCHEMA,
)
from .schema import (
    DataTable,
    DetailSection,
    JobPresentation,
    Metric,
    Notice,
    TableCell,
    TableColumn,
    TableRow,
)


def apply_report_overlay(
    presentation: JobPresentation,
    report_dir: Path | None,
    task_slug: str,
    *,
    public_context: dict[str, Any] | None = None,
) -> JobPresentation:
    """Return the raw presentation enriched by a supported report."""
    if report_dir is None:
        return _with_public_execution_origin(presentation, public_context)
    analysis = _read_json(report_dir / "analysis.json")
    if not isinstance(analysis, dict):
        return _with_public_execution_origin(presentation, public_context)
    if analysis.get("schema_version") == TRANSACTIONS_SCHEMA:
        enriched = _transactions(presentation, analysis, task_slug)
        return _with_public_execution_origin(enriched, public_context)
    if analysis.get("schema_version") == TRANSACTIONS_COMPARISON_SCHEMA:
        enriched = _transactions_comparison(presentation, analysis, task_slug)
        return _with_public_execution_origin(enriched, public_context)
    if analysis.get("schema_version") == TRANSACTIONS_ADJUDICATION_SCHEMA:
        return _transactions_adjudication(
            presentation,
            analysis,
            task_slug,
            public_context=public_context,
        )
    return _with_public_execution_origin(presentation, public_context)


def _transactions_adjudication(
    base: JobPresentation,
    analysis: dict[str, Any],
    task_slug: str,
    *,
    public_context: dict[str, Any] | None = None,
) -> JobPresentation:
    model_run = next(
        (
            run
            for run in (analysis.get("models") or {}).values()
            if isinstance(run, dict) and run.get("job") == base.job_id
        ),
        None,
    )
    if model_run is None:
        return base
    original_task = (model_run.get("original") or {}).get("tasks", {}).get(task_slug)
    amended_task = (model_run.get("amended") or {}).get("tasks", {}).get(task_slug)
    if not isinstance(original_task, dict) or not isinstance(amended_task, dict):
        return base
    records = [
        record
        for record in model_run.get("records") or []
        if isinstance(record, dict) and record.get("task") == task_slug
    ]
    visual_summary = {"good": 0, "mixed": 0, "poor": 0}
    adapted_records = []
    for record in records:
        review = record.get("visual_review") or {}
        rating = review.get("practical_usability")
        if rating in visual_summary:
            visual_summary[str(rating)] += 1
        amended = record["amended"]
        adapted_records.append(
            {
                "trial": record["trial"],
                "task": record["task"],
                "semantic_score": amended["semantic_score"],
                "semantic_passes": amended["semantic_passes"],
                "semantic_criteria": amended["semantic_criteria"],
                "harbor_reward": amended["reward"],
                "all_pass": amended["all_pass"],
                "infrastructure_error": None,
                "duration_seconds": record.get("duration_seconds"),
                "tokens": record.get("tokens"),
                "criteria": amended["criteria"],
                "trajectory": record.get("trajectory") or {},
                "visual_review": review,
            }
        )
    retained = int(amended_task.get("retained", len(records)))
    adapted = {
        "summary": {
            "tasks": {
                task_slug: {
                    "attempted": base.trial_count,
                    "retained": retained,
                    "infrastructure_errors": max(base.trial_count - retained, 0),
                    "valid_docx": retained,
                    "all_pass": amended_task.get("all_pass", 0),
                    "semantic": amended_task.get("semantic") or {},
                    "harbor_reward": amended_task.get("reward") or {},
                }
            }
        },
        "visual_summary": {task_slug: visual_summary},
        "trials": adapted_records,
    }
    presentation = _transactions(base, adapted, task_slug)
    if (public_context or {}).get("execution_origin") == (
        "original_harbor_output_final_checklist"
    ):
        return _public_preserved_adjudication(
            presentation,
            amended_task=amended_task,
            records=records,
            retained=retained,
            public_context=public_context or {},
        )
    records_by_trial = {str(record["trial"]): record for record in records}

    trial_rows = []
    for row in presentation.trial_table.rows:
        trial_id = _cell(row, "trial")
        record = records_by_trial.get(trial_id)
        if record is None:
            trial_rows.append(
                TableRow(
                    search=row.search,
                    cells={
                        "trial": row.cells.get("trial", TableCell(value="—")),
                        "status": row.cells.get("status", TableCell(value="—")),
                        "v1_semantic": TableCell(value="—"),
                        "v2_semantic": TableCell(value="—"),
                        "delta": TableCell(value="—"),
                        "v2_criteria": TableCell(value="—"),
                        "v1_all_pass": TableCell(value="—"),
                        "v2_all_pass": TableCell(value="—"),
                        "craft": TableCell(value="—"),
                        "pages": TableCell(value="—"),
                        "duration": row.cells.get("duration", TableCell(value="—")),
                    },
                )
            )
            continue
        original = record["original"]
        amended = record["amended"]
        review = record.get("visual_review") or {}
        trial_rows.append(
            TableRow(
                search=row.search,
                cells={
                    "trial": row.cells["trial"],
                    "status": row.cells["status"],
                    "v1_semantic": TableCell(
                        value=_number(original.get("semantic_score"), 4)
                    ),
                    "v2_semantic": TableCell(
                        value=_number(amended.get("semantic_score"), 4)
                    ),
                    "delta": TableCell(value=_signed(record.get("semantic_delta"))),
                    "v2_criteria": TableCell(
                        value=_fraction(
                            amended.get("semantic_passes"),
                            amended.get("semantic_criteria"),
                        )
                    ),
                    "v1_all_pass": TableCell(
                        value=_yes_no(original.get("all_pass"))
                    ),
                    "v2_all_pass": TableCell(
                        value=_yes_no(amended.get("all_pass")),
                        tone="good" if amended.get("all_pass") == 1 else "neutral",
                    ),
                    "craft": TableCell(
                        value=str(review.get("practical_usability") or "—"),
                        tone=_craft_tone(review.get("practical_usability")),
                    ),
                    "pages": TableCell(value=str(review.get("page_count") or "—")),
                    "duration": row.cells["duration"],
                },
            )
        )

    trial_details = dict(presentation.trials)
    for trial_id, record in records_by_trial.items():
        detail = trial_details.get(trial_id)
        if detail is None:
            continue
        original = record["original"]
        amended = record["amended"]
        summary = [
            Metric(
                label=(
                    "Original Harbor reward"
                    if metric.label in {"Reward", "Mean reward", "Score"}
                    else "Amended semantic"
                    if metric.label == "Semantic score"
                    else "Amended criteria"
                    if metric.label == "Criteria"
                    else "Amended all pass"
                    if metric.label == "All pass"
                    else metric.label
                ),
                value=metric.value,
                hint=metric.hint,
                tone=metric.tone,
            )
            for metric in detail.summary
        ]
        summary.extend(
            [
                Metric(
                    label="Original semantic",
                    value=_number(original.get("semantic_score"), 4),
                ),
                Metric(
                    label="Original all pass", value=_yes_no(original.get("all_pass"))
                ),
            ]
        )
        sections = [
            *[
                section.model_copy(update={"title": "Original Harbor rewards"})
                if section.title == "Rewards"
                else section
                for section in detail.sections
            ],
            DetailSection(
                title="Adjudication replay",
                data={
                    "original_label": analysis.get("labels", {}).get("original"),
                    "amended_label": analysis.get("labels", {}).get("amended"),
                    "agent_rerun": False,
                    "artifact_sha256": record.get("artifact_sha256"),
                    "original": {
                        "semantic_score": original.get("semantic_score"),
                        "reward": original.get("reward"),
                        "all_pass": original.get("all_pass"),
                    },
                    "amended": {
                        "semantic_score": amended.get("semantic_score"),
                        "reward": amended.get("reward"),
                        "all_pass": amended.get("all_pass"),
                    },
                    "criterion_transitions": record.get("criterion_transitions"),
                    "changed_criteria": record.get("changed_criteria"),
                },
            ),
        ]
        trial_details[trial_id] = detail.model_copy(
            update={"summary": summary, "sections": sections}
        )

    original_semantic = (original_task.get("semantic") or {}).get("mean")
    amended_semantic = (amended_task.get("semantic") or {}).get("mean")
    reviewed = sum(visual_summary.values())
    return presentation.model_copy(
        update={
            "primary_score": Metric(
                label="Amended all pass",
                value=f"{amended_task.get('all_pass', 0)}/{retained}",
                hint="Harvey-style strict all-pass under verifier v2 replay",
                tone="good" if amended_task.get("all_pass") else "neutral",
            ),
            "metrics": [
                Metric(label="Retained outputs", value=f"{retained}/{base.trial_count}"),
                Metric(
                    label="Original all pass",
                    value=f"{original_task.get('all_pass', 0)}/{retained}",
                ),
                Metric(
                    label="Amended criterion pass",
                    value=_number(amended_semantic, 4),
                ),
                Metric(
                    label="Original criterion pass",
                    value=_number(original_semantic, 4),
                ),
                Metric(
                    label=f"Document craft / {reviewed} reviewed",
                    value=(
                        f"{visual_summary['good']} good · "
                        f"{visual_summary['mixed']} mixed · "
                        f"{visual_summary['poor']} poor"
                    ),
                    hint="Unchanged blind review of the preserved DOCX artifacts",
                ),
                Metric(
                    label="Original infrastructure exclusions",
                    value=str(max(base.trial_count - retained, 0)),
                ),
            ],
            "notices": [
                Notice(
                    text=(
                        "Amended adjudication replays verifier v2 over preserved "
                        "outputs. No agent was rerun and the original Harbor score "
                        "remains unchanged."
                    ),
                    tone="info",
                ),
                *presentation.notices,
            ],
            "agent_table": DataTable(
                title="Agents",
                description="Original and amended grading of the same retained outputs.",
                columns=[
                    TableColumn(key="agent", label="Agent"),
                    TableColumn(key="model", label="Model"),
                    TableColumn(key="retained", label="Retained", align="right"),
                    TableColumn(key="v1", label="v1 semantic", align="right"),
                    TableColumn(key="v2", label="v2 semantic", align="right"),
                    TableColumn(key="v1_pass", label="v1 all pass", align="right"),
                    TableColumn(key="v2_pass", label="v2 all pass", align="right"),
                    TableColumn(key="input", label="Input tokens", align="right"),
                    TableColumn(key="output", label="Output tokens", align="right"),
                    TableColumn(key="cost", label="Reported cost", align="right"),
                ],
                rows=[
                    TableRow(
                        cells={
                            "agent": presentation.agent_table.rows[0].cells["agent"],
                            "model": presentation.agent_table.rows[0].cells["model"],
                            "retained": TableCell(value=str(retained)),
                            "v1": TableCell(value=_number(original_semantic, 4)),
                            "v2": TableCell(value=_number(amended_semantic, 4)),
                            "v1_pass": TableCell(
                                value=f"{original_task.get('all_pass', 0)}/{retained}"
                            ),
                            "v2_pass": TableCell(
                                value=f"{amended_task.get('all_pass', 0)}/{retained}"
                            ),
                            "input": presentation.agent_table.rows[0].cells["input"],
                            "output": presentation.agent_table.rows[0].cells["output"],
                            "cost": presentation.agent_table.rows[0].cells["cost"],
                        }
                    )
                ],
            ),
            "trial_table": DataTable(
                title="Trials",
                description="Original verifier v1 beside amended verifier v2 on the same DOCX.",
                searchable=True,
                columns=[
                    TableColumn(key="trial", label="Trial"),
                    TableColumn(key="status", label="Status"),
                    TableColumn(key="v1_semantic", label="v1 semantic", align="right"),
                    TableColumn(key="v2_semantic", label="v2 semantic", align="right"),
                    TableColumn(key="delta", label="Delta", align="right"),
                    TableColumn(key="v2_criteria", label="v2 criteria", align="right"),
                    TableColumn(key="v1_all_pass", label="v1 all pass", align="right"),
                    TableColumn(key="v2_all_pass", label="v2 all pass", align="right"),
                    TableColumn(key="craft", label="Document craft"),
                    TableColumn(key="pages", label="Pages", align="right"),
                    TableColumn(key="duration", label="Duration", align="right"),
                ],
                rows=trial_rows,
            ),
            "trials": trial_details,
        }
    )


def _public_preserved_adjudication(
    presentation: JobPresentation,
    *,
    amended_task: dict[str, Any],
    records: list[dict[str, Any]],
    retained: int,
    public_context: dict[str, Any],
) -> JobPresentation:
    """Present final-rubric results for the original agent outputs."""
    records_by_trial = {str(record["trial"]): record for record in records}
    trial_details = {}
    for trial_id, detail in presentation.trials.items():
        record = records_by_trial.get(trial_id)
        amended = (record or {}).get("amended") or {}
        summary = []
        for metric in detail.summary:
            if metric.label.lower() in {
                "reward",
                "mean reward",
                "score",
                "reported cost",
                "cost",
            }:
                continue
            label = {
                "Semantic score": "Criterion pass rate",
                "Criteria": "Criteria",
                "All pass": "Passed",
                "Document craft": "Document review",
            }.get(metric.label, metric.label)
            value = metric.value
            if metric.label == "Semantic score" and isinstance(
                amended.get("semantic_score"), (int, float)
            ):
                value = f"{100 * float(amended['semantic_score']):.1f}%"
            summary.append(metric.model_copy(update={"label": label, "value": value}))
        summary.append(
            Metric(
                label="Reward",
                value=_number(amended.get("reward"), 4),
            )
        )
        sections = [section for section in detail.sections if section.title != "Rewards"]
        trial_details[trial_id] = detail.model_copy(
            update={"summary": summary, "sections": sections}
        )

    semantic = amended_task.get("semantic") or {}
    semantic_mean = semantic.get("mean") if isinstance(semantic, dict) else None
    criteria_passed = (
        f"{100 * float(semantic_mean):.1f}%"
        if isinstance(semantic_mean, (int, float))
        else "—"
    )

    agent_rows = []
    for row in presentation.agent_table.rows:
        cells = dict(row.cells)
        cells["semantic"] = TableCell(value=criteria_passed)
        agent_rows.append(row.model_copy(update={"cells": cells}))
    agent_columns = [
        TableColumn(key="agent", label="Agent"),
        TableColumn(key="model", label="Model"),
        TableColumn(key="valid", label="Valid documents", align="right"),
        TableColumn(key="semantic", label="Criterion pass rate", align="right"),
        TableColumn(key="all_pass", label="Runs passed", align="right"),
        TableColumn(key="input", label="Input tokens", align="right"),
        TableColumn(key="output", label="Output tokens", align="right"),
    ]

    trial_labels = {
        "semantic": "Criterion pass rate",
        "criteria": "Criteria",
        "reward": "Reward",
        "all_pass": "Passed",
        "craft": "Document review",
    }
    trial_columns = [
        column.model_copy(update={"label": trial_labels.get(column.key, column.label)})
        for column in presentation.trial_table.columns
    ]
    trial_rows = []
    for row in presentation.trial_table.rows:
        cells = dict(row.cells)
        trial_id = _cell(row, "trial")
        amended = (records_by_trial.get(trial_id) or {}).get("amended") or {}
        semantic_score = amended.get("semantic_score")
        if isinstance(semantic_score, (int, float)):
            cells["semantic"] = TableCell(
                value=f"{100 * float(semantic_score):.1f}%"
            )
        trial_rows.append(row.model_copy(update={"cells": cells}))
    metric_by_label = {metric.label: metric for metric in presentation.metrics}
    metrics = [
        Metric(
            label="Criterion pass rate",
            value=criteria_passed,
            hint="Average share of binary rubric criteria passed",
        ),
        Metric(
            label="Valid documents",
            value=metric_by_label.get(
                "Valid DOCX / retained", Metric(label="", value="—")
            ).value,
        ),
        Metric(
            label="Document review",
            value=metric_by_label.get(
                f"Document craft / {retained} reviewed", Metric(label="", value="—")
            ).value,
        ),
    ]
    excluded = metric_by_label.get(
        "Excluded trials", Metric(label="", value="0")
    ).value
    if excluded != "0":
        metrics.append(Metric(label="Excluded", value=excluded))
    return presentation.model_copy(
        update={
            "primary_score": Metric(
                label="Runs passed",
                value=f"{amended_task.get('all_pass', 0)}/{retained}",
                hint="Runs in which every rubric criterion passed",
                tone="good" if amended_task.get("all_pass") else "neutral",
            ),
            "metrics": metrics,
            "notices": [
                Notice(
                    text=(
                        "This score applies the final rubric to the original "
                        "DOCX. The agent was not rerun."
                    ),
                    tone="info",
                ),
                *presentation.notices,
            ],
            "agent_table": presentation.agent_table.model_copy(
                update={
                    "description": (
                        "Final rubric results on the original agent output."
                    ),
                    "columns": agent_columns,
                    "rows": agent_rows,
                }
            ),
            "trial_table": presentation.trial_table.model_copy(
                update={
                    "description": "Final rubric results for each original DOCX.",
                    "columns": trial_columns,
                    "rows": trial_rows,
                }
            ),
            "trials": _sanitize_public_trials(trial_details),
        }
    )


def _with_public_execution_origin(
    presentation: JobPresentation, public_context: dict[str, Any] | None
) -> JobPresentation:
    if not public_context:
        return presentation
    display_origin = str(
        public_context.get("display_label") or "Fresh native Harbor run"
    )
    agent_rows = []
    for row in presentation.agent_table.rows:
        cells = dict(row.cells)
        cells["origin"] = TableCell(value=display_origin)
        agent_rows.append(row.model_copy(update={"cells": cells}))
    columns = list(presentation.agent_table.columns)
    columns.insert(2, TableColumn(key="origin", label="Execution origin"))
    all_pass = next(
        (metric for metric in presentation.metrics if metric.label == "All pass / retained"),
        None,
    )
    primary_score = presentation.primary_score
    metrics = [Metric(label="Execution origin", value=display_origin)]
    if all_pass is not None:
        criterion_not_judged = (
            presentation.primary_score is not None
            and presentation.primary_score.value == "not judged"
        )
        primary_score = Metric(
            label="Strict all-pass",
            value=all_pass.value,
            hint="Attempts that passed every required check",
            tone="good" if not all_pass.value.startswith("0/") else "neutral",
        )
        metrics.append(
            Metric(
                label="Criterion pass",
                value=(
                    presentation.primary_score.value
                    if presentation.primary_score is not None
                    else "—"
                ),
                hint=(
                    "No usable document reached checklist review"
                    if criterion_not_judged
                    else "Mean share of individual checks passed"
                ),
            )
        )
    metrics.extend(presentation.metrics)
    return presentation.model_copy(
        update={
            "primary_score": primary_score,
            "metrics": metrics,
            "notices": [
                Notice(
                    text=(
                        "This row comes from a fresh native Harbor run on the "
                        "frozen release grader."
                    ),
                    tone="info",
                ),
                *presentation.notices,
            ],
            "agent_table": presentation.agent_table.model_copy(
                update={"columns": columns, "rows": agent_rows}
            ),
            "trials": _sanitize_public_trials(presentation.trials),
        }
    )


def _transactions_comparison(
    base: JobPresentation, analysis: dict[str, Any], task_slug: str
) -> JobPresentation:
    model_run = next(
        (
            run
            for run in (analysis.get("models") or {}).values()
            if isinstance(run, dict) and run.get("job") == base.job_id
        ),
        None,
    )
    if model_run is None:
        return base
    if model_run.get("status") == "official_invalidated":
        return _invalidated_comparison(base, model_run)
    if not isinstance(model_run.get("summary"), dict):
        return base
    visual_summary: dict[str, dict[str, int]] = {}
    for record in model_run.get("records") or []:
        if not isinstance(record, dict):
            continue
        review = record.get("visual_review") or {}
        rating = review.get("practical_usability")
        task = record.get("task")
        if task and rating in {"good", "mixed", "poor"}:
            task_counts = visual_summary.setdefault(
                str(task), {"good": 0, "mixed": 0, "poor": 0}
            )
            task_counts[str(rating)] += 1
    adapted = {
        "summary": model_run["summary"],
        "visual_summary": visual_summary,
        "trials": model_run.get("records") or [],
    }
    return _transactions(base, adapted, task_slug)


def _invalidated_comparison(
    base: JobPresentation, model_run: dict[str, Any]
) -> JobPresentation:
    reason = str(
        model_run.get("exclusion_reason")
        or "This complete job was excluded from the scored comparison."
    )
    metrics = [
        metric.model_copy(
            update={"label": "Terminal trials" if metric.label == "Trials" else metric.label}
        )
        for metric in base.metrics
        if "reward" not in metric.label.lower() and "score" not in metric.label.lower()
    ]
    metrics.insert(1, Metric(label="Scored trials", value="0"))
    return base.model_copy(
        update={
            "primary_score": Metric(
                label="Comparison status",
                value="Unscored",
                hint="This job is preserved for audit but excluded from comparison results",
                tone="bad",
            ),
            "metrics": metrics,
            "notices": [
                Notice(
                    text=f"Excluded from the scored comparison. {reason}",
                    tone="bad",
                ),
                *base.notices,
            ],
            "agent_table": _unscored_table(
                base.agent_table,
                description=(
                    "Resolved harness, model, usage, and execution status from Harbor. "
                    "This invalidated job has no comparison score."
                ),
            ),
            "trial_table": _unscored_table(
                base.trial_table,
                description=(
                    "Raw Harbor trials preserved for audit. This invalidated job is "
                    "unscored."
                ),
            ),
            "trials": {
                trial_id: _unscored_trial(trial, reason)
                for trial_id, trial in base.trials.items()
            },
        }
    )


def _transactions(
    base: JobPresentation, analysis: dict[str, Any], task_slug: str
) -> JobPresentation:
    task_summary = (analysis.get("summary", {}).get("tasks", {}) or {}).get(task_slug)
    if not isinstance(task_summary, dict):
        return base
    records = [
        record
        for record in analysis.get("trials", [])
        if isinstance(record, dict) and record.get("task") == task_slug
    ]
    if not records:
        return base

    visual = (analysis.get("visual_summary") or {}).get(task_slug) or {}
    attempted = int(task_summary.get("attempted", base.trial_count))
    retained = int(task_summary.get("retained", 0))
    invalid_outputs = sum(bool(record.get("agent_invalid_output")) for record in records)
    output_gate_only = (
        retained > 0
        and int(task_summary.get("valid_docx", 0)) == 0
        and invalid_outputs == retained
    )
    semantic = task_summary.get("semantic") or {}
    harbor_reward = task_summary.get("harbor_reward") or {}
    good = int(visual.get("good", 0))
    mixed = int(visual.get("mixed", 0))
    poor = int(visual.get("poor", 0))

    agent_row = base.agent_table.rows[0] if base.agent_table.rows else None
    agent_value = _cell(agent_row, "agent")
    model_value = _cell(agent_row, "model")
    input_tokens = _cell(agent_row, "input")
    output_tokens = _cell(agent_row, "output")
    cost = _cell(agent_row, "cost")

    records_by_trial = {str(record["trial"]): record for record in records}
    trial_rows = []
    trial_details = dict(base.trials)
    for raw_row in base.trial_table.rows:
        trial_id = _cell(raw_row, "trial")
        record = records_by_trial.get(trial_id)
        if record is None:
            trial_rows.append(_unanalyzed_trial_row(raw_row))
            continue
        review = record.get("visual_review") or {}
        infra = record.get("infrastructure_error")
        invalid_output = bool(record.get("agent_invalid_output"))
        status = (
            "timeout excluded"
            if _is_agent_timeout(infra)
            else "error"
            if infra
            else "invalid output"
            if invalid_output
            else _cell(raw_row, "status")
        )
        trial_rows.append(
            TableRow(
                search=(
                    f"{trial_id} {status} {record.get('invalid_output_reason', '')} "
                    f"{review.get('practical_usability', '')}"
                ).lower(),
                cells={
                    "trial": TableCell(value=trial_id, href=trial_id),
                    "status": TableCell(
                        value=status,
                        tone="bad" if infra or invalid_output else "good",
                    ),
                    "semantic": TableCell(
                        value=(
                            "not judged"
                            if invalid_output
                            else _number(record.get("semantic_score"), 4)
                        )
                    ),
                    "criteria": TableCell(
                        value=(
                            "not judged"
                            if invalid_output
                            else _fraction(
                                record.get("semantic_passes"),
                                record.get("semantic_criteria"),
                            )
                        )
                    ),
                    "reward": TableCell(value=_number(record.get("harbor_reward"), 4)),
                    "all_pass": TableCell(
                        value=_yes_no(record.get("all_pass"))
                    ),
                    "craft": TableCell(
                        value=str(review.get("practical_usability") or "—"),
                        tone=_craft_tone(review.get("practical_usability")),
                    ),
                    "pages": TableCell(value=str(review.get("page_count") or "—")),
                    "duration": TableCell(
                        value=(
                            _duration(record.get("duration_seconds"))
                            if record.get("duration_seconds") is not None
                            else _cell(raw_row, "duration")
                        )
                    ),
                },
            )
        )
        detail = trial_details.get(trial_id)
        if detail is not None:
            sections = [
                DetailSection(
                    title=(
                        "Timeout exclusion"
                        if _is_agent_timeout(infra)
                        else "Run exclusion"
                    ),
                    data={
                        "status": "excluded under the frozen scoring rule",
                        "classification": (
                            "one-hour agent timeout"
                            if _is_agent_timeout(infra)
                            else "runtime or provider failure"
                        ),
                        "cause": (
                            "not determined"
                            if _is_agent_timeout(infra)
                            else "recorded by Harbor"
                        ),
                    },
                )
                if infra and section.title == "Rewards"
                else section
                for section in detail.sections
            ]
            sections.extend(
                [
                    *(
                        [
                            DetailSection(
                                title="Output failure",
                                data={
                                    "classification": "model output failure",
                                    "reason": record.get("invalid_output_reason"),
                                    "checklist_review": "not run",
                                },
                            )
                        ]
                        if invalid_output
                        else []
                    ),
                    DetailSection(
                        title="Checklist criteria",
                        data=record.get("criteria") or [],
                    ),
                    DetailSection(title="Document review", data=review),
                    DetailSection(
                        title="Execution observations",
                        data=record.get("trajectory") or {},
                    ),
                ]
            )
            detail_metrics = [
                metric.model_copy(
                    update={
                        "label": "Harbor reward",
                        "value": "—",
                        "hint": (
                            "Excluded under frozen one-hour timeout rule"
                            if _is_agent_timeout(infra)
                            else "Run excluded by protocol"
                        ),
                    }
                )
                if infra and metric.label.lower() in {"reward", "mean reward", "score"}
                else metric
                for metric in detail.summary
            ]
            detail_metrics.extend(
                [
                    *(
                        [
                            Metric(
                                label="Output status",
                                value="invalid DOCX",
                                hint=str(record.get("invalid_output_reason") or ""),
                                tone="bad",
                            )
                        ]
                        if invalid_output
                        else []
                    ),
                    Metric(
                        label="Semantic score",
                        value=(
                            "not judged"
                            if invalid_output
                            else _number(record.get("semantic_score"), 4)
                        ),
                    ),
                    Metric(
                        label="Criteria",
                        value=(
                            "not judged"
                            if invalid_output
                            else _fraction(
                                record.get("semantic_passes"),
                                record.get("semantic_criteria"),
                            )
                        ),
                    ),
                    Metric(
                        label="All pass",
                        value=_yes_no(record.get("all_pass")),
                    ),
                    Metric(
                        label="Document craft",
                        value=str(review.get("practical_usability") or "—"),
                    ),
                ]
            )
            trial_details[trial_id] = detail.model_copy(
                update={"summary": detail_metrics, "sections": sections}
            )

    analyzed_ids = set(records_by_trial)
    raw_ids = set(base.trials)
    notices = list(base.notices)
    if analyzed_ids != raw_ids:
        notices.append(
            Notice(
                text=(
                    f"Analysis covers {len(analyzed_ids & raw_ids)}/"
                    f"{len(raw_ids)} raw trials"
                ),
                tone="warn",
            )
        )
    infrastructure_errors = int(task_summary.get("infrastructure_errors", 0))
    if infrastructure_errors:
        timeout_exclusions = sum(
            _is_agent_timeout(record.get("infrastructure_error"))
            for record in records
        )
        notices.append(
            Notice(
                text=(
                    f"{infrastructure_errors} trial(s) are excluded under the frozen "
                    + (
                        "one-hour timeout rule."
                        if timeout_exclusions == infrastructure_errors
                        else "runtime and timeout rules."
                    )
                ),
                tone="info",
            )
        )
    if invalid_outputs:
        notices.append(
            Notice(
                text=(
                    f"{invalid_outputs} trial(s) failed the required DOCX output "
                    "contract and received a benchmark zero before checklist review."
                ),
                tone="bad",
            )
        )

    reviewed = good + mixed + poor

    return base.model_copy(
        update={
            "primary_score": Metric(
                label=("Checklist review" if output_gate_only else "Mean semantic"),
                value=(
                    "not judged"
                    if output_gate_only
                    else _number(semantic.get("mean"), 4)
                ),
                hint=(
                    "Every retained attempt failed the required-file output gate"
                    if output_gate_only
                    else "Passed semantic criteria divided by authored semantic criteria"
                ),
            ),
            "metrics": [
                Metric(
                    label="Terminal trials",
                    value=_metric_value(base, "Trial records"),
                    hint="Harbor terminal trials over planned trials",
                ),
                Metric(
                    label="Retained trials",
                    value=f"{retained}/{attempted}",
                    hint="Trials retained in benchmark scoring",
                ),
                Metric(
                    label="Valid DOCX / retained",
                    value=f"{task_summary.get('valid_docx', 0)}/{retained}",
                ),
                Metric(
                    label="Mean Harbor reward / retained",
                    value=_number(harbor_reward.get("mean"), 4),
                ),
                Metric(
                    label="All pass / retained",
                    value=f"{task_summary.get('all_pass', 0)}/{retained}",
                ),
                Metric(
                    label=f"Document craft / {reviewed} reviewed",
                    value=f"{good} good · {mixed} mixed · {poor} poor",
                    hint=(
                        "Blind review of collected DOCX artifacts; this may include "
                        "an infrastructure-excluded trial"
                    ),
                ),
                Metric(
                    label="Excluded trials",
                    value=str(task_summary.get("infrastructure_errors", 0)),
                ),
            ],
            "notices": notices,
            "agent_table": DataTable(
                title="Agents",
                description="Task results for the resolved agent and model.",
                columns=[
                    TableColumn(key="agent", label="Agent"),
                    TableColumn(key="model", label="Model"),
                    TableColumn(key="trials", label="Terminal", align="right"),
                    TableColumn(key="retained", label="Retained", align="right"),
                    TableColumn(
                        key="valid", label="Valid / retained", align="right"
                    ),
                    TableColumn(
                        key="semantic",
                        label=(
                            "Checklist review / retained"
                            if output_gate_only
                            else "Mean semantic / retained"
                        ),
                        align="right",
                    ),
                    TableColumn(
                        key="all_pass", label="All pass / retained", align="right"
                    ),
                    TableColumn(key="input", label="Input tokens", align="right"),
                    TableColumn(key="output", label="Output tokens", align="right"),
                    TableColumn(key="cost", label="Reported cost", align="right"),
                ],
                rows=[
                    TableRow(
                        search=f"{agent_value} {model_value}".lower(),
                        cells={
                            "agent": TableCell(value=agent_value),
                            "model": TableCell(value=model_value),
                            "trials": TableCell(value=str(base.trial_count)),
                            "retained": TableCell(value=str(retained)),
                            "valid": TableCell(
                                value=(
                                    f"{task_summary.get('valid_docx', 0)}/{retained}"
                                )
                            ),
                            "semantic": TableCell(
                                value=(
                                    "not judged"
                                    if output_gate_only
                                    else _number(semantic.get("mean"), 4)
                                )
                            ),
                            "all_pass": TableCell(
                                value=f"{task_summary.get('all_pass', 0)}/{retained}"
                            ),
                            "input": TableCell(value=input_tokens),
                            "output": TableCell(value=output_tokens),
                            "cost": TableCell(value=cost),
                        },
                    )
                ],
            ),
            "trial_table": DataTable(
                title="Trials",
                description=(
                    "Harbor result, checklist review, and document review for each "
                    "trial. Invalid required files keep reward zero but are not "
                    "semantically judged. Excluded rows have no score."
                ),
                searchable=True,
                columns=[
                    TableColumn(key="trial", label="Trial"),
                    TableColumn(key="status", label="Status"),
                    TableColumn(
                        key="semantic",
                        label="Checklist review" if output_gate_only else "Semantic",
                        align="right",
                    ),
                    TableColumn(key="criteria", label="Criteria", align="right"),
                    TableColumn(key="reward", label="Harbor reward", align="right"),
                    TableColumn(key="all_pass", label="All pass", align="right"),
                    TableColumn(key="craft", label="Document craft"),
                    TableColumn(key="pages", label="Pages", align="right"),
                    TableColumn(key="duration", label="Duration", align="right"),
                ],
                rows=trial_rows,
            ),
            "trials": trial_details,
        }
    )


def _unanalyzed_trial_row(raw: TableRow) -> TableRow:
    return TableRow(
        search=raw.search,
        cells={
            "trial": raw.cells.get("trial", TableCell(value="—")),
            "status": raw.cells.get("status", TableCell(value="—")),
            "semantic": TableCell(value="—"),
            "criteria": TableCell(value="—"),
            "reward": raw.cells.get("reward", TableCell(value="—")),
            "all_pass": TableCell(value="—"),
            "craft": TableCell(value="—"),
            "pages": TableCell(value="—"),
            "duration": raw.cells.get("duration", TableCell(value="—")),
        },
    )


def _unscored_table(table: DataTable, *, description: str) -> DataTable:
    score_keys = {"reward", "score", "semantic", "criteria", "all_pass"}
    columns = [
        column.model_copy(
            update={"label": "Comparison score" if column.key in score_keys else column.label}
        )
        for column in table.columns
    ]
    rows = []
    for row in table.rows:
        cells = dict(row.cells)
        for key in score_keys & cells.keys():
            cells[key] = TableCell(value="—")
        rows.append(row.model_copy(update={"cells": cells}))
    return table.model_copy(
        update={"description": description, "columns": columns, "rows": rows}
    )


def _unscored_trial(trial: Any, reason: str) -> Any:
    summary = [
        metric.model_copy(
            update={
                "label": "Comparison score",
                "value": "—",
                "hint": "This job is excluded from comparison results",
            }
        )
        if metric.label.lower() in {"reward", "score", "semantic score", "all pass"}
        else metric
        for metric in trial.summary
    ]
    sections = [
        DetailSection(
            title="Comparison status",
            data={"status": "unscored", "reason": reason},
        )
        if section.title == "Rewards"
        else section
        for section in trial.sections
    ]
    return trial.model_copy(update={"summary": summary, "sections": sections})


def _cell(row: TableRow | None, key: str) -> str:
    if row is None or key not in row.cells:
        return "—"
    return row.cells[key].value


def _is_agent_timeout(value: Any) -> bool:
    return value is not None and "AgentTimeoutError" in str(value)


def _sanitize_public_trials(trials: dict[str, Any]) -> dict[str, Any]:
    hidden_sections = {"Error", "Resolved configuration"}
    return {
        trial_id: trial.model_copy(
            update={
                "sections": [
                    section
                    for section in trial.sections
                    if section.title not in hidden_sections
                ]
            }
        )
        for trial_id, trial in trials.items()
    }


def _metric_value(presentation: JobPresentation, label: str) -> str:
    match = next(
        (metric for metric in presentation.metrics if metric.label == label), None
    )
    return match.value if match else "—"


def _number(value: Any, digits: int) -> str:
    return "—" if not isinstance(value, (int, float)) else f"{float(value):.{digits}f}"


def _fraction(numerator: Any, denominator: Any) -> str:
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        return "—"
    return f"{numerator}/{denominator}"


def _yes_no(value: Any) -> str:
    if value == 1:
        return "yes"
    if value == 0:
        return "no"
    return "—"


def _duration(value: Any) -> str:
    return "—" if not isinstance(value, (int, float)) else f"{float(value):.1f}s"


def _signed(value: Any) -> str:
    return "—" if not isinstance(value, (int, float)) else f"{float(value):+.4f}"


def _craft_tone(value: Any) -> str:
    return {"good": "good", "mixed": "warn", "poor": "bad"}.get(str(value), "neutral")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
