from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common import (  # noqa: E402
    DELIVERABLES,
    ORIGINAL_TASK_DIGESTS,
    TASK_NAMES,
    AdjudicationError,
    load_json,
    sha256_file,
    task_content_digest,
    tree_manifest,
)
from prepare import read_criteria  # noqa: E402
from openrouter_gate import evaluate_gate  # noqa: E402
import replay as replay_module  # noqa: E402
from analyze_replay import (  # noqa: E402
    DEFAULT_ATTEMPT,
    validate_protocol_amendment,
)
from replay import (  # noqa: E402
    RAW_JOBS,
    MockVerifierRuntime,
    RuntimeResult,
    complete_mock_reward,
    execute_replay,
    has_nested_error,
    replay_one,
    validate_commitment,
    validate_docx,
    validate_reward_files,
)


COMMITMENT_PATH = ROOT / "adjudication-replay-001.commitment.json"
AMENDMENT_PATH = ROOT / "adjudication-replay-001.modal-amendment.json"
MANIFEST_PATH = ROOT / "visible-surface-equivalence.json"
SUMMARY_PATH = ROOT / "criterion-audit-summary.json"
V2_ROOT = ROOT / "verifier-v2"
TRANSACTIONS_ROOT = ROOT.parent
V1_ARCHIVE = TRANSACTIONS_ROOT / "internal/archive/verifier-v1"


def _archived_aware_task_digest(path: Path) -> str:
    resolved = path.resolve()
    if (
        resolved.parent != TRANSACTIONS_ROOT.resolve()
        or resolved.name not in TASK_NAMES
    ):
        return task_content_digest(path)
    with tempfile.TemporaryDirectory() as temporary:
        reconstructed = Path(temporary) / resolved.name
        shutil.copytree(resolved, reconstructed)
        shutil.rmtree(reconstructed / "tests")
        shutil.copytree(
            V1_ARCHIVE / resolved.name / "tests",
            reconstructed / "tests",
        )
        archived_solution = (
            TRANSACTIONS_ROOT
            / "internal/archive/oracle-gold-v1-failed-001"
            / resolved.name
            / DELIVERABLES[resolved.name]
        )
        if archived_solution.is_file():
            shutil.copy2(
                archived_solution,
                reconstructed / "solution" / DELIVERABLES[resolved.name],
            )
        return task_content_digest(reconstructed)


# The frozen replay still addresses the pre-release canonical paths. Tests supply
# the archived grader and gold there without changing the hash-bound replay code.
replay_module.task_content_digest = _archived_aware_task_digest


class TrackingMockRuntime(MockVerifierRuntime):
    def __init__(self, **kwargs: object):
        super().__init__(**kwargs)
        self.workspace_names: list[str] = []
        self.prepared: list[str] = []

    def prepare(
        self, task_name: str, corrected_task: Path, verifier_digest: str
    ) -> None:
        del corrected_task, verifier_digest
        self.prepared.append(task_name)

    def run(
        self,
        task_name: str,
        corrected_task: Path,
        workspace: Path,
        logs_dir: Path,
    ) -> RuntimeResult:
        self.workspace_names.append(workspace.name)
        return super().run(task_name, corrected_task, workspace, logs_dir)


class NestedErrorRuntime(MockVerifierRuntime):
    def run(
        self,
        task_name: str,
        corrected_task: Path,
        workspace: Path,
        logs_dir: Path,
    ) -> RuntimeResult:
        result = super().run(task_name, corrected_task, workspace, logs_dir)
        (logs_dir / "reward-details.json").write_text(
            json.dumps({"criteria": [{"id": "C-001", "error": "judge failed"}]}) + "\n"
        )
        return result


class FailFirstRuntime(TrackingMockRuntime):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def run(
        self,
        task_name: str,
        corrected_task: Path,
        workspace: Path,
        logs_dir: Path,
    ) -> RuntimeResult:
        self.calls += 1
        if self.calls == 1:
            self.workspace_names.append(workspace.name)
            return RuntimeResult(
                9,
                "",
                "simulated infrastructure failure",
                self.identity(task_name),
            )
        return super().run(task_name, corrected_task, workspace, logs_dir)


class AdjudicationPreparationTests(unittest.TestCase):
    def test_original_task_digests_remain_frozen_and_reconstructible(self) -> None:
        for task_name, expected in ORIGINAL_TASK_DIGESTS.items():
            with self.subTest(task=task_name):
                with tempfile.TemporaryDirectory() as temporary:
                    reconstructed = Path(temporary) / task_name
                    shutil.copytree(TRANSACTIONS_ROOT / task_name, reconstructed)
                    shutil.rmtree(reconstructed / "tests")
                    shutil.copytree(
                        V1_ARCHIVE / task_name / "tests",
                        reconstructed / "tests",
                    )
                    archived_solution = (
                        TRANSACTIONS_ROOT
                        / "internal/archive/oracle-gold-v1-failed-001"
                        / task_name
                        / DELIVERABLES[task_name]
                    )
                    if archived_solution.is_file():
                        shutil.copy2(
                            archived_solution,
                            reconstructed / "solution" / DELIVERABLES[task_name],
                        )
                    self.assertEqual(task_content_digest(reconstructed), expected)

    def test_visible_surfaces_are_equal_and_diffs_are_verifier_only(self) -> None:
        manifest = load_json(MANIFEST_PATH)
        self.assertTrue(manifest["all_visible_surfaces_equal"])
        self.assertEqual({row["task"] for row in manifest["tasks"]}, set(TASK_NAMES))
        for row in manifest["tasks"]:
            self.assertTrue(row["instruction"]["equal"])
            self.assertTrue(row["environment"]["equal"])
            self.assertTrue(row["agent_visible_task_config"]["equal"])
            self.assertTrue(row["output_contract_and_integrity"]["equal"])
            self.assertEqual(row["verifier_only_diff"]["removed"], [])
            self.assertEqual(row["disallowed_diff"], [])
            self.assertNotEqual(
                row["original_task_digest"], row["corrected_task_digest"]
            )

    def test_every_criterion_has_exact_evidence_and_matches_v2_rubric(self) -> None:
        total = 0
        for task_name in TASK_NAMES:
            ledger = load_json(V2_ROOT / task_name / "tests/criterion-provenance.json")
            rubric = read_criteria(V2_ROOT / task_name)
            rows = ledger["criteria"]
            total += len(rows)
            self.assertEqual({row["id"] for row in rows}, set(rubric))
            for row in rows:
                with self.subTest(task=task_name, criterion=row["id"]):
                    self.assertEqual(row["support_status"], "author_assessed_supported")
                    self.assertIn(
                        row["evidence_scope"],
                        {"cited_excerpts", "complete_normalized_matter"},
                    )
                    self.assertEqual(
                        row["v2_description"], rubric[row["id"]]["description"]
                    )
                    self.assertTrue(row["evidence"])
                    for evidence in row["evidence"]:
                        self.assertTrue(evidence["file"])
                        self.assertTrue(evidence["location"])
                        self.assertTrue(evidence["text"])
                        self.assertEqual(len(evidence["text_sha256"]), 64)
        self.assertEqual(total, 171)
        summary = load_json(SUMMARY_PATH)
        self.assertEqual(summary["criteria_audited"], 171)
        self.assertEqual(summary["unresolved_v2_criteria"], [])

    def test_known_v1_defects_are_explicitly_repaired(self) -> None:
        contract = load_json(
            V2_ROOT
            / "compare-capacity-agreement-against-term-sheet"
            / "tests/criterion-provenance.json"
        )
        c058 = next(row for row in contract["criteria"] if row["id"] == "C-058")
        self.assertEqual(
            set(c058["v1_flags"]), {"unsupported", "cross_task_contamination"}
        )
        self.assertNotIn("October 31", c058["v2_description"])
        self.assertEqual(c058["support_status"], "author_assessed_supported")

    def test_global_criteria_receive_complete_normalized_matter(self) -> None:
        expected = {
            "normalize-buyer-mandate": {"C-047", "C-053"},
            "draft-capacity-data-room-population-plan": {"C-052", "C-053"},
            "compare-capacity-agreement-against-term-sheet": {"C-062"},
        }
        for task_name, criterion_ids in expected.items():
            task = V2_ROOT / task_name
            ledger = load_json(task / "tests/criterion-provenance.json")
            rows = {row["id"]: row for row in ledger["criteria"]}
            for criterion_id in criterion_ids:
                self.assertEqual(
                    rows[criterion_id]["evidence_scope"],
                    "complete_normalized_matter",
                )
            for quality in (task / "tests").glob("*/quality.toml"):
                self.assertIn('"/tests/source-context.md"', quality.read_text())

    def test_verifier_identity_ignores_generated_python_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "checks.py").write_text("value = 1\n")
            expected = tree_manifest(root)["tree_sha256"]
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "checks.cpython-313.pyc").write_bytes(b"generated")
            self.assertEqual(tree_manifest(root)["tree_sha256"], expected)
        for task_name in TASK_NAMES:
            dockerignore = V2_ROOT / task_name / "tests/.dockerignore"
            self.assertEqual(
                dockerignore.read_text(), "__pycache__/\n*.py[cod]\n.DS_Store\n"
            )

    def test_commitment_validates_exactly_43_immutable_sources(self) -> None:
        commitment = validate_commitment(COMMITMENT_PATH)
        self.assertEqual(len(commitment["sources"]), 43)
        self.assertEqual(len(commitment["excluded_sources"]), 2)
        self.assertEqual(len(commitment["source_jobs"]), 3)
        self.assertEqual(len(commitment["source_protocol_files"]), 4)
        self.assertEqual(len(commitment["policy_sha256"]), 64)
        self.assertEqual(commitment["judge"]["expected_paid_judge_calls"], 129)
        for source in commitment["sources"]:
            self.assertEqual(len(source["original"]["trial_config_sha256"]), 64)
        self.assertFalse(commitment["agent_rerun"])
        self.assertEqual(
            commitment["labels"]["amended"],
            "Amended adjudicated score (verifier v2 replay; preserved outputs; no agent rerun)",
        )

    def test_modal_protocol_amendment_binds_commitment_and_completed_run(self) -> None:
        run_path = DEFAULT_ATTEMPT / "adjudication-run.json"
        run = load_json(run_path)
        amendment = validate_protocol_amendment(
            AMENDMENT_PATH, COMMITMENT_PATH, run_path, run
        )
        self.assertEqual(amendment["runtime_change"]["backend"], "modal_sandbox")
        self.assertEqual(amendment["completed_run"]["valid_grades"], 43)

        changed_run = json.loads(json.dumps(run))
        changed_run["runtime_builds"][TASK_NAMES[0]]["modal_image_object_id"] = (
            "im-changed"
        )
        with self.assertRaisesRegex(AdjudicationError, "runtime identity mismatch"):
            validate_protocol_amendment(
                AMENDMENT_PATH, COMMITMENT_PATH, run_path, changed_run
            )

    def test_commitment_rejects_source_list_and_analysis_drift(self) -> None:
        commitment = load_json(COMMITMENT_PATH)
        with mock.patch("replay.load_json", wraps=load_json) as mocked_load:

            def load_with_source_change(path: Path) -> object:
                value = load_json(path)
                if path == COMMITMENT_PATH:
                    value["sources"][0]["source_trial"] = "changed"
                return value

            mocked_load.side_effect = load_with_source_change
            with self.assertRaisesRegex(AdjudicationError, "source-list hash"):
                validate_commitment(COMMITMENT_PATH)

        with mock.patch("replay.sha256_file", wraps=sha256_file) as mocked_hash:
            analysis_path = (
                ROOT.parent.parent.parent.parent / commitment["source_analysis"]["path"]
            )

            def hash_with_analysis_change(path: Path) -> str:
                if path.resolve() == analysis_path.resolve():
                    return "0" * 64
                return sha256_file(path)

            mocked_hash.side_effect = hash_with_analysis_change
            with self.assertRaisesRegex(AdjudicationError, "source analysis hash"):
                validate_commitment(COMMITMENT_PATH)

        with mock.patch("replay.load_json", wraps=load_json) as mocked_load:

            def load_with_policy_change(path: Path) -> object:
                value = load_json(path)
                if path == COMMITMENT_PATH:
                    value["retry_policy"]["valid_grade"] = "retry"
                return value

            mocked_load.side_effect = load_with_policy_change
            with self.assertRaisesRegex(AdjudicationError, "policy hash"):
                validate_commitment(COMMITMENT_PATH)

    def test_commitment_rederives_included_trials_from_frozen_analysis(self) -> None:
        commitment = load_json(COMMITMENT_PATH)
        analysis_path = (
            ROOT.parent.parent.parent.parent / commitment["source_analysis"]["path"]
        ).resolve()
        with mock.patch("replay.load_json", wraps=load_json) as mocked_load:

            def load_with_analysis_change(path: Path) -> object:
                value = load_json(path)
                if path.resolve() == analysis_path:
                    model = value["models"]["deepseek-v4-flash-0731"]
                    retained = next(
                        row
                        for row in model["records"]
                        if row.get("infrastructure_error") is None
                    )
                    retained["artifact_status_ok"] = False
                return value

            mocked_load.side_effect = load_with_analysis_change
            with self.assertRaisesRegex(
                AdjudicationError, "non-infrastructure analysis record lacks artifact"
            ):
                validate_commitment(COMMITMENT_PATH)

    def test_commitment_binds_each_trial_config(self) -> None:
        commitment = load_json(COMMITMENT_PATH)
        source = commitment["sources"][0]
        config = (
            ROOT.parent.parent.parent.parent
            / "compute-bazaar-bench/jobs/raw"
            / source["source_job"]
            / source["source_trial"]
            / "config.json"
        ).resolve()
        with mock.patch("replay.sha256_file", wraps=sha256_file) as mocked_hash:

            def hash_with_config_change(path: Path) -> str:
                if path.resolve() == config:
                    return "0" * 64
                return sha256_file(path)

            mocked_hash.side_effect = hash_with_config_change
            with self.assertRaisesRegex(
                AdjudicationError, "retained source hash mismatch"
            ):
                validate_commitment(COMMITMENT_PATH)

    def test_actual_verifier_shell_accepts_mocked_rewardkit_result(self) -> None:
        task_name = "normalize-buyer-mandate"
        task = V2_ROOT / task_name
        tests = task / "tests"
        deliverable = "buyer-mandate-brief.docx"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "app"
            logs = root / "logs/verifier"
            binaries = root / "bin"
            workspace.mkdir(parents=True)
            logs.mkdir(parents=True)
            binaries.mkdir()
            shutil.copyfile(task / "solution" / deliverable, workspace / deliverable)

            pandoc = binaries / "pandoc"
            pandoc.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' '# Mock extraction'\n"
                "i=0; while [ $i -lt 30 ]; do printf '%s\\n' "
                "'Complete professional output text for an offline verifier test.'; "
                "i=$((i + 1)); done\n"
            )
            mock_reward, mock_details = complete_mock_reward(task)
            mock_reward_path = root / "mock-reward.json"
            mock_details_path = root / "mock-reward-details.json"
            mock_reward_path.write_text(json.dumps(mock_reward) + "\n")
            mock_details_path.write_text(json.dumps(mock_details) + "\n")
            rewardkit = binaries / "rewardkit"
            rewardkit.write_text(
                "#!/bin/sh\n"
                "while [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = '--output' ]; then shift; output=$1; fi\n"
                "  shift\n"
                "done\n"
                'mkdir -p "$(dirname "$output")"\n'
                'cp "$MOCK_REWARD" "$output"\n'
                'cp "$MOCK_REWARD_DETAILS" "$(dirname "$output")/reward-details.json"\n'
            )
            pandoc.chmod(0o755)
            rewardkit.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{binaries}:{env['PATH']}",
                    "HARBOR_TESTS_DIR": str(tests),
                    "HARBOR_WORKSPACE": str(workspace),
                    "HARBOR_VERIFIER_LOG_DIR": str(logs),
                    "MOCK_REWARD": str(mock_reward_path),
                    "MOCK_REWARD_DETAILS": str(mock_details_path),
                }
            )
            completed = subprocess.run(
                ["bash", str(tests / "test.sh")],
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            reward, details = validate_reward_files(logs, task)
            self.assertEqual(reward["all_pass"], 1.0)
            self.assertTrue(
                all(
                    details[dimension]["mock"]
                    for dimension in details
                    if dimension != "output-integrity"
                )
            )
            self.assertTrue((workspace / f"{deliverable}.md").is_file())


class AdjudicationReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.commitment = validate_commitment(COMMITMENT_PATH)
        cls.source = cls.commitment["sources"][0]
        cls.corrected_task = V2_ROOT / cls.source["task"]

    def test_mocked_full_replay_is_separate_and_never_writes_harbor_result(
        self,
    ) -> None:
        runtime = TrackingMockRuntime()
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp) / "adjudications"
            execute_replay(COMMITMENT_PATH, output_root, runtime)
            run_dir = output_root / self.commitment["adjudication_id"] / "attempt-001"
            run = load_json(run_dir / "adjudication-run.json")
            self.assertEqual(run["attempted_sources"], 43)
            self.assertEqual(run["remaining_sources"], 0)
            self.assertEqual(run["valid"], 43)
            self.assertEqual(run["status"], "complete")
            self.assertEqual(set(runtime.prepared), set(TASK_NAMES))
            self.assertEqual(runtime.workspace_names, ["app"] * 43)
            self.assertEqual(list(run_dir.rglob("result.json")), [])
            self.assertEqual(
                len(list((run_dir / "records").glob("*/adjudication.json"))), 43
            )

    def test_resume_recovers_record_written_after_last_ledger_checkpoint(self) -> None:
        runtime = TrackingMockRuntime()
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp) / "adjudications"
            execute_replay(COMMITMENT_PATH, output_root, runtime)
            run_dir = output_root / self.commitment["adjudication_id"] / "attempt-001"
            checkpoint_path = run_dir / "adjudication-run.json"
            stale = load_json(checkpoint_path)
            stale["status"] = "running"
            stale["record_results"].pop()
            stale["attempted_sources"] -= 1
            stale["remaining_sources"] += 1
            checkpoint_path.write_text(json.dumps(stale, indent=2) + "\n")

            resumed_runtime = TrackingMockRuntime()
            resumed = execute_replay(
                COMMITMENT_PATH,
                output_root,
                resumed_runtime,
                resume_attempt=True,
            )
            self.assertEqual(resumed["status"], "complete")
            self.assertEqual(resumed["attempted_sources"], 43)
            self.assertEqual(resumed["remaining_sources"], 0)
            self.assertEqual(resumed_runtime.workspace_names, [])
            self.assertEqual(resumed_runtime.prepared, [])

    def test_resume_blocks_an_in_flight_record_without_final_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp) / "adjudications"
            run = execute_replay(COMMITMENT_PATH, output_root, TrackingMockRuntime())
            run_dir = output_root / self.commitment["adjudication_id"] / "attempt-001"
            checkpoint_path = run_dir / "adjudication-run.json"
            checkpoint = load_json(checkpoint_path)
            checkpoint["status"] = "running"
            checkpoint_path.write_text(json.dumps(checkpoint, indent=2) + "\n")
            record_path = run_dir / run["record_results"][0]["record_path"]
            record_path.unlink()
            with self.assertRaisesRegex(
                AdjudicationError,
                "in-flight record has no final adjudication checkpoint",
            ):
                execute_replay(
                    COMMITMENT_PATH,
                    output_root,
                    TrackingMockRuntime(),
                    resume_attempt=True,
                )

    def test_missing_and_malformed_docx_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(AdjudicationError):
                validate_docx(root / "missing.docx")
            malformed = root / "malformed.docx"
            malformed.write_bytes(b"not a docx")
            with self.assertRaisesRegex(AdjudicationError, "valid DOCX"):
                validate_docx(malformed)

    def test_committed_artifact_tamper_is_detected_without_touching_source(
        self,
    ) -> None:
        artifact = ROOT.parent.parent.parent.parent / self.source["artifact"]["path"]
        original_hash = sha256_file(artifact)
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / artifact.name
            copied.write_bytes(artifact.read_bytes() + b"tamper")
            self.assertNotEqual(sha256_file(copied), self.source["artifact"]["sha256"])
        self.assertEqual(sha256_file(artifact), original_hash)

    def test_verifier_artifact_mutation_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "record"
            record = replay_one(
                self.source,
                self.corrected_task,
                output,
                MockVerifierRuntime(mutate_artifact=True),
            )
            self.assertEqual(record["status"], "integrity_error")
            self.assertEqual(record["failure_stage"], "artifact_post_verifier")

    def test_nonzero_verifier_exit_is_preserved_as_infrastructure_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "record"
            record = replay_one(
                self.source,
                self.corrected_task,
                output,
                MockVerifierRuntime(returncode=9),
            )
            self.assertEqual(record["status"], "infrastructure_error")
            self.assertEqual(record["returncode"], 9)

    def test_nested_judge_error_fails_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "record"
            record = replay_one(
                self.source,
                self.corrected_task,
                output,
                NestedErrorRuntime(),
            )
            self.assertEqual(record["status"], "infrastructure_error")
            self.assertEqual(record["failure_stage"], "reward_validation")
            self.assertIn("nested verifier/judge error", record["failure_message"])
            self.assertFalse((output / "reward.json").exists())
            self.assertTrue((output / "invalid-reward-details.json").exists())

    def test_retry_attempt_selects_only_prior_infrastructure_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp) / "adjudications"
            first_runtime = FailFirstRuntime()
            first = execute_replay(COMMITMENT_PATH, output_root, first_runtime)
            self.assertEqual(first["valid"], 42)
            self.assertEqual(first["infrastructure_error"], 1)
            first_path = (
                output_root
                / self.commitment["adjudication_id"]
                / "attempt-001/adjudication-run.json"
            )
            retry_runtime = TrackingMockRuntime()
            retry = execute_replay(
                COMMITMENT_PATH,
                output_root,
                retry_runtime,
                attempt_id="attempt-002",
                retry_from=first_path,
            )
            self.assertEqual(retry["attempt_kind"], "infrastructure_retry_only")
            self.assertEqual(retry["attempted_sources"], 1)
            self.assertEqual(retry["valid"], 1)
            self.assertEqual(retry_runtime.workspace_names, ["app"])

            first_record = first["record_results"][0]
            record_path = first_path.parent / first_record["record_path"]
            record_path.write_text(record_path.read_text() + " ")
            with self.assertRaisesRegex(AdjudicationError, "retry record hash"):
                execute_replay(
                    COMMITMENT_PATH,
                    output_root,
                    TrackingMockRuntime(),
                    attempt_id="attempt-003",
                    retry_from=first_path,
                )

    def test_later_attempt_without_retry_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(AdjudicationError, "require --retry-from"):
                execute_replay(
                    COMMITMENT_PATH,
                    Path(temp),
                    TrackingMockRuntime(),
                    attempt_id="attempt-002",
                )

    def test_raw_job_output_destination_is_rejected(self) -> None:
        with self.assertRaisesRegex(AdjudicationError, "jobs/raw"):
            replay_one(
                self.source,
                self.corrected_task,
                RAW_JOBS / "must-not-exist",
                MockVerifierRuntime(),
            )

    def test_reward_validation_requires_complete_consistent_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            logs = Path(temp)
            reward, details = complete_mock_reward(self.corrected_task)
            semantic_dimension = next(
                key for key in details if key != "output-integrity"
            )
            details[semantic_dimension]["criteria"].pop()
            (logs / "reward.json").write_text(json.dumps(reward) + "\n")
            (logs / "reward-details.json").write_text(json.dumps(details) + "\n")
            with self.assertRaisesRegex(AdjudicationError, "criterion coverage"):
                validate_reward_files(logs, self.corrected_task)
        self.assertTrue(has_nested_error({"criteria": [{"errors": ["bad"]}]}))

    def test_openrouter_gate_estimates_129_calls_and_fails_closed(self) -> None:
        models = {
            "data": [
                {
                    "id": "openai/gpt-5.4",
                    "canonical_slug": "openai/gpt-5.4-20260305",
                    "context_length": 1_050_000,
                    "pricing": {"prompt": "0.0000025", "completion": "0.000015"},
                    "top_provider": {"max_completion_tokens": 128_000},
                }
            ]
        }
        common = {
            "commitment": self.commitment,
            "commitment_sha256": sha256_file(COMMITMENT_PATH),
            "repo_root": ROOT.parent.parent.parent.parent,
            "adjudication_root": ROOT,
            "key_payload": {
                "data": {
                    "label": "sk-or-v1-test-only-redacted",
                    "limit": 60,
                    "limit_remaining": 40,
                    "usage": 20,
                }
            },
            "models_payload": models,
        }
        passing = evaluate_gate(
            **common,
            credits_payload={"data": {"total_credits": 100, "total_usage": 0}},
        )
        self.assertEqual(passing["status"], "passed")
        self.assertEqual(passing["estimate"]["calls"], 129)
        self.assertNotIn("test-only-redacted", passing["account"]["key_label"])
        self.assertGreater(passing["estimate"]["required_balance_usd"], 0)

        blocked = evaluate_gate(
            **common,
            credits_payload={"data": {"total_credits": 1, "total_usage": 0}},
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertFalse(blocked["checks"]["account_balance_covers_required_reserve"])


if __name__ == "__main__":
    unittest.main()
