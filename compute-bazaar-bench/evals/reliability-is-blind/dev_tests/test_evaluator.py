from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from typing import Any, Sequence

EVAL_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_ROOT = EVAL_ROOT / "evaluator"
TASK_ROOT = EVAL_ROOT / "task"
BENCH_ROOT = EVAL_ROOT.parents[1]
sys.path.insert(0, str(BENCH_ROOT))
sys.path.insert(0, str(EVALUATOR_ROOT))

import analysis as rib_analysis  # noqa: E402
import protocol as rib_protocol  # noqa: E402
from viewer.app import (  # noqa: E402
    ASSET_ROOT,
    _discover_run_paths,
    _evaluation_summary,
    _evals_html,
    _index_html,
    _runs_html,
    create_app,
)
from viewer.presenters import load_job_presentation  # noqa: E402
from viewer.schema import (  # noqa: E402
    DataTable,
    DetailSection,
    GraderInfo,
    JobPresentation,
    LaunchSpec,
    Metric,
    TableCell,
    TableColumn,
    TableRow,
    TaskInfo,
    TaskLink,
    TrialPresentation,
)


ENGINE_SHA256 = hashlib.sha256(
    (TASK_ROOT / "environment" / "market-sidecar" / "market_engine.py").read_bytes()
).hexdigest()


def jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def artifact_config(config: Any) -> dict[str, Any]:
    value = asdict(config)
    value.update(
        {
            "reward_amount": config.reward_amount,
            "minimum_stake": config.minimum_stake,
            "maximum_stake": config.maximum_stake,
            "ruin_threshold": config.ruin_threshold,
            "incomplete_reward": config.incomplete_reward,
        }
    )
    return value


def sample_presentation() -> JobPresentation:
    trial = TrialPresentation(
        trial_id="trial-001",
        title="Trial 001",
        summary=[Metric(label="Agent", value="example-agent")],
        sections=[DetailSection(title="Output", data={"answer": "yes"})],
    )
    return JobPresentation(
        task=TaskInfo(
            slug="reliability-is-blind",
            name="Reliability Is Blind",
            domain="Brokerage game",
            description="A compute brokerage game.",
            instruction="Choose four suppliers.",
            grader=GraderInfo(
                kind="Deterministic replay",
                primary_reward="Mean broker reward",
                incomplete_outcome="-1",
                metrics="Delivery rate",
                integrity="Protected ledger replay",
            ),
            links=[TaskLink(label="Harbor task", href="https://example.com/task")],
            launch=LaunchSpec(
                package_path=("compute-bazaar-bench/evals/reliability-is-blind/task"),
                task_id="reliability-is-blind",
            ),
        ),
        job_id="matched-run-001",
        agent_count=3,
        trial_count=59,
        primary_score=Metric(
            label="Mean reward",
            value="-0.455",
            hint="Exact verifier reward averaged across observed trials",
        ),
        metrics=[Metric(label="Completed books", value="34")],
        notices=[],
        agent_table=DataTable(title="Agents", columns=[], rows=[]),
        trial_table=DataTable(
            title="Trials",
            columns=[TableColumn(key="trial", label="Trial")],
            rows=[
                TableRow(
                    cells={"trial": TableCell(value="Trial 001", href="trial-001")}
                )
            ],
        ),
        trials={"trial-001": trial},
    )


def write_trial(
    root: Path,
    *,
    name: str,
    model: str,
    requests: Sequence[Sequence[int]],
    commands: Sequence[str] = (),
    delegated: bool = False,
    seed: int = 2026080301,
    task_digest: str = "sha256:test-task",
) -> Path:
    module = rib_analysis._load_engine_module(TASK_ROOT, ENGINE_SHA256)
    config = module.MarketConfig()
    engine = module.MarketEngine(config)
    engine.reset(seed)
    attempts: list[dict[str, Any]] = []
    for attempt_id, requested in enumerate(requests, start=1):
        step = engine.step(requested)
        attempts.append(
            {
                "attempt_id": attempt_id,
                "requested_supplier_ids": list(requested),
                "accepted": step.accepted,
                "error": step.error,
                "deal": jsonable(step.deal),
                "broker_reward": step.broker_reward,
                "post_state": {
                    "completed_deals": step.observation.completed_deals,
                    "invalid_actions": step.observation.invalid_actions,
                    "terminal": step.observation.terminal,
                    "terminal_reason": jsonable(step.observation.terminal_reason),
                },
            }
        )
        if engine.terminal:
            break

    result = engine.result()
    artifact = {
        "schema_version": "test",
        "artifact_kind": "authoritative_market_ledger",
        "engine": {
            "version": module.ENGINE_VERSION,
            "upstream_revision": module.UPSTREAM_REVISION,
            "sha256": ENGINE_SHA256,
        },
        "seed": str(seed),
        "config": artifact_config(config),
        "attempts": attempts,
        "final_observation": jsonable(engine.observe()),
        "final_result": jsonable(result),
        "request_counts": {
            "total": len(attempts),
            "by_action": {"select": len(attempts)} if attempts else {},
        },
        "finalized": True,
    }

    trial = root / name
    (trial / "agent").mkdir(parents=True)
    (trial / "artifacts" / "market-artifacts").mkdir(parents=True)
    (trial / "verifier").mkdir(parents=True)
    artifact_path = trial / "artifacts" / "market-artifacts" / "state.json"
    artifact_path.write_text(json.dumps(artifact, sort_keys=True))
    artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    tool_calls: list[dict[str, Any]] = [
        {
            "function_name": "bash",
            "arguments": {"command": command},
        }
        for command in commands
    ]
    if delegated:
        tool_calls.insert(
            0,
            {
                "function_name": "task",
                "arguments": {"prompt": "operate market"},
            },
        )
    trajectory = {
        "schema_version": "1.0",
        "steps": [
            {"step_id": 1, "source": "user", "message": "test"},
            {
                "step_id": 2,
                "source": "agent",
                "message": "",
                "tool_calls": tool_calls or None,
            },
        ],
    }
    (trial / "agent" / "trajectory.json").write_text(json.dumps(trajectory))
    lock = {
        "task": {"digest": task_digest},
        "agent": {"name": "opencode", "model_name": model},
        "environment": {"type": "modal", "kwargs": {"modal_vm_runtime": True}},
    }
    (trial / "lock.json").write_text(json.dumps(lock))
    (trial / "result.json").write_text(
        json.dumps(
            {
                "trial_name": name,
                "started_at": "2026-08-03T00:00:00Z",
                "finished_at": "2026-08-03T00:01:00Z",
                "agent_execution": {
                    "started_at": "2026-08-03T00:00:10Z",
                    "finished_at": "2026-08-03T00:00:50Z",
                },
                "agent_result": {
                    "n_input_tokens": 10,
                    "n_cache_tokens": 2,
                    "n_output_tokens": 3,
                    "cost_usd": 0.01,
                },
                "agent_info": {"name": "opencode", "version": "1.18.11"},
                "exception_info": None,
            }
        )
    )
    reward = {
        "reward": result.primary_reward,
        "completion": result.completion,
        "completed_deals": result.completed_deals,
        "delivered_deals": result.delivered_deals,
        "failed_deals": result.failed_deals,
        "delivery_rate": result.delivery_rate,
        "failure_rate": result.failure_rate,
        "reliability_target_met": int(result.target_met),
        "verifier_integrity": 1,
    }
    (trial / "verifier" / "reward.json").write_text(json.dumps(reward))
    (trial / "verifier" / "evidence.json").write_text(
        json.dumps({"artifact_sha256": artifact_hash})
    )
    return trial


class ReliabilityIsBlindAnalysisTests(unittest.TestCase):
    def test_completed_fixed_route_is_not_mislabeled_as_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial = write_trial(
                Path(directory),
                name="medium",
                model="mistral/mistral-medium-3-5",
                requests=[[0, 1, 2, 3]] * 100,
                commands=["market status", "market select 0 1 2 3"],
            )

            analysis = rib_analysis.analyze_trial(trial, task_root=TASK_ROOT)

        self.assertEqual(analysis["control"]["outcome"], "completed")
        self.assertEqual(analysis["policy"]["top_bundle_share"], 1.0)
        self.assertFalse(analysis["capability"]["attribution_challenge_activated"])
        self.assertEqual(
            analysis["capability"]["highest_layer_reached"],
            "market_operation_without_collective_failure",
        )
        self.assertAlmostEqual(
            analysis["hidden_diagnostics"][
                "dominant_bundle_observed_outcome_likelihood"
            ],
            0.5221225607340606,
        )

    def test_no_tool_use_is_an_interface_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial = write_trial(
                Path(directory),
                name="small",
                model="mistral/mistral-small-2603",
                requests=[],
            )
            analysis = rib_analysis.analyze_trial(trial, task_root=TASK_ROOT)

        self.assertEqual(analysis["control"]["outcome"], "interface_failure")
        self.assertEqual(
            analysis["capability"]["highest_layer_reached"],
            "interface_not_entered",
        )

    def test_collective_failure_does_not_imply_overlapping_evidence(self) -> None:
        requests = [
            list(range(10)),
            [0, 1, 2, 3],
            [4, 5, 6, 7],
            [8, 9, 10, 11],
            [12, 13, 14, 15],
            [16, 17, 18, 19],
        ] + [list(range(start, start + 4)) for start in range(20, 56, 4)]
        with tempfile.TemporaryDirectory() as directory:
            trial = write_trial(
                Path(directory),
                name="large",
                model="mistral/mistral-large-2512",
                requests=requests,
                commands=["market reset", "market status"],
                delegated=True,
            )
            analysis = rib_analysis.analyze_trial(trial, task_root=TASK_ROOT)

        self.assertEqual(analysis["control"]["outcome"], "action_control_failure")
        self.assertTrue(analysis["capability"]["attribution_challenge_activated"])
        self.assertFalse(analysis["capability"]["overlapping_success_failure_evidence"])
        self.assertEqual(
            analysis["capability"]["highest_layer_reached"],
            "collective_failure_with_followup_decisions",
        )

    def test_single_seed_comparison_refuses_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            write_trial(
                job,
                name="medium",
                model="mistral/mistral-medium-3-5",
                requests=[[0, 1, 2, 3]] * 100,
                commands=["market status"],
            )
            write_trial(
                job,
                name="small",
                model="mistral/mistral-small-2603",
                requests=[],
            )

            _, comparison = rib_analysis.compare_job(job, task_root=TASK_ROOT)

        self.assertFalse(comparison["ranking_allowed"])
        self.assertEqual(
            comparison["label"], "SINGLE-SEED CANARY - NOT A MODEL RANKING"
        )
        self.assertEqual(comparison["matched_seed_count"], 1)

    def test_mismatched_task_digest_blocks_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            write_trial(
                job,
                name="left",
                model="model-left",
                requests=[],
                task_digest="sha256:left",
            )
            write_trial(
                job,
                name="right",
                model="model-right",
                requests=[],
                task_digest="sha256:right",
            )

            _, comparison = rib_analysis.compare_job(job, task_root=TASK_ROOT)

        self.assertIn("task digests differ", comparison["ranking_blockers"])
        self.assertFalse(comparison["ranking_allowed"])

    def test_protocol_preparation_balances_and_commits_hidden_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "private.json"
            commitment = root / "commitment.json"
            secret = root / "secret"

            rib_protocol.prepare_protocol(
                private_manifest=manifest,
                commitment_path=commitment,
                secret_path=secret,
                task_root=TASK_ROOT,
            )
            rib_protocol.verify_commitment(manifest, commitment)
            private = json.loads(manifest.read_text())
            public = json.loads(commitment.read_text())

        self.assertEqual(len(private["cells"]), 20)
        self.assertEqual(len(private["canary_cell_ids"]), 3)
        self.assertEqual(
            {cell["difficulty_stratum"] for cell in private["cells"]},
            {name for name, _, _ in rib_protocol.STRATA},
        )
        self.assertNotIn("cells", public)
        self.assertFalse(public["raw_seeds_public"])
        self.assertEqual(public["planned_trials"], 60)

    def test_three_seed_protocol_gate_requires_every_matched_trial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = root / "jobs"
            models = ["model-left", "model-right"]
            cells = []
            for index, seed in enumerate((2026080301, 41, 43), start=1):
                cell_id = f"rib-{index:03d}"
                job_name = f"protocol-{cell_id}"
                cells.append(
                    {
                        "cell_id": cell_id,
                        "job_name": job_name,
                        "seed": seed,
                        "difficulty_stratum": "test",
                    }
                )
                job = jobs / job_name
                write_trial(
                    job,
                    name=f"{cell_id}-left",
                    model=models[0],
                    requests=[],
                    seed=seed,
                )
                write_trial(
                    job,
                    name=f"{cell_id}-right",
                    model=models[1],
                    requests=[],
                    seed=seed,
                )
                (job / "result.json").write_text(
                    json.dumps(
                        {
                            "finished_at": "2026-08-03T00:00:00Z",
                            "stats": {
                                "n_completed_trials": 2,
                                "n_errored_trials": 0,
                                "n_pending_trials": 0,
                                "n_retries": 0,
                            },
                        }
                    )
                )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "reliability-is-blind.analysis.v1",
                        "protocol_id": "protocol",
                        "models": models,
                        "canary_cell_ids": [cell["cell_id"] for cell in cells],
                        "cells": cells,
                    }
                )
            )

            _, comparison = rib_analysis.analyze_protocol(
                manifest, jobs, phase="canary", task_root=TASK_ROOT
            )

        self.assertTrue(comparison["canary_gate_passed"])
        self.assertFalse(comparison["ranking_allowed"])
        self.assertEqual(comparison["observed_trials"], 6)
        self.assertEqual(comparison["matched_seed_cells"], 3)

    def test_unfinished_job_is_never_a_clean_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = root / "jobs"
            job = jobs / "job"
            write_trial(job, name="trial", model="model", requests=[], seed=7)
            (job / "result.json").write_text(
                json.dumps(
                    {
                        "finished_at": None,
                        "stats": {
                            "n_completed_trials": 1,
                            "n_errored_trials": 0,
                            "n_retries": 0,
                        },
                    }
                )
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "protocol_id": "protocol",
                        "models": ["model"],
                        "canary_cell_ids": ["rib-001"],
                        "cells": [
                            {
                                "cell_id": "rib-001",
                                "job_name": "job",
                                "seed": "7",
                            }
                        ],
                    }
                )
            )

            _, comparison = rib_analysis.analyze_protocol(
                manifest, jobs, phase="canary", task_root=TASK_ROOT
            )

        self.assertFalse(comparison["canary_gate_passed"])
        self.assertEqual(comparison["job_unfinished_count"], 1)
        self.assertIn("rib-001: job did not finalize", comparison["issues"])

    def test_view_is_local_analysis_not_a_second_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            analysis = Path(directory)
            (analysis / "protocol.json").write_text(
                json.dumps(
                    {
                        "protocol_id": "protocol",
                        "label": "CANARY",
                        "models": [],
                        "trials": [],
                        "issues": [],
                        "observed_trials": 0,
                        "planned_trials": 0,
                        "matched_seed_cells": 0,
                        "planned_seed_cells": 0,
                        "completed_rollouts": 0,
                        "reliability_targets_met": 0,
                        "attribution_challenges_activated": 0,
                        "job_error_count": 0,
                        "job_unfinished_count": 0,
                        "job_retry_count": 0,
                    }
                )
            )
            (analysis / "trials.json").write_text("[]")

            app = create_app(analysis)

        self.assertEqual(app.title, "Compute Bazaar Evals")
        route_paths = {route.path for route in app.routes}
        self.assertIn("/evals/{eval_slug}", route_paths)
        self.assertIn("/evals/{eval_slug}/jobs/{run_id}", route_paths)
        self.assertIn(
            "/evals/{eval_slug}/jobs/{run_id}/trials/{trial_name}", route_paths
        )
        self.assertIn("/api/evals", route_paths)
        self.assertIn("/api/evals/{eval_slug}/jobs", route_paths)
        self.assertIn("/api/evals/{eval_slug}/jobs/{run_id}/note", route_paths)

    def test_view_shows_compute_bazaar_wordmark(self) -> None:
        self.assertTrue(
            (ASSET_ROOT / "compute-title" / "compute-title-embroidery.js").is_file()
        )
        self.assertTrue(
            (
                ASSET_ROOT / "compute-title" / "assets" / "embroidery-weave.webp"
            ).is_file()
        )
        html = _index_html(sample_presentation())
        self.assertIn("data-compute-embroidery", html)
        self.assertIn("compute-brand-word compute", html)
        self.assertIn('href="/">Tasks</a> /', html)
        self.assertIn("/ Job", html)
        self.assertNotIn("compute-brand-panel", html)

    def test_evals_home_uses_common_evaluation_summary(self) -> None:
        presentation = sample_presentation().model_copy(
            update={"agent_count": 1, "trial_count": 2}
        )
        summary = _evaluation_summary(presentation)
        html = _evals_html([summary])

        self.assertIn("<h2>Tasks</h2>", html)
        self.assertIn("data-compute-embroidery", html)
        self.assertNotIn("<h1>", html)
        self.assertIn('href="/evals/reliability-is-blind"', html)
        self.assertIn("Reliability Is Blind", html)
        self.assertIn("Task", html)
        self.assertIn("Domain", html)
        self.assertIn("Brokerage game", html)
        self.assertIn("Jobs", html)
        self.assertIn("Agents", html)
        self.assertNotIn("Status</span>", html)
        self.assertIn("Trials</span>2", html)

    def test_eval_page_lists_runs_before_trials(self) -> None:
        html = _runs_html(
            sample_presentation().task,
            [
                {
                    "run_id": "matched-run-001",
                    "score": Metric(label="Mean reward", value="-0.455"),
                    "agents": 3,
                    "trials": 59,
                    "note": "One trial is missing; interpret as exploratory.",
                }
            ],
        )

        self.assertIn("<h2>Jobs</h2>", html)
        self.assertIn("A compute brokerage game.", html)
        self.assertIn("Agent instruction", html)
        self.assertIn("Grader", html)
        self.assertIn("Deterministic replay", html)
        self.assertIn("Mean broker reward", html)
        self.assertIn("Choose four suppliers.", html)
        self.assertIn("Launch job", html)
        self.assertIn("harbor", html)
        self.assertIn("Mean reward", html)
        self.assertIn("-0.455", html)
        self.assertNotIn("Phase", html)
        self.assertIn("Agents", html)
        self.assertIn("Note", html)
        self.assertIn("One trial is missing; interpret as exploratory.", html)
        self.assertNotIn("Status</span>", html)
        self.assertIn('href="/evals/reliability-is-blind/jobs/matched-run-001"', html)
        self.assertNotIn("<h2>Trials</h2>", html)

    def test_generic_view_contract_renders_a_different_eval_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            payload = {
                "task": {
                    "slug": "deal-room",
                    "name": "Deal Room",
                    "domain": "Procurement diligence",
                },
                "job_id": "deal-room-canary-001",
                "agent_count": 2,
                "trial_count": 1,
                "primary_score": {"label": "Rubric score", "value": "82%"},
                "metrics": [
                    {"label": "Critical failures", "value": "0", "tone": "good"}
                ],
                "notices": [],
                "agent_table": {"title": "Agents", "columns": [], "rows": []},
                "trial_table": {
                    "title": "Matter trials",
                    "columns": [{"key": "trial", "label": "Matter"}],
                    "rows": [
                        {
                            "cells": {
                                "trial": {
                                    "value": "Virginia capacity review",
                                    "href": "matter-001",
                                }
                            }
                        }
                    ],
                },
                "trials": {
                    "matter-001": {
                        "trial_id": "matter-001",
                        "title": "Virginia capacity review",
                        "summary": [{"label": "Rubric score", "value": "82%"}],
                        "sections": [
                            {
                                "title": "Criterion results",
                                "data": {"commercial_fit": "pass"},
                            }
                        ],
                    }
                },
            }
            (run / "view.json").write_text(json.dumps(payload))

            presentation = load_job_presentation(run, "deal-room", "ignored")
            html = _index_html(presentation)

        self.assertIn("Deal Room", html)
        self.assertIn("Rubric score", html)
        self.assertIn("Matter trials", html)
        self.assertNotIn("Attribution activated", html)
        self.assertNotIn("Matched seeds", html)

    def test_results_are_discovered_by_eval_then_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "reliability-is-blind" / "runs" / "matched-run-001"
            run.mkdir(parents=True)
            (run / "protocol.json").write_text("{}")
            (run / "trials.json").write_text("[]")

            discovered = _discover_run_paths(root)

        self.assertEqual(
            discovered,
            {"reliability-is-blind": {"matched-run-001": run.resolve()}},
        )


if __name__ == "__main__":
    unittest.main()
