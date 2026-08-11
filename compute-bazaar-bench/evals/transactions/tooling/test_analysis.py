from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from analysis import classify_trial, inspect_trajectory
from comparison import (
    attach_visual_review,
    validate_terminal_job,
)


ROOT = Path(__file__).resolve().parents[4]
TRANSACTIONS = ROOT / "compute-bazaar-bench" / "evals" / "transactions"
RAW_JOBS = ROOT / "compute-bazaar-bench" / "jobs" / "raw"


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


class JobValidationTests(unittest.TestCase):
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

    def test_actual_retained_agent_timeout_is_infrastructure(self) -> None:
        trial = (
            RAW_JOBS
            / "transactions-comparison-v1-mistral-small-2603-canary-001"
            / "normalize-buyer-mandate__YThRoHz"
        )
        if not trial.exists():
            self.skipTest("local retained Harbor timeout is unavailable")
        task = {
            "name": "normalize-buyer-mandate",
            "deliverable": "buyer-mandate-brief.docx",
            "semantic_criteria": 56,
            "matter_documents": [],
        }
        agent = {
            "name": "opencode",
            "version": "1.18.11",
            "model": "openrouter/mistralai/mistral-small-2603:exacto",
        }
        record = classify_trial(
            trial, task, agent, missing_artifact_as_invalid=True
        )
        self.assertIn("AgentTimeoutError", record["infrastructure_error"])
        self.assertFalse(record["agent_invalid_output"])

if __name__ == "__main__":
    unittest.main()
