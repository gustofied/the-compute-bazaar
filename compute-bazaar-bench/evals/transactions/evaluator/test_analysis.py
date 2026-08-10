from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from analysis import classify_trial, load_object
from comparison import validate_commitment


ROOT = Path(__file__).resolve().parents[4]
TRANSACTIONS = ROOT / "compute-bazaar-bench" / "evals" / "transactions"
PROTOCOLS = TRANSACTIONS / "protocols"
RAW_JOBS = ROOT / "compute-bazaar-bench" / "jobs" / "raw"
REPORTS = ROOT / "compute-bazaar-bench" / "jobs" / "reports"


class ComparisonProtocolTests(unittest.TestCase):
    def test_comparison_commitment_is_self_consistent(self) -> None:
        protocol = validate_commitment(
            PROTOCOLS / "transactions-comparison-v1.commitment.json"
        )
        self.assertEqual(len(protocol["models"]), 5)
        self.assertEqual(protocol["official_run"]["planned_trials_total"], 75)


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
            PROTOCOLS / "transactions-v1-mistral-medium.commitment.json"
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
                    str(TRANSACTIONS / "evaluator" / "analysis.py"),
                    str(job),
                    "--protocol",
                    str(PROTOCOLS / "transactions-v1-mistral-medium.commitment.json"),
                    "--run-record",
                    str(PROTOCOLS / "transactions-v1-mistral-medium.run.json"),
                    "--visual-review",
                    str(
                        TRANSACTIONS
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
