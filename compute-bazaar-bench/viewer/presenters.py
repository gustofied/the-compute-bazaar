"""Adapters from evaluation-specific reports to the generic viewer contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .schema import (
    DataTable,
    DetailSection,
    GraderInfo,
    JobPresentation,
    LaunchSpec,
    Metric,
    Notice,
    TableCell,
    TableColumn,
    TableRow,
    TaskInfo,
    TaskLink,
    TrialPresentation,
)


RIB_SCHEMA = "reliability-is-blind.analysis.v1"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read presentation source {path}: {exc}") from exc


def _number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _percent(value: Any) -> str:
    return "—" if value is None else f"{100 * float(value):.1f}%"


def _agent_name(model: str, trials: list[dict[str, Any]]) -> str:
    match = next((trial for trial in trials if trial["trial"]["model"] == model), None)
    if match is None:
        return model
    agent = match["trial"].get("agent") or "agent"
    version = match["trial"].get("agent_version")
    harness = f"{agent} {version}" if version else str(agent)
    return f"{harness} · {model}"


def _rib_mean_reward(protocol: dict[str, Any]) -> float | None:
    trials = protocol.get("trials", [])
    if not trials:
        return None
    return sum(float(trial["reward"]) for trial in trials) / len(trials)


def _rib_mean_completed_delivery_rate(protocol: dict[str, Any]) -> float | None:
    completed = [
        trial for trial in protocol.get("trials", []) if trial.get("completion")
    ]
    if not completed:
        return None
    return sum(1.0 - float(trial["failure_rate"]) for trial in completed) / len(
        completed
    )


def _rib_trial_presentation(trial: dict[str, Any]) -> TrialPresentation:
    trial_data = trial["trial"]
    trial_id = str(trial_data["name"])
    return TrialPresentation(
        trial_id=trial_id,
        title=trial_id,
        summary=[
            Metric(label="Agent", value=_agent_name(trial_data["model"], [trial])),
            Metric(label="Seed cell", value=str(trial["protocol"].get("cell_id", "—"))),
            Metric(
                label="Status",
                value=str(trial["control"].get("outcome", "—")),
                tone=(
                    "good" if trial["control"].get("outcome") == "completed" else "bad"
                ),
            ),
            Metric(
                label="Completed deals",
                value=str(trial["control"].get("completed_deals", "—")),
            ),
            Metric(
                label="Failed deals",
                value=str(trial["result"].get("failed_deals", "—")),
            ),
            Metric(
                label="Delivery rate",
                value=(
                    _percent(1.0 - float(trial["result"].get("failure_rate", 0.0)))
                    if trial["control"].get("completed_deals", 0)
                    else "—"
                ),
            ),
            Metric(
                label="Target met",
                value=(
                    "—"
                    if not trial["trial"].get("completion")
                    else (
                        "yes"
                        if trial["result"].get("reliability_target_met") == 1
                        else "no"
                    )
                ),
            ),
            Metric(label="Reward", value=_number(trial["result"].get("reward"), 4)),
            Metric(
                label="Invalid selections",
                value=str(trial["control"].get("invalid_selections", "—")),
            ),
        ],
        sections=[
            DetailSection(title="Control", data=trial["control"]),
            DetailSection(title="Policy", data=trial["policy"]),
            DetailSection(title="Capability activation", data=trial["capability"]),
            DetailSection(
                title="Hidden evaluator diagnostics",
                data=trial["hidden_diagnostics"],
                warning="Never agent-visible",
            ),
        ],
    )


def _present_reliability_is_blind(
    protocol: dict[str, Any], trials: list[dict[str, Any]], run_id: str
) -> JobPresentation:
    task_root = (
        Path(__file__).resolve().parents[1] / "evals" / "reliability-is-blind" / "task"
    )
    instruction = (task_root / "instruction.md").read_text().strip()
    trial_details = {
        trial["trial"]["name"]: _rib_trial_presentation(trial) for trial in trials
    }
    agents = []
    for model in protocol.get("models", []):
        agents.append(
            TableRow(
                search=" ".join(str(value) for value in model.values()).lower(),
                cells={
                    "agent": TableCell(
                        value=_agent_name(str(model["model"]), trials),
                        title=str(model["model"]),
                    ),
                    "observed": TableCell(
                        value=f"{model['observed_trials']}/{model['planned_trials']}"
                    ),
                    "complete": TableCell(
                        value=(
                            f"{model['completed_rollouts']}/{model['observed_trials']}"
                        )
                    ),
                    "target": TableCell(
                        value=(
                            f"{model['reliability_targets_met']}/"
                            f"{model['completed_rollouts']}"
                        )
                    ),
                    "reward": TableCell(value=_number(model["mean_reward"], 4)),
                    "delivery_rate": TableCell(
                        value=_percent(
                            None
                            if model["mean_completed_failure_rate"] is None
                            else 1.0 - model["mean_completed_failure_rate"]
                        )
                    ),
                    "invalid": TableCell(value=str(model["invalid_selections"])),
                    "cost": TableCell(
                        value=(
                            f"{_number(model['reported_cost_usd'], 4)} "
                            f"({model['cost_coverage']})"
                        )
                    ),
                },
            )
        )

    trial_rows = []
    for trial in protocol.get("trials", []):
        outcome = str(trial["control_outcome"])
        trial_rows.append(
            TableRow(
                search=" ".join(str(value) for value in trial.values()).lower(),
                cells={
                    "trial": TableCell(
                        value=str(trial["cell_id"]),
                        href=str(trial["name"]),
                    ),
                    "agent": TableCell(value=str(trial["model"]).split("/")[-1]),
                    "status": TableCell(
                        value=outcome,
                        tone=(
                            "good"
                            if outcome == "completed"
                            else "bad"
                            if outcome
                            in {"interface_failure", "action_control_failure"}
                            else "warn"
                        ),
                    ),
                    "completed": TableCell(value=str(trial["completed_deals"])),
                    "failure_rate": TableCell(
                        value=(
                            _percent(trial["failure_rate"])
                            if trial["completed_deals"]
                            else "—"
                        )
                    ),
                    "target": TableCell(
                        value=(
                            "—"
                            if not trial["completion"]
                            else (
                                "yes" if trial["reliability_target_met"] == 1 else "no"
                            )
                        )
                    ),
                    "reward": TableCell(value=_number(trial["reward"], 4)),
                    "invalid": TableCell(value=str(trial["invalid_selections"])),
                },
            )
        )

    notices = []
    issues = [str(issue) for issue in protocol.get("issues", [])]
    if issues:
        notices.append(
            Notice(
                text=(
                    "Job diagnostics · "
                    f"{protocol.get('observed_trials', 0)}/"
                    f"{protocol.get('planned_trials', 0)} trials observed · "
                    f"{protocol.get('job_error_count', 0)} Harbor errors · "
                    f"{protocol.get('job_unfinished_count', 0)} unfinished job"
                ),
                tone="warn",
                details=issues,
            )
        )

    mean_reward = _rib_mean_reward(protocol)
    mean_delivery_rate = _rib_mean_completed_delivery_rate(protocol)
    observed = int(protocol.get("observed_trials", 0))
    completed = int(protocol.get("completed_rollouts", 0))
    target_met = int(protocol.get("reliability_targets_met", 0))
    return JobPresentation(
        task=TaskInfo(
            slug="reliability-is-blind",
            name="Reliability Is Blind",
            domain="Brokerage game",
            description=(
                "A compute brokerage game where an agent repeatedly places supply "
                "into deals, observes whether each complete placement delivered, "
                "and learns which suppliers to trust without being told what caused "
                "each failure."
            ),
            instruction=instruction,
            grader=GraderInfo(
                kind="Deterministic replay",
                primary_reward=(
                    "Mean calibrated broker reward across 100 completed deals"
                ),
                incomplete_outcome=(
                    "-1 for an incomplete book or 10 invalid selections"
                ),
                metrics=(
                    "Delivery rate, failure rate, 5% target attainment, completed "
                    "deals, and invalid selections"
                ),
                integrity=(
                    "Authenticated market ledger replayed by a separate no-network "
                    "verifier"
                ),
            ),
            links=[
                TaskLink(
                    label="Harbor task",
                    href=(
                        "https://hub.harborframework.com/tasks/"
                        "gustofied/reliability-is-blind/latest"
                    ),
                ),
                TaskLink(
                    label="Source",
                    href=(
                        "https://github.com/gustofied/the-compute-bazaar/tree/"
                        "main/compute-bazaar-bench/evals/reliability-is-blind"
                    ),
                ),
            ],
            launch=LaunchSpec(
                package_path=("compute-bazaar-bench/evals/reliability-is-blind/harbor"),
                task_id="reliability-is-blind",
            ),
        ),
        job_id=run_id,
        agent_count=len(protocol.get("models", [])),
        trial_count=int(protocol.get("observed_trials", len(trials))),
        primary_score=Metric(
            label="Mean reward",
            value=_number(mean_reward, 3),
            hint="Exact verifier reward averaged across observed trials",
        ),
        metrics=[
            Metric(
                label="Trials",
                value=(
                    f"{protocol.get('observed_trials', 0)}/"
                    f"{protocol.get('planned_trials', 0)}"
                ),
            ),
            Metric(
                label="Completed",
                value=(f"{completed}/{observed}"),
            ),
            Metric(
                label="Target met",
                value=f"{target_met}/{completed}",
            ),
            Metric(
                label="Mean delivery rate",
                value=_percent(mean_delivery_rate),
            ),
            Metric(
                label="Matched seed cells",
                value=(
                    f"{protocol.get('matched_seed_cells', 0)}/"
                    f"{protocol.get('planned_seed_cells', 0)}"
                ),
            ),
            Metric(
                label="Run health",
                value=(
                    f"{protocol.get('job_error_count', 0)} / "
                    f"{protocol.get('job_unfinished_count', 0)} / "
                    f"{protocol.get('job_retry_count', 0)}"
                ),
                hint="Errors / unfinished jobs / retries",
            ),
        ],
        notices=notices,
        agent_table=DataTable(
            title="Agents",
            description="Exact task reward and adjacent diagnostics by agent configuration.",
            columns=[
                TableColumn(key="agent", label="Agent"),
                TableColumn(key="observed", label="Observed", align="right"),
                TableColumn(key="complete", label="Completed", align="right"),
                TableColumn(key="target", label="Target met", align="right"),
                TableColumn(key="delivery_rate", label="Delivery rate", align="right"),
                TableColumn(key="reward", label="Mean reward", align="right"),
                TableColumn(key="invalid", label="Invalid", align="right"),
                TableColumn(key="cost", label="Reported cost", align="right"),
            ],
            rows=agents,
        ),
        trial_table=DataTable(
            title="Trials",
            searchable=True,
            columns=[
                TableColumn(key="trial", label="Seed cell"),
                TableColumn(key="agent", label="Agent"),
                TableColumn(key="status", label="Status"),
                TableColumn(key="completed", label="Deals", align="right"),
                TableColumn(key="failure_rate", label="Failure rate", align="right"),
                TableColumn(key="target", label="Target met", align="right"),
                TableColumn(key="reward", label="Reward", align="right"),
                TableColumn(key="invalid", label="Invalid", align="right"),
            ],
            rows=trial_rows,
        ),
        trials=trial_details,
    )


def _present_generic(
    protocol: dict[str, Any], trials: list[dict[str, Any]], run_id: str, eval_slug: str
) -> JobPresentation:
    task_name = eval_slug.replace("-", " ").title()
    trial_rows = []
    details = {}
    for index, trial in enumerate(trials, start=1):
        trial_data = trial.get("trial", trial)
        trial_id = str(trial_data.get("name") or f"trial-{index:03d}")
        reward = trial.get("reward", trial.get("result", {}).get("reward"))
        agent = trial_data.get("agent") or trial_data.get("model") or "—"
        trial_rows.append(
            TableRow(
                search=json.dumps(trial, sort_keys=True).lower(),
                cells={
                    "trial": TableCell(value=trial_id, href=trial_id),
                    "agent": TableCell(value=str(agent)),
                    "reward": TableCell(value=_number(reward, 4)),
                },
            )
        )
        details[trial_id] = TrialPresentation(
            trial_id=trial_id,
            title=trial_id,
            summary=[
                Metric(label="Agent", value=str(agent)),
                Metric(label="Reward", value=_number(reward, 4)),
            ],
            sections=[DetailSection(title="Trial data", data=trial)],
        )

    return JobPresentation(
        task=TaskInfo(
            slug=eval_slug,
            name=task_name,
            domain="Evaluation",
            description=str(protocol.get("description", "")),
        ),
        job_id=run_id,
        agent_count=len(protocol.get("models", [])),
        trial_count=len(trials),
        metrics=[Metric(label="Trials", value=str(len(trials)))],
        notices=[],
        agent_table=DataTable(title="Agents", columns=[], rows=[]),
        trial_table=DataTable(
            title="Trials",
            searchable=True,
            columns=[
                TableColumn(key="trial", label="Trial"),
                TableColumn(key="agent", label="Agent"),
                TableColumn(key="reward", label="Reward", align="right"),
            ],
            rows=trial_rows,
        ),
        trials=details,
    )


def load_job_presentation(
    run_dir: Path, eval_slug: str, run_id: str
) -> JobPresentation:
    presentation_path = run_dir / "view.json"
    if presentation_path.is_file():
        try:
            return JobPresentation.model_validate(_read_json(presentation_path))
        except ValidationError as exc:
            raise RuntimeError(
                f"invalid generic presentation {presentation_path}: {exc}"
            ) from exc

    protocol = _read_json(run_dir / "protocol.json")
    trials = _read_json(run_dir / "trials.json")
    if not isinstance(protocol, dict) or not isinstance(trials, list):
        raise RuntimeError(f"invalid analysis files in {run_dir}")
    if protocol.get("schema_version") == RIB_SCHEMA:
        return _present_reliability_is_blind(protocol, trials, run_id)
    return _present_generic(protocol, trials, run_id, eval_slug)
