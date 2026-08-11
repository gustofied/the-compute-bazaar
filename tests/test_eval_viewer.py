from __future__ import annotations

from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
import textwrap
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = PROJECT_ROOT / "compute-bazaar-bench"
if str(BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCH_ROOT))

from viewer.app import create_app, first_evaluation_url  # noqa: E402
from viewer.presenters import load_job_presentation  # noqa: E402
from viewer.task_catalog import discover_task_definitions  # noqa: E402


class TaskCatalogTests(unittest.TestCase):
    def test_internal_adjudication_packages_are_not_launchable_tasks(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            internal = (
                bench_root / "evals/transactions/adjudication/verifier-v2/sample-task"
            )
            internal.mkdir(parents=True)
            (internal / "task.toml").write_text(
                '[task]\nname = "gustofied/sample-task"\n', encoding="utf-8"
            )

            tasks = discover_task_definitions(bench_root)

            self.assertEqual(list(tasks), ["sample-task"])

    def test_report_loader_reads_instruction_from_harbor_package(self) -> None:
        with TemporaryDirectory() as temporary:
            report = Path(temporary)
            _write_json(
                report / "protocol.json",
                {
                    "schema_version": "reliability-is-blind.analysis.v1",
                    "models": [],
                    "trials": [],
                    "observed_trials": 0,
                    "planned_trials": 0,
                    "completed_rollouts": 0,
                    "reliability_targets_met": 0,
                },
            )
            _write_json(report / "trials.json", [])

            presentation = load_job_presentation(
                report,
                "reliability-is-blind",
                "sample-run",
            )

            self.assertEqual(presentation.task.slug, "reliability-is-blind")
            self.assertIn("book of 100 compute deals", presentation.task.instruction)

    def test_internal_archive_packages_are_not_launchable_tasks(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            internal = bench_root / "evals/transactions/internal/archive/sample-task"
            internal.mkdir(parents=True)
            (internal / "task.toml").write_text(
                '[task]\nname = "gustofied/sample-task"\n', encoding="utf-8"
            )

            tasks = discover_task_definitions(bench_root)

            self.assertEqual(list(tasks), ["sample-task"])

    def test_release_preflight_packages_are_not_launchable_tasks(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            preflight = (
                bench_root
                / "evals/transactions/releases/release-v1/preflight/model-route"
            )
            preflight.mkdir(parents=True)
            (preflight / "task.toml").write_text(
                '[task]\nname = "gustofied/private-preflight"\n', encoding="utf-8"
            )

            tasks = discover_task_definitions(bench_root)

            self.assertEqual(list(tasks), ["sample-task"])

    def test_authored_task_appears_before_any_job_report(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            task_root = bench_root / "evals" / "transactions" / "sample-task"
            task_root.mkdir(parents=True)
            (task_root / "instruction.md").write_text(
                "Produce the requested brief.\n", encoding="utf-8"
            )
            (task_root / "task.toml").write_text(
                textwrap.dedent(
                    """
                    schema_version = "1.3"

                    [task]
                    name = "gustofied/sample-task"
                    description = "A task with no jobs yet."

                    [metadata]
                    domain = "transactions"
                    n_criteria = 12

                    [verifier]
                    environment_mode = "separate"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            tasks = discover_task_definitions(bench_root)
            self.assertEqual(list(tasks), ["sample-task"])
            self.assertEqual(tasks["sample-task"].domain, "Transactions")
            self.assertEqual(tasks["sample-task"].launch.task_id, "sample-task")

            reports = bench_root / "jobs" / "reports"
            app = create_app(reports, bench_root=bench_root)

            index = _route_endpoint(app, "/")()
            self.assertIn("Sample Task", index)
            self.assertIn("Transactions", index)

            detail = _route_endpoint(app, "/evals/{eval_slug}")("sample-task")
            self.assertIn("Produce the requested brief.", detail)
            self.assertIn("No jobs yet.", detail)
            self.assertIn("Launch job", detail)
            self.assertIn(
                "https://hub.harborframework.com/tasks/gustofied/sample-task/latest",
                detail,
            )
            self.assertIn("modal_vm_runtime=true", detail)
            self.assertIn("'--env-file',launchSpec.default_env_file", detail)
            self.assertNotIn("'-i',launchSpec.task_id", detail)
            self.assertIn("if(attempts!=='1')", detail)
            self.assertEqual(detail.count('autocapitalize="none"'), 3)
            self.assertIn("const newJobName=", detail)
            self.assertIn("-job-${stamp}-${suffix}", detail)
            self.assertIn("['tmux','new-session','-A','-s'", detail)
            self.assertIn("tmuxSession(value('launch-name'))", detail)

            native_app = create_app(
                reports,
                bench_root=bench_root,
                base_path="/eval",
            )
            native_detail = _route_endpoint(native_app, "/evals/{eval_slug}")(
                "sample-task"
            )
            self.assertIn('data-external-link="true"', native_detail)
            self.assertIn("/api/terminal/external", native_detail)

    def test_task_links_only_own_harbor_package(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            task_root = bench_root / "evals" / "transactions" / "sample-task"
            task_root.mkdir(parents=True)
            (task_root / "task.toml").write_text(
                textwrap.dedent(
                    """
                    [task]
                    name = "gustofied/sample-task"

                    [metadata]
                    source_harbor_url = "https://hub.harborframework.com/tasks/source/task/latest"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            task = discover_task_definitions(bench_root)["sample-task"]

            self.assertEqual(
                [(link.label, link.href) for link in task.links],
                [
                    (
                        "Harbor task",
                        "https://hub.harborframework.com/tasks/gustofied/sample-task/latest",
                    ),
                ],
            )

    def test_first_evaluation_url_uses_authored_tasks(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            task_root = bench_root / "evals" / "alpha"
            task_root.mkdir(parents=True)
            (task_root / "task.toml").write_text(
                '[task]\nname = "gustofied/alpha"\n', encoding="utf-8"
            )

            self.assertEqual(
                first_evaluation_url(
                    bench_root / "jobs" / "reports", bench_root=bench_root
                ),
                "/eval/evals/alpha",
            )

    def test_raw_harbor_job_appears_without_a_report(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "job-001")

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            jobs = _route_endpoint(app, "/api/evals/{eval_slug}/jobs")("sample-task")
            self.assertEqual([item["run_id"] for item in jobs], ["job-001"])

            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "job-001"
            )
            self.assertEqual(detail["task"]["slug"], "sample-task")
            self.assertEqual(detail["started_at"], "2026-01-01T00:00:00Z")
            self.assertEqual(detail["finished_at"], "2026-01-01T00:00:12Z")
            self.assertEqual(detail["trial_count"], 1)
            self.assertEqual(detail["primary_score"]["label"], "Mean reward")
            self.assertEqual(detail["primary_score"]["value"], "0.7500")
            metrics = {item["label"]: item["value"] for item in detail["metrics"]}
            self.assertEqual(metrics["Trial records"], "1/1")
            self.assertEqual(metrics["Finished trials"], "1")
            self.assertEqual(metrics["Still running"], "0")
            self.assertIn("sample-task__abc", detail["trials"])
            trial = detail["trials"]["sample-task__abc"]
            self.assertEqual(trial["trace"]["step_count"], 2)
            self.assertIn(
                "binary payload omitted",
                trial["trace"]["steps"][1]["tool_calls"][0]["arguments"]["content"],
            )
            self.assertNotIn(
                "Trajectory", [section["title"] for section in trial["sections"]]
            )

            html = _route_endpoint(
                app,
                "/evals/{eval_slug}/jobs/{run_id}/trials/{trial_name}",
            )("sample-task", "job-001", "sample-task__abc")
            self.assertIn('class="trace-step"', html)
            self.assertIn("binary payload omitted", html)

    def test_canonical_harbor_job_appears_directly_under_jobs(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(
                bench_root,
                "sample-task",
                "job-001",
                jobs_subdir=None,
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            jobs = _route_endpoint(app, "/api/evals/{eval_slug}/jobs")("sample-task")

            self.assertEqual([item["run_id"] for item in jobs], ["job-001"])

    def test_jobs_are_sorted_newest_first_and_show_start_time(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(
                bench_root,
                "sample-task",
                "older-job",
                started_at="2026-01-01T08:00:00Z",
            )
            _write_raw_job(
                bench_root,
                "sample-task",
                "newer-job",
                started_at="2026-02-03T14:05:00Z",
                finished_at="2026-02-03T14:05:12Z",
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            jobs = _route_endpoint(app, "/api/evals/{eval_slug}/jobs")("sample-task")
            self.assertEqual(
                [item["run_id"] for item in jobs], ["newer-job", "older-job"]
            )

            html = _route_endpoint(app, "/evals/{eval_slug}")("sample-task")
            self.assertIn("Started UTC", html)
            self.assertIn("03 Feb 2026, 14:05", html)
            self.assertLess(html.index("newer-job"), html.index("older-job"))

    def test_jobs_created_after_start_are_discovered_on_refresh(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            jobs_endpoint = _route_endpoint(app, "/api/evals/{eval_slug}/jobs")

            self.assertEqual(jobs_endpoint("sample-task"), [])

            _write_raw_job(bench_root, "sample-task", "new-job")

            jobs = jobs_endpoint("sample-task")
            self.assertEqual([item["run_id"] for item in jobs], ["new-job"])
            html = _route_endpoint(app, "/evals/{eval_slug}")("sample-task")
            self.assertIn("new-job", html)

    def test_task_summary_aggregates_raw_jobs_and_agent_configurations(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(
                bench_root,
                "sample-task",
                "job-a",
                model_name="mistral/model-a",
            )
            _write_raw_job(
                bench_root,
                "sample-task",
                "job-b",
                model_name="mistral/model-b",
                trial_ids=["sample-task__def", "sample-task__ghi"],
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            evaluations = _route_endpoint(app, "/api/evals")()
            summary = next(
                item for item in evaluations if item["slug"] == "sample-task"
            )

            self.assertEqual(summary["jobs"], 2)
            self.assertEqual(summary["agents"], 2)
            self.assertEqual(summary["trials"], 3)

    def test_task_and_job_indexes_do_not_load_full_trial_presentations(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "job-001")
            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)

            with patch(
                "viewer.app.present_harbor_job",
                side_effect=AssertionError("index loaded a full Harbor presentation"),
            ):
                evaluations = _route_endpoint(app, "/api/evals")()
                jobs = _route_endpoint(app, "/api/evals/{eval_slug}/jobs")(
                    "sample-task"
                )
                html = _route_endpoint(app, "/evals/{eval_slug}")("sample-task")

            self.assertEqual(evaluations[0]["trials"], 1)
            self.assertEqual(jobs[0]["trials"], 1)
            self.assertIn("job-001", html)

    def test_public_view_hides_private_transaction_jobs(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "private-job")
            _write_raw_job(bench_root, "sample-task", "release-job")
            view_path = bench_root / "evals/transactions/tooling/public-view.json"
            view_path.parent.mkdir(parents=True)
            _write_json(
                view_path,
                {
                    "schema_version": "compute-bazaar-bench.public-view.v1",
                    "release_id": "release-v1",
                    "managed_tasks": ["sample-task"],
                    "jobs": ["release-job"],
                    "job_metadata": {
                        "release-job": {
                            "execution_origin": "fresh_native_harbor",
                            "display_label": "Fresh native Harbor run",
                            "score_origin": "release_grader",
                        }
                    },
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            jobs = _route_endpoint(app, "/api/evals/{eval_slug}/jobs")("sample-task")

            self.assertEqual([item["run_id"] for item in jobs], ["release-job"])
            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "release-job"
            )
            metrics = {metric["label"]: metric for metric in detail["metrics"]}
            self.assertEqual(
                metrics["Execution origin"]["value"], "Fresh native Harbor run"
            )

    def test_public_view_hides_release_preflight_task_jobs(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "release-v1-model-001")
            _write_raw_job(
                bench_root,
                "private-model-route",
                "release-v1-model-route-preflight-001",
            )
            view_path = bench_root / "evals/transactions/tooling/public-view.json"
            _write_json(
                view_path,
                {
                    "schema_version": "compute-bazaar-bench.public-view.v1",
                    "release_id": "release-v1",
                    "managed_tasks": ["sample-task"],
                    "jobs": ["release-v1-model-001"],
                    "job_metadata": {
                        "release-v1-model-001": {
                            "execution_origin": "fresh_native_harbor",
                            "display_label": "Fresh native Harbor run",
                            "score_origin": "release_grader",
                        }
                    },
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            index = _route_endpoint(app, "/")()
            evaluations = _route_endpoint(app, "/api/evals")()

            self.assertNotIn("Private Model Route", index)
            self.assertNotIn(
                "private-model-route", {item["slug"] for item in evaluations}
            )

    def test_public_release_summary_powers_task_comparison_only(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "release-job")
            view_path = bench_root / "evals/transactions/tooling/public-view.json"
            _write_json(
                view_path,
                {
                    "schema_version": "compute-bazaar-bench.public-view.v1",
                    "release_id": "release-v1",
                    "protocol_sha256": "a" * 64,
                    "managed_tasks": ["sample-task"],
                    "jobs": ["release-job"],
                    "job_metadata": {
                        "release-job": {
                            "execution_origin": "fresh_native_harbor",
                            "display_label": "Fresh native Harbor run",
                            "score_origin": "release_grader",
                        }
                    },
                    "report": "release-v1",
                    "summary_path": (
                        "evals/transactions/results/release-v1.summary.json"
                    ),
                },
            )
            _write_json(
                bench_root / "evals/transactions/results/release-v1.summary.json",
                {
                    "schema_version": (
                        "compute-bazaar-bench.transactions.release-summary.v1"
                    ),
                    "release_id": "release-v1",
                    "protocol_sha256": "a" * 64,
                    "rows": [
                        {
                            "model": "Model A",
                            "job": "release-job",
                            "execution_label": "Fresh Harbor run",
                            "planned": 15,
                            "scored": 15,
                            "strict_all_pass": 0,
                            "strict_all_pass_rate": 0.0,
                            "criterion_pass_rate": 0.0,
                            "criterion_evaluation": "not_run_output_gate",
                            "equal_task_macro": 0.0,
                            "tasks": {
                                "sample-task": {
                                    "retained": 5,
                                    "all_pass": 0,
                                    "semantic": {"mean": 0.0},
                                }
                            },
                            "craft": {"good": 2, "mixed": 1, "poor": 0},
                            "telemetry": {
                                "median_agent_seconds": 12.0,
                                "median_input_tokens": 100,
                                "median_output_tokens": 20,
                                "agent_cost_usd": None,
                                "judge_cost_usd": None,
                                "modal_cost_usd": None,
                            },
                        },
                        {
                            "model": "Model B",
                            "job": "release-job",
                            "execution_label": "Earlier output, regraded",
                            "planned": 15,
                            "scored": 14,
                            "strict_all_pass": 0,
                            "strict_all_pass_rate": 0.0,
                            "criterion_pass_rate": 0.7,
                            "equal_task_macro": 0.72,
                            "tasks": {
                                "sample-task": {
                                    "retained": 5,
                                    "all_pass": 1,
                                    "semantic": {"mean": 0.72},
                                }
                            },
                            "craft": {"good": 1, "mixed": 2, "poor": 1},
                            "telemetry": {},
                        },
                    ],
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            html = _route_endpoint(app, "/evals/{eval_slug}")("sample-task")

            self.assertIn("Run outcomes", html)
            self.assertIn("OpenCode 1.0 + Model B", html)
            self.assertIn("72.0%", html)
            self.assertIn("1 of 5 passed", html)
            self.assertIn("Passed", html)
            self.assertIn("Incomplete", html)
            self.assertIn('class="comparison-picker"', html)
            self.assertIn(">Release v1</option>", html)
            self.assertIn("No semantic review", html)
            self.assertNotIn(">0.0%</strong>", html)
            self.assertNotIn("<h2>Results</h2>", html)
            self.assertNotIn("Document quality", html)

    def test_generic_benchmark_chart_is_visible_on_task_page(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            report_dir = bench_root / "jobs/reports/sample-task/runs/sample-comparison"
            _write_json(
                report_dir / "protocol.json",
                {
                    "models": [
                        {
                            "model": "mistral/model-a",
                            "observed_trials": 20,
                            "completed_rollouts": 17,
                            "reliability_targets_met": 10,
                            "mean_completed_failure_rate": 0.057,
                        }
                    ]
                },
            )
            _write_json(
                report_dir / "trials.json",
                [
                    {
                        "trial": {
                            "agent": "opencode",
                            "agent_version": "1.18.11",
                            "model": "mistral/model-a",
                        }
                    }
                ],
            )
            _write_json(
                bench_root / "evals/sample-suite/comparisons/sample.comparison.json",
                {
                    "schema_version": "compute-bazaar-bench.comparison-group.v1",
                    "id": "sample-comparison",
                    "label": "Sample comparison",
                    "tasks": ["sample-task"],
                    "source": {
                        "kind": "reliability-is-blind-report",
                        "job": "sample-comparison",
                    },
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            html = _route_endpoint(app, "/evals/{eval_slug}")("sample-task")

            self.assertIn("Sample comparison", html)
            self.assertIn("Book completion and reliability target", html)
            self.assertIn("10/20 target met", html)
            self.assertIn("17/20 completed", html)
            self.assertIn("OpenCode 1.18.11 + Model A", html)
            self.assertIn('class="benchmark-segment good"', html)
            self.assertIn('class="benchmark-segment neutral"', html)
            self.assertIn('class="comparison-picker"', html)
            self.assertIn(
                '<option value="/evals/sample-task?comparison=sample-comparison" selected>Sample comparison</option>',
                html,
            )

            _write_json(
                bench_root / "evals/sample-suite/comparisons/second.comparison.json",
                {
                    "schema_version": "compute-bazaar-bench.comparison-group.v1",
                    "id": "second-comparison",
                    "label": "Second comparison",
                    "tasks": ["sample-task"],
                    "source": {
                        "kind": "reliability-is-blind-report",
                        "job": "sample-comparison",
                    },
                },
            )
            html = _route_endpoint(app, "/evals/{eval_slug}")(
                "sample-task", "second-comparison"
            )

            self.assertIn('class="comparison-picker"', html)
            self.assertIn(
                '<option value="/evals/sample-task?comparison=second-comparison" selected>Second comparison</option>',
                html,
            )

    def test_one_off_job_does_not_create_a_comparison_group(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(
                bench_root,
                "sample-task",
                "one-off-job",
                jobs_subdir=None,
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            html = _route_endpoint(app, "/evals/{eval_slug}")("sample-task")

            self.assertIn("one-off-job", html)
            self.assertNotIn('class="benchmark"', html)

    def test_finished_top_level_multi_agent_job_is_a_comparison(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            job_id = "deepseek-vs-hy3"
            trial_ids = ["sample-task__deepseek", "sample-task__hy3"]
            _write_raw_job(
                bench_root,
                "sample-task",
                job_id,
                trial_ids=trial_ids,
                model_name=("openrouter/deepseek/deepseek-v4-flash-20260731:exacto"),
                jobs_subdir=None,
            )
            job_dir = bench_root / "jobs" / job_id
            _set_trial_agent(
                job_dir / trial_ids[1],
                "openrouter/tencent/hy3",
            )
            parent_lock = json.loads((job_dir / "lock.json").read_text())
            parent_lock["trials"][1] = json.loads(
                (job_dir / trial_ids[1] / "lock.json").read_text()
            )
            _write_json(job_dir / "lock.json", parent_lock)
            _write_json(
                job_dir / trial_ids[0] / "verifier" / "evidence.json",
                {
                    "result": {
                        "completion": 1,
                        "failure_rate": 0.04,
                        "target_met": True,
                    }
                },
            )
            _write_json(
                job_dir / trial_ids[1] / "verifier" / "evidence.json",
                {
                    "result": {
                        "completion": 1,
                        "failure_rate": 0.08,
                        "target_met": False,
                    }
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            html = _route_endpoint(app, "/evals/{eval_slug}")("sample-task")

            self.assertIn("DeepSeek V4 Flash 0731 vs HY3", html)
            self.assertIn("Book completion and reliability target", html)
            self.assertIn("OpenCode 1.0 + DeepSeek V4 Flash 0731", html)
            self.assertIn("OpenCode 1.0 + HY3", html)
            self.assertIn("1/1 target met", html)
            self.assertIn("0/1 target met", html)

    def test_legacy_raw_multi_agent_job_does_not_create_a_group(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            trial_ids = ["sample-task__a", "sample-task__b"]
            _write_raw_job(
                bench_root,
                "sample-task",
                "legacy-matrix-cell",
                trial_ids=trial_ids,
            )
            job_dir = bench_root / "jobs" / "raw" / "legacy-matrix-cell"
            _set_trial_agent(job_dir / trial_ids[1], "openrouter/tencent/hy3")
            parent_lock = json.loads((job_dir / "lock.json").read_text())
            parent_lock["trials"][1] = json.loads(
                (job_dir / trial_ids[1] / "lock.json").read_text()
            )
            _write_json(job_dir / "lock.json", parent_lock)

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            html = _route_endpoint(app, "/evals/{eval_slug}")("sample-task")

            self.assertIn("legacy-matrix-cell", html)
            self.assertNotIn('class="benchmark"', html)

    def test_multi_agent_job_without_vs_name_stays_an_ordinary_job(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            trial_ids = ["sample-task__a", "sample-task__b"]
            _write_raw_job(
                bench_root,
                "sample-task",
                "multi-agent-canary",
                trial_ids=trial_ids,
                jobs_subdir=None,
            )
            job_dir = bench_root / "jobs" / "multi-agent-canary"
            _set_trial_agent(job_dir / trial_ids[1], "openrouter/tencent/hy3")
            parent_lock = json.loads((job_dir / "lock.json").read_text())
            parent_lock["trials"][1] = json.loads(
                (job_dir / trial_ids[1] / "lock.json").read_text()
            )
            _write_json(job_dir / "lock.json", parent_lock)

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            html = _route_endpoint(app, "/evals/{eval_slug}")("sample-task")

            self.assertIn("multi-agent-canary", html)
            self.assertNotIn('class="benchmark"', html)

    def test_public_native_analysis_leads_with_strict_all_pass(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "release-job")
            report_dir = bench_root / "jobs" / "reports" / "release-job"
            _write_json(
                report_dir / "analysis.json",
                {
                    "schema_version": "compute-bazaar-bench.transactions.analysis.v1",
                    "job": "release-job",
                    "summary": {
                        "tasks": {
                            "sample-task": {
                                "attempted": 1,
                                "retained": 1,
                                "infrastructure_errors": 0,
                                "valid_docx": 1,
                                "all_pass": 0,
                                "semantic": {"mean": 0.5},
                                "harbor_reward": {"mean": 0.5},
                            }
                        }
                    },
                    "visual_summary": {
                        "sample-task": {"good": 0, "mixed": 0, "poor": 0}
                    },
                    "trials": [
                        {
                            "trial": "sample-task__abc",
                            "task": "sample-task",
                            "semantic_score": 0.5,
                            "semantic_passes": 1,
                            "semantic_criteria": 2,
                            "harbor_reward": 0.5,
                            "all_pass": 0,
                            "infrastructure_error": None,
                            "duration_seconds": 12.0,
                            "tokens": {"input": 100, "output": 20},
                            "criteria": [],
                            "trajectory": {},
                        }
                    ],
                },
            )
            _write_json(
                bench_root / "evals/transactions/tooling/public-view.json",
                {
                    "schema_version": "compute-bazaar-bench.public-view.v1",
                    "release_id": "release-v1",
                    "managed_tasks": ["sample-task"],
                    "jobs": ["release-job"],
                    "job_metadata": {
                        "release-job": {
                            "execution_origin": "fresh_native_harbor",
                            "display_label": "Fresh native Harbor run",
                            "score_origin": "release_grader",
                        }
                    },
                },
            )
            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "release-job"
            )

            self.assertEqual(detail["primary_score"]["label"], "Strict all-pass")
            self.assertEqual(detail["primary_score"]["value"], "0/1")
            metrics = {item["label"]: item["value"] for item in detail["metrics"]}
            self.assertEqual(metrics["Criterion pass"], "0.5000")

    def test_transaction_report_enriches_the_raw_job(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "job-001")
            report_dir = bench_root / "jobs" / "reports" / "job-001"
            report_dir.mkdir(parents=True)
            _write_json(
                report_dir / "analysis.json",
                {
                    "schema_version": "compute-bazaar-bench.transactions.analysis.v1",
                    "job": "job-001",
                    "summary": {
                        "tasks": {
                            "sample-task": {
                                "attempted": 1,
                                "retained": 1,
                                "infrastructure_errors": 0,
                                "valid_docx": 1,
                                "all_pass": 0,
                                "semantic": {"mean": 0.5},
                                "harbor_reward": {"mean": 0.75},
                            }
                        }
                    },
                    "visual_summary": {
                        "sample-task": {"good": 0, "mixed": 1, "poor": 0}
                    },
                    "trials": [
                        {
                            "trial": "sample-task__abc",
                            "task": "sample-task",
                            "semantic_score": 0.5,
                            "semantic_passes": 1,
                            "semantic_criteria": 2,
                            "harbor_reward": 0.75,
                            "all_pass": 0,
                            "infrastructure_error": None,
                            "duration_seconds": 12.0,
                            "tokens": {"input": 100, "output": 20},
                            "criteria": [{"id": "C-001", "value": 1}],
                            "trajectory": {"steps": 2},
                            "visual_review": {
                                "page_count": 3,
                                "practical_usability": "mixed",
                            },
                        }
                    ],
                },
            )
            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "job-001"
            )
            self.assertEqual(detail["primary_score"]["label"], "Mean semantic")
            self.assertEqual(detail["primary_score"]["value"], "0.5000")
            self.assertEqual(detail["trial_table"]["columns"][2]["label"], "Semantic")
            sections = detail["trials"]["sample-task__abc"]["sections"]
            self.assertIn("Document review", [section["title"] for section in sections])

    def test_invalid_output_is_explicit_in_job_and_trial(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "job-001")
            report_dir = bench_root / "jobs" / "reports" / "job-001"
            _write_json(
                report_dir / "analysis.json",
                {
                    "schema_version": "compute-bazaar-bench.transactions.analysis.v1",
                    "job": "job-001",
                    "summary": {
                        "tasks": {
                            "sample-task": {
                                "attempted": 1,
                                "retained": 1,
                                "infrastructure_errors": 0,
                                "valid_docx": 0,
                                "all_pass": 0,
                                "semantic": {"mean": 0.0},
                                "harbor_reward": {"mean": 0.0},
                            }
                        }
                    },
                    "visual_summary": {
                        "sample-task": {"good": 0, "mixed": 0, "poor": 0}
                    },
                    "trials": [
                        {
                            "trial": "sample-task__abc",
                            "task": "sample-task",
                            "semantic_score": 0.0,
                            "semantic_passes": 0,
                            "semantic_criteria": 2,
                            "harbor_reward": 0.0,
                            "all_pass": 0,
                            "infrastructure_error": None,
                            "agent_invalid_output": True,
                            "invalid_output_reason": (
                                "deliverable is not a valid DOCX archive"
                            ),
                            "duration_seconds": 12.0,
                            "tokens": {"input": 100, "output": 20},
                            "criteria": [],
                            "trajectory": {"steps": 2},
                        }
                    ],
                },
            )
            _write_json(
                bench_root / "evals/transactions/tooling/public-view.json",
                {
                    "schema_version": "compute-bazaar-bench.public-view.v1",
                    "release_id": "release-v1",
                    "managed_tasks": ["sample-task"],
                    "jobs": ["job-001"],
                    "job_metadata": {
                        "job-001": {
                            "execution_origin": "fresh_native_harbor",
                            "display_label": "Fresh native Harbor run",
                            "score_origin": "release_grader",
                        }
                    },
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "job-001"
            )

            status = detail["trial_table"]["rows"][0]["cells"]["status"]
            self.assertEqual(status["value"], "invalid output")
            self.assertEqual(status["tone"], "bad")
            row = detail["trial_table"]["rows"][0]["cells"]
            self.assertEqual(row["semantic"]["value"], "not judged")
            self.assertEqual(row["criteria"]["value"], "not judged")
            metrics = {item["label"]: item["value"] for item in detail["metrics"]}
            self.assertEqual(metrics["Criterion pass"], "not judged")
            trial = detail["trials"]["sample-task__abc"]
            self.assertIn(
                "Output failure", [section["title"] for section in trial["sections"]]
            )
            self.assertIn(
                "invalid DOCX", [metric["value"] for metric in trial["summary"]]
            )
            self.assertNotIn(
                "Resolved configuration",
                [section["title"] for section in trial["sections"]],
            )

    def test_public_timeout_is_excluded_without_raw_traceback(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "release-v1-model-001")
            trial_result_path = (
                bench_root
                / "jobs/raw/release-v1-model-001/sample-task__abc/result.json"
            )
            trial_result = json.loads(trial_result_path.read_text())
            trial_result["exception_info"] = {
                "exception_type": "AgentTimeoutError",
                "exception_message": "Agent timed out",
                "exception_traceback": "/Users/adams/private/path.py",
            }
            _write_json(trial_result_path, trial_result)
            report_dir = bench_root / "jobs/reports/release-v1-model-001"
            _write_json(
                report_dir / "analysis.json",
                {
                    "schema_version": "compute-bazaar-bench.transactions.analysis.v1",
                    "job": "release-v1-model-001",
                    "summary": {
                        "tasks": {
                            "sample-task": {
                                "attempted": 1,
                                "retained": 0,
                                "infrastructure_errors": 1,
                                "valid_docx": 0,
                                "all_pass": 0,
                                "semantic": {"mean": None},
                                "harbor_reward": {"mean": None},
                            }
                        }
                    },
                    "visual_summary": {
                        "sample-task": {"good": 0, "mixed": 0, "poor": 0}
                    },
                    "trials": [
                        {
                            "trial": "sample-task__abc",
                            "task": "sample-task",
                            "semantic_score": None,
                            "semantic_passes": None,
                            "semantic_criteria": None,
                            "harbor_reward": None,
                            "all_pass": None,
                            "infrastructure_error": (
                                "AgentTimeoutError at /Users/adams/private/path.py"
                            ),
                            "duration_seconds": 3600.0,
                            "criteria": [],
                            "trajectory": {},
                        }
                    ],
                },
            )
            _write_json(
                bench_root / "evals/transactions/tooling/public-view.json",
                {
                    "schema_version": "compute-bazaar-bench.public-view.v1",
                    "release_id": "release-v1",
                    "managed_tasks": ["sample-task"],
                    "jobs": ["release-v1-model-001"],
                    "job_metadata": {
                        "release-v1-model-001": {
                            "execution_origin": "fresh_native_harbor",
                            "display_label": "Fresh native Harbor run",
                            "score_origin": "release_grader",
                        }
                    },
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "release-v1-model-001"
            )

            row = detail["trial_table"]["rows"][0]["cells"]
            self.assertEqual(row["status"]["value"], "timeout excluded")
            trial = detail["trials"]["sample-task__abc"]
            titles = [section["title"] for section in trial["sections"]]
            self.assertIn("Timeout exclusion", titles)
            self.assertNotIn("Error", titles)
            self.assertNotIn("Resolved configuration", titles)
            self.assertNotIn("/Users/adams", json.dumps(trial))
            reward_metric = next(
                metric
                for metric in trial["summary"]
                if metric["label"] == "Harbor reward"
            )
            self.assertEqual(
                reward_metric["hint"],
                "Excluded under frozen one-hour timeout rule",
            )
            self.assertNotIn("Infrastructure-excluded", json.dumps(trial))

    def test_partial_report_never_hides_raw_trials(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(
                bench_root,
                "sample-task",
                "job-001",
                trial_ids=["sample-task__abc", "sample-task__def"],
            )
            report_dir = bench_root / "jobs" / "reports" / "job-001"
            report_dir.mkdir(parents=True)
            _write_json(
                report_dir / "analysis.json",
                {
                    "schema_version": "compute-bazaar-bench.transactions.analysis.v1",
                    "job": "job-001",
                    "summary": {
                        "tasks": {
                            "sample-task": {
                                "attempted": 1,
                                "retained": 1,
                                "semantic": {"mean": 0.5},
                                "harbor_reward": {"mean": 0.75},
                            }
                        }
                    },
                    "trials": [
                        {
                            "trial": "sample-task__abc",
                            "task": "sample-task",
                            "semantic_score": 0.5,
                            "semantic_passes": 1,
                            "semantic_criteria": 2,
                            "harbor_reward": 0.75,
                        }
                    ],
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "job-001"
            )

            rows = detail["trial_table"]["rows"]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["cells"]["trial"]["value"], "sample-task__def")
            self.assertEqual(rows[1]["cells"]["semantic"]["value"], "—")
            self.assertEqual(detail["metrics"][0]["value"], "2/2")
            self.assertEqual(
                detail["notices"][-1]["text"], "Analysis covers 1/2 raw trials"
            )

    def test_comparison_report_enriches_each_underlying_model_job(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "model-job-001")
            report_dir = bench_root / "jobs" / "reports" / "comparison-v1"
            report_dir.mkdir(parents=True)
            _write_json(
                report_dir / "analysis.json",
                {
                    "schema_version": (
                        "compute-bazaar-bench.transactions.comparison-analysis.v1"
                    ),
                    "models": {
                        "sample-model": {
                            "status": "official",
                            "job": "model-job-001",
                            "summary": {
                                "tasks": {
                                    "sample-task": {
                                        "attempted": 1,
                                        "retained": 1,
                                        "infrastructure_errors": 0,
                                        "valid_docx": 1,
                                        "all_pass": 0,
                                        "semantic": {"mean": 0.5},
                                        "harbor_reward": {"mean": 0.75},
                                    }
                                }
                            },
                            "records": [
                                {
                                    "trial": "sample-task__abc",
                                    "task": "sample-task",
                                    "semantic_score": 0.5,
                                    "semantic_passes": 1,
                                    "semantic_criteria": 2,
                                    "harbor_reward": 0.75,
                                    "all_pass": 0,
                                    "infrastructure_error": None,
                                    "duration_seconds": 12.0,
                                    "tokens": {"input": 100, "output": 20},
                                    "criteria": [],
                                    "trajectory": {},
                                    "visual_review": {
                                        "page_count": 2,
                                        "practical_usability": "good",
                                    },
                                }
                            ],
                        }
                    },
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "model-job-001"
            )

            self.assertEqual(detail["primary_score"]["label"], "Mean semantic")
            self.assertEqual(detail["primary_score"]["value"], "0.5000")
            metrics = {metric["label"]: metric for metric in detail["metrics"]}
            self.assertEqual(
                metrics["Document craft / 1 reviewed"]["value"],
                "1 good · 0 mixed · 0 poor",
            )

    def test_adjudication_report_keeps_original_and_amended_scores_adjacent(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "model-job-001")
            report_dir = bench_root / "jobs" / "reports" / "adjudication-v1"
            report_dir.mkdir(parents=True)
            original = {
                "semantic_score": 0.5,
                "semantic_passes": 1,
                "semantic_criteria": 2,
                "reward": 0.5,
                "all_pass": 0,
                "output_integrity": 1,
                "criteria": [],
            }
            amended = {
                **original,
                "semantic_score": 1.0,
                "semantic_passes": 2,
                "reward": 1.0,
                "all_pass": 1,
            }
            _write_json(
                report_dir / "analysis.json",
                {
                    "schema_version": (
                        "compute-bazaar-bench.transactions.adjudication-analysis.v1"
                    ),
                    "labels": {
                        "original": "Original frozen Harbor score (verifier v1)",
                        "amended": "Amended adjudicated score (verifier v2 replay)",
                    },
                    "models": {
                        "sample-model": {
                            "job": "model-job-001",
                            "original": {
                                "tasks": {
                                    "sample-task": {
                                        "retained": 1,
                                        "all_pass": 0,
                                        "semantic": {"mean": 0.5},
                                    }
                                }
                            },
                            "amended": {
                                "tasks": {
                                    "sample-task": {
                                        "retained": 1,
                                        "all_pass": 1,
                                        "semantic": {"mean": 1.0},
                                        "reward": {"mean": 1.0},
                                    }
                                }
                            },
                            "records": [
                                {
                                    "trial": "sample-task__abc",
                                    "task": "sample-task",
                                    "artifact_sha256": "a" * 64,
                                    "original": original,
                                    "amended": amended,
                                    "semantic_delta": 0.5,
                                    "criterion_transitions": {
                                        "fail_to_pass": 1,
                                        "pass_to_fail": 0,
                                    },
                                    "changed_criteria": [],
                                    "duration_seconds": 12.0,
                                    "trajectory": {},
                                    "visual_review": {
                                        "page_count": 2,
                                        "practical_usability": "good",
                                    },
                                }
                            ],
                        }
                    },
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "model-job-001"
            )

            self.assertEqual(detail["primary_score"]["label"], "Amended all pass")
            self.assertEqual(detail["primary_score"]["value"], "1/1")
            columns = [column["label"] for column in detail["trial_table"]["columns"]]
            self.assertIn("v1 semantic", columns)
            self.assertIn("v2 semantic", columns)
            row = detail["trial_table"]["rows"][0]["cells"]
            self.assertEqual(row["v1_semantic"]["value"], "0.5000")
            self.assertEqual(row["v2_semantic"]["value"], "1.0000")
            sections = detail["trials"]["sample-task__abc"]["sections"]
            self.assertIn(
                "Adjudication replay", [section["title"] for section in sections]
            )

    def test_public_adjudication_shows_release_score_without_private_v1(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "model-job-001")
            report_dir = bench_root / "jobs" / "reports" / "adjudication-v1"
            report_dir.mkdir(parents=True)
            original = {
                "semantic_score": 0.5,
                "semantic_passes": 1,
                "semantic_criteria": 2,
                "reward": 0.5,
                "all_pass": 0,
                "output_integrity": 1,
                "criteria": [],
            }
            amended = {
                **original,
                "semantic_score": 1.0,
                "semantic_passes": 2,
                "reward": 1.0,
                "all_pass": 1,
            }
            _write_json(
                report_dir / "analysis.json",
                {
                    "schema_version": (
                        "compute-bazaar-bench.transactions.adjudication-analysis.v1"
                    ),
                    "models": {
                        "sample-model": {
                            "job": "model-job-001",
                            "original": {
                                "tasks": {
                                    "sample-task": {
                                        "retained": 1,
                                        "all_pass": 0,
                                        "semantic": {"mean": 0.5},
                                    }
                                }
                            },
                            "amended": {
                                "tasks": {
                                    "sample-task": {
                                        "retained": 1,
                                        "all_pass": 1,
                                        "semantic": {"mean": 1.0},
                                        "reward": {"mean": 1.0},
                                    }
                                }
                            },
                            "records": [
                                {
                                    "trial": "sample-task__abc",
                                    "task": "sample-task",
                                    "artifact_sha256": "a" * 64,
                                    "original": original,
                                    "amended": amended,
                                    "duration_seconds": 12.0,
                                    "trajectory": {},
                                    "visual_review": {
                                        "page_count": 2,
                                        "practical_usability": "good",
                                    },
                                }
                            ],
                        }
                    },
                },
            )
            view_path = bench_root / "evals/transactions/tooling/public-view.json"
            view_path.parent.mkdir(parents=True)
            _write_json(
                view_path,
                {
                    "schema_version": "compute-bazaar-bench.public-view.v1",
                    "release_id": "release-v1",
                    "managed_tasks": ["sample-task"],
                    "jobs": ["model-job-001"],
                    "job_metadata": {
                        "model-job-001": {
                            "execution_origin": (
                                "original_harbor_output_final_checklist"
                            ),
                            "display_label": (
                                "Original Harbor output, final checklist"
                            ),
                            "score_origin": "final_checklist",
                            "agent_rerun": False,
                        }
                    },
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "model-job-001"
            )

            self.assertEqual(detail["primary_score"]["label"], "Runs passed")
            self.assertEqual(detail["primary_score"]["value"], "1/1")
            metrics = {metric["label"]: metric["value"] for metric in detail["metrics"]}
            self.assertEqual(metrics["Criterion pass rate"], "100.0%")
            self.assertEqual(metrics["Valid documents"], "1/1")
            self.assertEqual(
                [column["label"] for column in detail["trial_table"]["columns"]],
                [
                    "Trial",
                    "Status",
                    "Criterion pass rate",
                    "Criteria",
                    "Reward",
                    "Passed",
                    "Document review",
                    "Pages",
                    "Duration",
                ],
            )
            self.assertEqual(
                detail["trial_table"]["rows"][0]["cells"]["semantic"]["value"],
                "100.0%",
            )
            rendered = json.dumps(detail)
            self.assertNotIn("v1 semantic", rendered)
            self.assertNotIn("Original Harbor reward", rendered)
            self.assertIn("final rubric to the original DOCX", rendered)
            self.assertIn("The agent was not rerun", rendered)

    def test_comparison_overlay_keeps_infrastructure_out_of_semantic_results(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "model-job-001")
            report_dir = bench_root / "jobs" / "reports" / "comparison-v1"
            report_dir.mkdir(parents=True)
            _write_json(
                report_dir / "analysis.json",
                {
                    "schema_version": (
                        "compute-bazaar-bench.transactions.comparison-analysis.v1"
                    ),
                    "models": {
                        "sample-model": {
                            "status": "official",
                            "job": "model-job-001",
                            "summary": {
                                "tasks": {
                                    "sample-task": {
                                        "attempted": 1,
                                        "retained": 0,
                                        "infrastructure_errors": 1,
                                        "valid_docx": 0,
                                        "all_pass": 0,
                                        "semantic": {"mean": None},
                                        "harbor_reward": {"mean": None},
                                    }
                                }
                            },
                            "records": [
                                {
                                    "trial": "sample-task__abc",
                                    "task": "sample-task",
                                    "semantic_score": None,
                                    "semantic_passes": None,
                                    "semantic_criteria": None,
                                    "harbor_reward": None,
                                    "all_pass": None,
                                    "infrastructure_error": {
                                        "kind": "agent_timeout",
                                        "message": "Agent timed out",
                                    },
                                    "duration_seconds": 3600.0,
                                    "criteria": [],
                                    "trajectory": {},
                                    "visual_review": {
                                        "page_count": 2,
                                        "practical_usability": "poor",
                                    },
                                }
                            ],
                        }
                    },
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "model-job-001"
            )

            row = detail["trial_table"]["rows"][0]["cells"]
            self.assertEqual(row["status"]["value"], "error")
            for key in ("semantic", "criteria", "reward", "all_pass"):
                self.assertEqual(row[key]["value"], "—")
            self.assertEqual(row["craft"]["value"], "poor")

            trial = detail["trials"]["sample-task__abc"]
            trial_metrics = {
                metric["label"]: metric["value"] for metric in trial["summary"]
            }
            self.assertEqual(trial_metrics["Harbor reward"], "—")
            section_titles = [section["title"] for section in trial["sections"]]
            self.assertIn("Run exclusion", section_titles)
            self.assertNotIn("Rewards", section_titles)

            metrics = {metric["label"]: metric for metric in detail["metrics"]}
            self.assertEqual(metrics["Terminal trials"]["value"], "1/1")
            self.assertEqual(metrics["Retained trials"]["value"], "0/1")
            self.assertEqual(
                metrics["Document craft / 1 reviewed"]["value"],
                "0 good · 0 mixed · 1 poor",
            )
            self.assertIn(
                "excluded under the frozen runtime and timeout rules",
                detail["notices"][-1]["text"],
            )

    def test_invalidated_comparison_job_is_preserved_but_unscored(self) -> None:
        with TemporaryDirectory() as temporary:
            bench_root = Path(temporary) / "bench"
            _write_task(bench_root, "sample-task")
            _write_raw_job(bench_root, "sample-task", "invalidated-job-001")
            report_dir = bench_root / "jobs" / "reports" / "comparison-v1"
            report_dir.mkdir(parents=True)
            _write_json(
                report_dir / "analysis.json",
                {
                    "schema_version": (
                        "compute-bazaar-bench.transactions.comparison-analysis.v1"
                    ),
                    "models": {
                        "sample-model": {
                            "status": "official_invalidated",
                            "job": "invalidated-job-001",
                            "exclusion_reason": "Evaluation budget was exhausted.",
                            "summary": None,
                            "records": [],
                        }
                    },
                },
            )

            app = create_app(bench_root / "jobs" / "reports", bench_root=bench_root)
            jobs = _route_endpoint(app, "/api/evals/{eval_slug}/jobs")("sample-task")
            self.assertEqual(jobs[0]["score"].label, "Comparison status")
            self.assertEqual(jobs[0]["score"].value, "Unscored")

            detail = _route_endpoint(app, "/api/evals/{eval_slug}/jobs/{run_id}")(
                "sample-task", "invalidated-job-001"
            )
            self.assertEqual(detail["primary_score"]["label"], "Comparison status")
            self.assertEqual(detail["primary_score"]["value"], "Unscored")
            self.assertEqual(
                detail["agent_table"]["rows"][0]["cells"]["reward"]["value"],
                "—",
            )
            self.assertEqual(
                detail["trial_table"]["rows"][0]["cells"]["reward"]["value"],
                "—",
            )
            trial = detail["trials"]["sample-task__abc"]
            scores = {metric["label"]: metric["value"] for metric in trial["summary"]}
            self.assertEqual(scores["Comparison score"], "—")
            self.assertEqual(trial["sections"][0]["title"], "Comparison status")
            self.assertIn(
                "Excluded from the scored comparison",
                detail["notices"][0]["text"],
            )


def _route_endpoint(app, path: str):
    return next(route.endpoint for route in app.routes if route.path == path)


def _write_task(bench_root: Path, slug: str) -> None:
    task_root = bench_root / "evals" / "transactions" / slug
    task_root.mkdir(parents=True)
    (task_root / "instruction.md").write_text("Produce the result.\n")
    (task_root / "task.toml").write_text(
        textwrap.dedent(
            f"""
            schema_version = "1.3"

            [task]
            name = "gustofied/{slug}"
            description = "A sample task."

            [metadata]
            domain = "transactions"
            """
        ).strip()
        + "\n"
    )


def _write_raw_job(
    bench_root: Path,
    slug: str,
    job_id: str,
    *,
    trial_ids: list[str] | None = None,
    started_at: str = "2026-01-01T00:00:00Z",
    finished_at: str = "2026-01-01T00:00:12Z",
    agent_name: str = "opencode",
    model_name: str = "mistral/model",
    agent_version: str = "1.0",
    jobs_subdir: str | None = "raw",
) -> None:
    jobs_dir = bench_root / "jobs"
    if jobs_subdir:
        jobs_dir /= jobs_subdir
    job_dir = jobs_dir / job_id
    trial_ids = trial_ids or [f"{slug}__abc"]
    provider, _, model = model_name.partition("/")
    trial_lock = {
        "task": {"name": slug},
        "agent": {
            "name": agent_name,
            "model_name": model_name,
            "kwargs": {"version": agent_version},
        },
    }
    _write_json(job_dir / "lock.json", {"trials": [trial_lock] * len(trial_ids)})
    _write_json(
        job_dir / "result.json",
        {
            "started_at": started_at,
            "finished_at": finished_at,
            "n_total_trials": len(trial_ids),
            "stats": {"n_completed_trials": len(trial_ids), "n_retries": 0},
        },
    )
    for trial_id in trial_ids:
        trial_dir = job_dir / trial_id
        (trial_dir / "artifacts").mkdir(parents=True)
        (trial_dir / "agent").mkdir()
        _write_json(trial_dir / "lock.json", trial_lock)
        _write_json(
            trial_dir / "result.json",
            {
                "task_name": f"gustofied/{slug}",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:12Z",
                "agent_info": {
                    "name": agent_name,
                    "version": agent_version,
                    "model_info": {"provider": provider, "name": model or provider},
                },
                "agent_result": {
                    "n_input_tokens": 100,
                    "n_output_tokens": 20,
                    "cost_usd": 0.01,
                },
                "verifier_result": {"rewards": {"reward": 0.75}},
                "exception_info": None,
            },
        )
        _write_json(trial_dir / "artifacts" / "manifest.json", [])
        _write_json(
            trial_dir / "agent" / "trajectory.json",
            {
                "schema_version": "ATIF-v1.7",
                "final_metrics": {"total_steps": 2},
                "steps": [
                    {"step_id": 1, "source": "user", "message": "Do the work."},
                    {
                        "step_id": 2,
                        "source": "agent",
                        "message": "",
                        "tool_calls": [
                            {
                                "function_name": "write",
                                "arguments": {"content": "PK\x00binary document"},
                            }
                        ],
                        "observation": "Done",
                        "metrics": {"prompt_tokens": 10, "completion_tokens": 2},
                    },
                ],
            },
        )


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _set_trial_agent(trial_dir: Path, model_name: str) -> None:
    lock = json.loads((trial_dir / "lock.json").read_text())
    lock["agent"]["model_name"] = model_name
    _write_json(trial_dir / "lock.json", lock)

    result = json.loads((trial_dir / "result.json").read_text())
    provider, _, model = model_name.partition("/")
    result["agent_info"]["model_info"] = {
        "provider": provider,
        "name": model or provider,
    }
    _write_json(trial_dir / "result.json", result)


if __name__ == "__main__":
    unittest.main()
