from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from analysis import classify_trial, inspect_trajectory, load_object, sha256
from comparison import (
    PRECOMMIT_GIT_COMMIT,
    REPAIR_FIXTURES,
    REPAIR_GIT_COMMIT,
    attach_visual_review,
    validate_commitment,
    validate_run_record,
    validate_terminal_job,
)


ROOT = Path(__file__).resolve().parents[4]
TRANSACTIONS = ROOT / "compute-bazaar-bench" / "evals" / "transactions"
PROTOCOLS = TRANSACTIONS / "protocols"
ARCHIVE_PROTOCOLS = TRANSACTIONS / "internal" / "archive" / "protocols"
RAW_JOBS = ROOT / "compute-bazaar-bench" / "jobs" / "raw"
REPORTS = ROOT / "compute-bazaar-bench" / "jobs" / "reports"


def official_accounting(
    protocol: dict, launched_keys: set[str], selected_keys: set[str]
) -> dict[str, int]:
    attempts_per_model = (
        len(protocol["tasks"])
        * protocol["official_run"]["attempts_per_task"]
    )
    return {
        "frozen_planned_trials": protocol["official_run"]["planned_trials_total"],
        "withheld_after_canary": (
            len(protocol["models"]) - len(launched_keys)
        )
        * attempts_per_model,
        "launched_trials": len(launched_keys) * attempts_per_model,
        "invalidated_job_trials": (
            len(launched_keys) - len(selected_keys)
        )
        * attempts_per_model,
        "selected_official_trials": len(selected_keys) * attempts_per_model,
    }


class TrajectoryIndicatorTests(unittest.TestCase):
    agent = {"name": "opencode", "version": "1.18.11", "model": "test/model"}

    def inspect_command(self, command: str) -> dict:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "trajectory.json"
            path.write_text(
                json.dumps(
                    {
                        "agent": {
                            "name": self.agent["name"],
                            "version": self.agent["version"],
                            "model_name": self.agent["model"],
                        },
                        "steps": [
                            {"source": "user"},
                            {
                                "source": "agent",
                                "tool_calls": [
                                    {
                                        "function_name": "bash",
                                        "arguments": {"command": command},
                                    }
                                ],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return inspect_trajectory(path, "deliverable.docx", self.agent)

    def test_render_tool_probe_is_not_an_output_render(self) -> None:
        result = self.inspect_command("which libreoffice || which soffice || true")
        self.assertTrue(result["attempted_visual_render"])
        self.assertFalse(result["output_visual_render_invocation"])

    def test_deliverable_render_command_is_an_output_render(self) -> None:
        result = self.inspect_command(
            "libreoffice --headless --convert-to pdf /app/deliverable.docx"
        )
        self.assertTrue(result["output_visual_render_invocation"])


class CraftAttachmentTests(unittest.TestCase):
    def test_known_infrastructure_artifact_may_receive_craft_review(self) -> None:
        model_runs = {
            "model": {
                "records": [
                    {"trial": "retained", "artifact_status_ok": True},
                    {"trial": "infra", "artifact_status_ok": None},
                ]
            }
        }
        rubric = {
            "criteria": [{"id": "render-success", "critical": True}]
        }
        review = {
            "trials": {
                key: {
                    "page_count": 1,
                    "criterion_values": {"render-success": True},
                    "practical_usability": "good",
                }
                for key in ("model/retained", "model/infra")
            }
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.json"
            path.write_text(json.dumps(review), encoding="utf-8")
            attach_visual_review(model_runs, path, rubric)
        self.assertIn("visual_review", model_runs["model"]["records"][1])

    def test_unknown_craft_review_trial_fails_closed(self) -> None:
        model_runs = {
            "model": {
                "records": [{"trial": "retained", "artifact_status_ok": True}]
            }
        }
        rubric = {
            "criteria": [{"id": "render-success", "critical": True}]
        }
        review = {
            "trials": {
                "model/retained": {
                    "page_count": 1,
                    "criterion_values": {"render-success": True},
                    "practical_usability": "good",
                },
                "model/unknown": {
                    "page_count": 1,
                    "criterion_values": {"render-success": True},
                    "practical_usability": "good",
                },
            }
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.json"
            path.write_text(json.dumps(review), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "visual review trial mismatch"):
                attach_visual_review(model_runs, path, rubric)


class ComparisonProtocolTests(unittest.TestCase):
    def test_comparison_commitment_is_self_consistent(self) -> None:
        protocol = validate_commitment(
            PROTOCOLS / "transactions-comparison-v1.commitment.json"
        )
        self.assertEqual(len(protocol["models"]), 5)
        self.assertEqual(protocol["official_run"]["planned_trials_total"], 75)

    def test_run_record_preserves_failed_canaries_before_accepted_replacement(
        self,
    ) -> None:
        protocol_path = PROTOCOLS / "transactions-comparison-v1.commitment.json"
        protocol = validate_commitment(protocol_path)
        canary_jobs = {}
        canary_history = {}
        official_jobs = {}
        official_history = {}
        for model in protocol["models"]:
            key = model["key"]
            canary_jobs[key] = model["canary_job"]
            canary_history[key] = [
                {"job": model["canary_job"], "status": "accepted"}
            ]
            official_jobs[key] = model["official_job"]
            official_history[key] = [
                {"job": model["official_job"], "status": "accepted"}
            ]
        deepseek = protocol["models"][0]
        stem = deepseek["canary_job"][:-3]
        canary_jobs[deepseek["key"]] = f"{stem}003"
        canary_history[deepseek["key"]] = [
            {
                "job": f"{stem}001",
                "status": "failed",
                "failure": "Modal DNS setup failure",
            },
            {
                "job": f"{stem}002",
                "status": "failed",
                "failure": "OpenRouter upstream provider failure",
            },
            {"job": f"{stem}003", "status": "accepted"},
        ]
        record = {
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": sha256(protocol_path),
            "precommit_git_commit": PRECOMMIT_GIT_COMMIT,
            "reproducibility_repair": {
                "git_commit": REPAIR_GIT_COMMIT,
                "fixtures": REPAIR_FIXTURES,
            },
            "canary_jobs": canary_jobs,
            "canary_history": canary_history,
            "official_jobs": official_jobs,
            "official_history": official_history,
            "official_launch_order": protocol["official_run"]["job_order"],
            "official_accounting": official_accounting(
                protocol, set(official_jobs), set(official_jobs)
            ),
            "official_lock_sha256": {
                model["key"]: "0" * 64 for model in protocol["models"]
            },
        }

        validate_run_record(record, protocol_path, protocol)

        record["canary_jobs"][deepseek["key"]] = f"{stem}002"
        with self.assertRaisesRegex(Exception, "accepted canary mismatch"):
            validate_run_record(record, protocol_path, protocol)

    def test_run_record_can_block_a_model_after_failed_canary(self) -> None:
        protocol_path = PROTOCOLS / "transactions-comparison-v1.commitment.json"
        protocol = validate_commitment(protocol_path)
        blocked_key = protocol["models"][-1]["key"]
        canary_jobs = {}
        canary_history = {}
        official_jobs = {}
        official_history = {}
        for model in protocol["models"]:
            key = model["key"]
            if key == blocked_key:
                canary_history[key] = [
                    {
                        "job": model["canary_job"],
                        "status": "failed",
                        "failure": "invalid deliverables and agent timeout",
                    }
                ]
                continue
            canary_jobs[key] = model["canary_job"]
            canary_history[key] = [
                {"job": model["canary_job"], "status": "accepted"}
            ]
            official_jobs[key] = model["official_job"]
            official_history[key] = [
                {"job": model["official_job"], "status": "accepted"}
            ]
        record = {
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": sha256(protocol_path),
            "precommit_git_commit": PRECOMMIT_GIT_COMMIT,
            "reproducibility_repair": {
                "git_commit": REPAIR_GIT_COMMIT,
                "fixtures": REPAIR_FIXTURES,
            },
            "canary_jobs": canary_jobs,
            "canary_history": canary_history,
            "official_jobs": official_jobs,
            "official_history": official_history,
            "official_launch_order": [
                key
                for key in protocol["official_run"]["job_order"]
                if key != blocked_key
            ],
            "official_accounting": official_accounting(
                protocol, set(official_jobs), set(official_jobs)
            ),
            "official_lock_sha256": {key: "0" * 64 for key in official_jobs},
        }

        validate_run_record(record, protocol_path, protocol)

    def test_run_record_accepts_complete_superseding_official_job(self) -> None:
        protocol_path = PROTOCOLS / "transactions-comparison-v1.commitment.json"
        protocol = validate_commitment(protocol_path)
        canary_jobs = {}
        canary_history = {}
        official_jobs = {}
        official_history = {}
        lock_hashes = {}
        for model in protocol["models"]:
            key = model["key"]
            if key == "mistral-small-2603":
                canary_history[key] = [
                    {
                        "job": model["canary_job"],
                        "status": "failed",
                        "failure": "canary blocked",
                    }
                ]
                continue
            canary_jobs[key] = model["canary_job"]
            canary_history[key] = [
                {"job": model["canary_job"], "status": "accepted"}
            ]
            selected = model["official_job"]
            history = [{"job": selected, "status": "accepted"}]
            if key == "claude-sonnet-4.6":
                selected = f"{model['official_job'][:-3]}002"
                history = [
                    {
                        "job": model["official_job"],
                        "status": "invalidated",
                        "failure": "OpenRouter credits exhausted",
                    },
                    {"job": selected, "status": "accepted"},
                ]
            official_jobs[key] = selected
            official_history[key] = history
            lock_hashes[key] = "0" * 64
        record = {
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": sha256(protocol_path),
            "precommit_git_commit": PRECOMMIT_GIT_COMMIT,
            "reproducibility_repair": {
                "git_commit": REPAIR_GIT_COMMIT,
                "fixtures": REPAIR_FIXTURES,
            },
            "canary_jobs": canary_jobs,
            "canary_history": canary_history,
            "official_jobs": official_jobs,
            "official_history": official_history,
            "official_launch_order": [
                key
                for key in protocol["official_run"]["job_order"]
                if key != "mistral-small-2603"
            ],
            "official_accounting": official_accounting(
                protocol, set(official_history), set(official_jobs)
            ),
            "official_lock_sha256": lock_hashes,
        }

        validate_run_record(record, protocol_path, protocol)

    def test_run_record_accepts_invalidated_official_job_without_replacement(
        self,
    ) -> None:
        protocol_path = PROTOCOLS / "transactions-comparison-v1.commitment.json"
        protocol = validate_commitment(protocol_path)
        invalidated_key = "claude-sonnet-4.6"
        blocked_key = "mistral-small-2603"
        canary_jobs = {}
        canary_history = {}
        official_jobs = {}
        official_history = {}
        lock_hashes = {}
        for model in protocol["models"]:
            key = model["key"]
            if key == blocked_key:
                canary_history[key] = [
                    {
                        "job": model["canary_job"],
                        "status": "failed",
                        "failure": "canary blocked",
                    }
                ]
                continue
            canary_jobs[key] = model["canary_job"]
            canary_history[key] = [
                {"job": model["canary_job"], "status": "accepted"}
            ]
            lock_hashes[key] = "0" * 64
            if key == invalidated_key:
                official_history[key] = [
                    {
                        "job": model["official_job"],
                        "status": "invalidated",
                        "failure": "evaluation budget exhausted",
                    }
                ]
                continue
            official_jobs[key] = model["official_job"]
            official_history[key] = [
                {"job": model["official_job"], "status": "accepted"}
            ]
        record = {
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": sha256(protocol_path),
            "precommit_git_commit": PRECOMMIT_GIT_COMMIT,
            "reproducibility_repair": {
                "git_commit": REPAIR_GIT_COMMIT,
                "fixtures": REPAIR_FIXTURES,
            },
            "canary_jobs": canary_jobs,
            "canary_history": canary_history,
            "official_jobs": official_jobs,
            "official_history": official_history,
            "official_launch_order": [
                key
                for key in protocol["official_run"]["job_order"]
                if key != blocked_key
            ],
            "official_accounting": official_accounting(
                protocol, set(official_history), set(official_jobs)
            ),
            "official_lock_sha256": lock_hashes,
        }

        validate_run_record(record, protocol_path, protocol)

        record["official_jobs"][invalidated_key] = protocol["models"][3][
            "official_job"
        ]
        with self.assertRaisesRegex(Exception, "invalidated official job selected"):
            validate_run_record(record, protocol_path, protocol)

    def test_unfinished_job_cannot_be_analyzed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "result.json").write_text(
                json.dumps(
                    {
                        "finished_at": None,
                        "n_total_trials": 3,
                        "stats": {
                            "n_completed_trials": 2,
                            "n_errored_trials": 0,
                            "n_running_trials": 1,
                            "n_pending_trials": 0,
                            "n_cancelled_trials": 0,
                            "n_retries": 0,
                        },
                    }
                )
            )
            with self.assertRaisesRegex(Exception, "not terminal"):
                validate_terminal_job(root, 3)

    def test_harbor_error_count_is_a_subset_of_completed_trials(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "result.json").write_text(
                json.dumps(
                    {
                        "finished_at": "2026-08-10T00:01:00Z",
                        "n_total_trials": 3,
                        "stats": {
                            "n_completed_trials": 3,
                            "n_errored_trials": 1,
                            "n_running_trials": 0,
                            "n_pending_trials": 0,
                            "n_cancelled_trials": 0,
                            "n_retries": 0,
                        },
                    }
                )
            )
            result = validate_terminal_job(root, 3)
        self.assertEqual(result["stats"]["n_errored_trials"], 1)


class ArtifactClassificationTests(unittest.TestCase):
    task = {
        "name": "synthetic-task",
        "deliverable": "output.docx",
        "semantic_criteria": 1,
        "matter_documents": [],
    }
    agent = {
        "name": "opencode",
        "version": "1.18.11",
        "model": "openrouter/example/model:exacto",
    }

    def build_trial(self, root: Path, log: str) -> Path:
        trial = root / "synthetic-task__trial"
        (trial / "artifacts").mkdir(parents=True)
        (trial / "verifier").mkdir()
        (trial / "agent").mkdir()
        result = {
            "task_name": "gustofied/synthetic-task",
            "started_at": "2026-08-10T00:00:00Z",
            "finished_at": "2026-08-10T00:00:30Z",
            "agent_execution": {
                "started_at": "2026-08-10T00:00:01Z",
                "finished_at": "2026-08-10T00:00:20Z",
            },
            "verifier": {
                "started_at": "2026-08-10T00:00:21Z",
                "finished_at": "2026-08-10T00:00:30Z",
            },
            "agent_info": {
                "name": "opencode",
                "version": "1.18.11",
                "model_info": {
                    "provider": "openrouter",
                    "name": "example/model:exacto",
                },
            },
            "agent_result": {
                "n_input_tokens": 10,
                "n_cache_tokens": 0,
                "n_output_tokens": 2,
                "cost_usd": 0.01,
            },
            "exception_info": None,
        }
        trajectory = {
            "agent": {
                "name": "opencode",
                "version": "1.18.11",
                "model_name": "openrouter/example/model:exacto",
            },
            "steps": [
                {"source": "user", "message": "Produce output.docx"},
                {"source": "agent", "message": "Done", "tool_calls": []},
            ],
        }
        manifest = [
            {
                "source": "/app/output.docx",
                "destination": "artifacts/app/output.docx",
                "type": "file",
                "status": "failed",
                "service": None,
            }
        ]
        reward = {"reward": 0.0, "all_pass": 0.0, "output-integrity": 0.0}
        details = {
            "failure_kind": "invalid_deliverable",
            "output-integrity": {"criteria": []},
        }
        (trial / "result.json").write_text(json.dumps(result))
        (trial / "agent" / "trajectory.json").write_text(json.dumps(trajectory))
        (trial / "artifacts" / "manifest.json").write_text(json.dumps(manifest))
        (trial / "verifier" / "reward.json").write_text(json.dumps(reward))
        (trial / "verifier" / "reward-details.json").write_text(json.dumps(details))
        (trial / "trial.log").write_text(log)
        return trial

    def test_unknown_artifact_failure_remains_infrastructure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            trial = self.build_trial(Path(temp), "artifact collection failed")
            record = classify_trial(
                trial, self.task, self.agent, missing_artifact_as_invalid=True
            )
        self.assertIsNotNone(record["infrastructure_error"])
        self.assertFalse(record["agent_invalid_output"])

    def test_positive_missing_output_evidence_is_agent_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            trial = self.build_trial(
                Path(temp),
                "FileNotFoundError: /app/output.docx: no such file or directory",
            )
            record = classify_trial(
                trial, self.task, self.agent, missing_artifact_as_invalid=True
            )
        self.assertIsNone(record["infrastructure_error"])
        self.assertTrue(record["agent_invalid_output"])
        self.assertEqual(record["semantic_score"], 0.0)

    def test_verifier_confirmed_missing_output_is_agent_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            trial = self.build_trial(Path(temp), "artifact collection failed")
            details_path = trial / "verifier" / "reward-details.json"
            details = json.loads(details_path.read_text())
            details["message"] = "required deliverable not produced: output.docx"
            details_path.write_text(json.dumps(details))
            record = classify_trial(
                trial, self.task, self.agent, missing_artifact_as_invalid=True
            )
        self.assertIsNone(record["infrastructure_error"])
        self.assertTrue(record["agent_invalid_output"])
        self.assertEqual(record["semantic_score"], 0.0)

    def test_old_analyzer_default_keeps_missing_artifact_as_infrastructure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            trial = self.build_trial(
                Path(temp),
                "FileNotFoundError: /app/output.docx: no such file or directory",
            )
            record = classify_trial(trial, self.task, self.agent)
        self.assertIsNotNone(record["infrastructure_error"])
        self.assertFalse(record["agent_invalid_output"])

    def test_actual_retained_modal_collection_failure_is_infrastructure(self) -> None:
        trial = (
            RAW_JOBS
            / "transactions-v1-mistral-medium-001"
            / "normalize-buyer-mandate__iGEmM5V"
        )
        if not trial.exists():
            self.skipTest("local retained Harbor failure is unavailable")
        protocol = load_object(
            ARCHIVE_PROTOCOLS / "transactions-v1-mistral-medium.commitment.json"
        )
        task = next(
            item
            for item in protocol["tasks"]
            if item["name"] == "normalize-buyer-mandate"
        )
        record = classify_trial(
            trial, task, protocol["agent"], missing_artifact_as_invalid=True
        )
        self.assertIsNotNone(record["infrastructure_error"])
        self.assertFalse(record["agent_invalid_output"])

    def test_actual_retained_agent_timeout_is_infrastructure(self) -> None:
        trial = (
            RAW_JOBS
            / "transactions-comparison-v1-mistral-small-2603-canary-001"
            / "normalize-buyer-mandate__YThRoHz"
        )
        if not trial.exists():
            self.skipTest("local retained Harbor timeout is unavailable")
        protocol = load_object(
            PROTOCOLS / "transactions-comparison-v1.commitment.json"
        )
        task = next(
            item
            for item in protocol["tasks"]
            if item["name"] == "normalize-buyer-mandate"
        )
        agent = {
            "name": protocol["agent"]["name"],
            "version": protocol["agent"]["version"],
            "model": next(
                model["agent_model"]
                for model in protocol["models"]
                if model["key"] == "mistral-small-2603"
            ),
        }
        record = classify_trial(
            trial, task, agent, missing_artifact_as_invalid=True
        )
        self.assertIn("AgentTimeoutError", record["infrastructure_error"])
        self.assertFalse(record["agent_invalid_output"])


class ExistingAnalyzerRegressionTests(unittest.TestCase):
    def test_existing_v1_report_is_unchanged(self) -> None:
        job = RAW_JOBS / "transactions-v1-mistral-medium-002"
        expected = REPORTS / "transactions-v1-mistral-medium-002" / "report.md"
        if not job.exists() or not expected.exists():
            self.skipTest("local Transactions v1 baseline is unavailable")
        with tempfile.TemporaryDirectory() as temp:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(TRANSACTIONS / "tooling" / "analysis.py"),
                    str(job),
                    "--protocol",
                    str(
                        ARCHIVE_PROTOCOLS
                        / "transactions-v1-mistral-medium.commitment.json"
                    ),
                    "--run-record",
                    str(ARCHIVE_PROTOCOLS / "transactions-v1-mistral-medium.run.json"),
                    "--visual-review",
                    str(
                        TRANSACTIONS
                        / "internal"
                        / "archive"
                        / "results"
                        / "transactions-v1-mistral-medium.visual-review.json"
                    ),
                    "--output-dir",
                    temp,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("infrastructure_errors=0", completed.stdout)
            actual = (Path(temp) / "report.md").read_text()
        self.assertEqual(actual, expected.read_text())


if __name__ == "__main__":
    unittest.main()
