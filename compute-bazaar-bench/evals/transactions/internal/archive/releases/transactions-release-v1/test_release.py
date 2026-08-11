from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib
import unittest
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parent
TRANSACTIONS_ROOT = ROOT.parents[1]
ADJUDICATION_ROOT = TRANSACTIONS_ROOT / "adjudication"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ADJUDICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(ADJUDICATION_ROOT))

from common import (  # noqa: E402
    DELIVERABLES,
    INTEGRITY_PATHS,
    ORIGINAL_TASK_DIGESTS,
    TASK_NAMES,
    canonical_json_sha256,
    load_json,
    selected_files_manifest,
    sha256_file,
    task_content_digest,
    tree_manifest,
)
from check_spend import evaluate_gate  # noqa: E402
from derive_cost_envelope import derive  # noqa: E402
from analyze_release import (  # noqa: E402
    native_row,
    render_public_report,
    replay_row,
    trial_counts,
)


PROTOCOL_PATH = ROOT / "transactions-release-v1.commitment.json"
CRAFT_PATH = ROOT / "transactions-release-v1.craft-rubric.json"
SPEND_GATE_PATH = ROOT / "spend-gate-002.json"
COST_ENVELOPE_PATH = ROOT / "cost-envelope-001.json"
PUBLIC_VIEW_PATH = ROOT.parent / "public-view.json"
V2_ROOT = ADJUDICATION_ROOT / "verifier-v2"
V1_ARCHIVE = TRANSACTIONS_ROOT / "internal/archive/verifier-v1"


class TransactionsReleaseTests(unittest.TestCase):
    def test_invalid_agent_output_remains_in_quality_denominator(self) -> None:
        records = [
            {
                "infrastructure_error": None,
                "agent_invalid_output": True,
            },
            {
                "infrastructure_error": None,
                "agent_invalid_output": False,
            },
            {
                "infrastructure_error": "provider failure",
                "agent_invalid_output": False,
            },
        ]

        self.assertEqual(
            trial_counts(records, planned=3),
            {
                "planned": 3,
                "completed": 3,
                "scored": 2,
                "valid_docx": 1,
                "agent_invalid_output": 1,
                "infrastructure": 1,
            },
        )

    def test_public_release_rows_keep_execution_origin_explicit(self) -> None:
        protocol = load_json(PROTOCOL_PATH)
        native = {
            "job": "native-job",
            "counts": {
                "planned": 15,
                "completed": 15,
                "scored": 15,
                "valid_docx": 0,
                "agent_invalid_output": 15,
                "infrastructure": 0,
            },
            "summary": {
                "strict_all_pass_rate": 0.0,
                "semantic_passes": 0,
                "semantic_criteria": 855,
                "micro_semantic_rate": 0.0,
                "macro_semantic_mean": 0.0,
                "tasks": {},
            },
            "trials": [
                {
                    "infrastructure_error": None,
                    "all_pass": 0,
                    "visual_review": None,
                    "agent_seconds": 12.0,
                    "tokens": {"input": 100, "cache": 50, "output": 10},
                    "reported_cost_usd": None,
                }
            ],
        }
        fresh = native_row(protocol, native)
        self.assertEqual(fresh["execution_label"], "Fresh Harbor run")
        self.assertEqual(fresh["scored"], 15)
        self.assertEqual(fresh["invalid_output"], 15)
        self.assertEqual(fresh["telemetry"]["judge_cost_usd"], 0.0)
        self.assertEqual(fresh["criterion_evaluation"], "not_run_output_gate")
        self.assertEqual(fresh["semantic_judge_batches"], 0)

        preserved = replay_row(
            protocol,
            "model-a",
            "Model A",
            {
                "job": "preserved-job",
                "amended": {
                    "retained": 1,
                    "all_pass": 1,
                    "strict_all_pass_rate": 1.0,
                    "semantic_passes": 2,
                    "semantic_criteria": 2,
                    "criterion_pass_rate": 1.0,
                    "macro_semantic_mean": 1.0,
                    "tasks": {},
                },
                "records": [
                    {
                        "agent_seconds": 10.0,
                        "tokens": {"input": 80, "cache": 20, "output": 8},
                        "visual_review": {
                            "practical_usability": "good",
                        },
                    }
                ],
            },
        )
        self.assertEqual(preserved["execution_label"], "Earlier output, regraded")
        self.assertEqual(preserved["infrastructure"], 14)

        report = render_public_report(
            {
                "rows": [fresh, preserved],
                "account_observation": {"combined_openrouter_spend_usd": None},
                "preserved_replay_observation": {},
            }
        )
        self.assertIn("Mistral Small was run fresh in Harbor", report)
        self.assertIn("Earlier output, regraded", report)
        self.assertIn("frozen release grader", report)
        self.assertIn("not judged (output gate)", report)
        self.assertIn("not a general model ranking", report)

    def test_protocol_binds_canonical_release_tasks(self) -> None:
        protocol = load_json(PROTOCOL_PATH)
        bound = {row["name"]: row for row in protocol["tasks"]}
        self.assertEqual(set(bound), set(TASK_NAMES))
        for task_name in TASK_NAMES:
            with self.subTest(task=task_name):
                canonical = TRANSACTIONS_ROOT / task_name
                self.assertEqual(
                    task_content_digest(canonical), bound[task_name]["digest"]
                )
                self.assertEqual(
                    tree_manifest(canonical / "tests")["tree_sha256"],
                    bound[task_name]["verifier_tree_sha256"],
                )
                self.assertEqual(
                    tree_manifest(canonical / "tests")["tree_sha256"],
                    tree_manifest(V2_ROOT / task_name / "tests")["tree_sha256"],
                )
                self.assertEqual(
                    sha256_file(
                        canonical / "solution" / bound[task_name]["deliverable"]
                    ),
                    bound[task_name]["solution_sha256"],
                )
                self.assertEqual(
                    sha256_file(canonical / "instruction.md"),
                    bound[task_name]["instruction_sha256"],
                )
                self.assertEqual(
                    tree_manifest(canonical / "environment")["tree_sha256"],
                    bound[task_name]["environment_tree_sha256"],
                )
                parsed = tomllib.loads((canonical / "task.toml").read_text())
                visible_config = {
                    key: parsed.get(key)
                    for key in (
                        "schema_version",
                        "artifacts",
                        "agent",
                        "environment",
                        "steps",
                    )
                }
                self.assertEqual(
                    canonical_json_sha256(visible_config),
                    bound[task_name]["agent_visible_task_config_sha256"],
                )
                self.assertEqual(
                    selected_files_manifest(canonical, INTEGRITY_PATHS)["tree_sha256"],
                    bound[task_name]["output_contract_and_integrity_tree_sha256"],
                )

    def test_repaired_oracle_gold_is_scoped_and_source_grounded(self) -> None:
        protocol = load_json(PROTOCOL_PATH)
        repair = protocol["oracle_gold_repair"]
        archive = TRANSACTIONS_ROOT / repair["archive_path"].split("transactions/", 1)[1]
        second_archive = (
            TRANSACTIONS_ROOT
            / repair["second_archive_path"].split("transactions/", 1)[1]
        )
        third_archive = (
            TRANSACTIONS_ROOT
            / repair["third_archive_path"].split("transactions/", 1)[1]
        )
        self.assertEqual(
            sha256_file(archive / "normalize-buyer-mandate/buyer-mandate-brief.docx"),
            repair["old_solution_sha256"]["normalize-buyer-mandate"],
        )
        self.assertEqual(
            sha256_file(
                archive / "draft-capacity-data-room-population-plan/"
                "capacity-data-room-population-plan.docx"
            ),
            repair["old_solution_sha256"]["draft-capacity-data-room-population-plan"],
        )
        self.assertEqual(
            sha256_file(
                second_archive
                / "normalize-buyer-mandate/buyer-mandate-brief.docx"
            ),
            repair["oracle_002_solution_sha256"]["normalize-buyer-mandate"],
        )
        self.assertEqual(
            sha256_file(
                second_archive
                / "draft-capacity-data-room-population-plan/"
                "capacity-data-room-population-plan.docx"
            ),
            repair["oracle_002_solution_sha256"][
                "draft-capacity-data-room-population-plan"
            ],
        )
        self.assertEqual(
            sha256_file(
                third_archive
                / "draft-capacity-data-room-population-plan/"
                "capacity-data-room-population-plan.docx"
            ),
            repair["oracle_004_solution_sha256"][
                "draft-capacity-data-room-population-plan"
            ],
        )

        normalize = (
            TRANSACTIONS_ROOT
            / "normalize-buyer-mandate/solution/buyer-mandate-brief.docx"
        )
        diligence = (
            TRANSACTIONS_ROOT / "draft-capacity-data-room-population-plan/solution/"
            "capacity-data-room-population-plan.docx"
        )
        with ZipFile(normalize) as archive_file:
            normalize_xml = archive_file.read("word/document.xml").decode()
        with ZipFile(diligence) as archive_file:
            diligence_xml = archive_file.read("word/document.xml").decode()
        self.assertIn("Current SOC 2 Type II report", normalize_xml)
        self.assertIn("For calculation only, assume", normalize_xml)
        self.assertIn("Implementation charges were not discussed", normalize_xml)
        for phrase in (
            "Operating procedures",
            "Proposed service levels",
            "proposed parent-guarantee credit support",
            "every redaction and basis",
            "KYC materials",
            "current status is not evidenced",
            "Collect current design set",
            "external capacity and redundancy",
            "water/coolant dependencies and operating limits",
            "sanctions, export controls, environmental matters",
        ):
            self.assertIn(phrase, diligence_xml)
        for unsupported in (
            "easement update missing",
            "NCCL reference threshold open",
            "Current drafts ready",
            "Permit matrix in review",
            "Current as of Aug. 9",
        ):
            self.assertNotIn(unsupported, diligence_xml)

    def test_private_v1_grader_remains_reconstructible(self) -> None:
        for task_name, digest in ORIGINAL_TASK_DIGESTS.items():
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
                    self.assertEqual(task_content_digest(reconstructed), digest)

    def test_configs_resolve_only_the_three_canonical_tasks(self) -> None:
        protocol = load_json(PROTOCOL_PATH)
        expected_paths = [row["path"] for row in protocol["tasks"]]
        expected_models = {
            "mistral-small-2603": "openrouter/mistralai/mistral-small-2603:exacto",
        }
        for model in protocol["models"]:
            with self.subTest(model=model["key"]):
                config_path = ROOT / model["config_path"]
                self.assertEqual(sha256_file(config_path), model["config_sha256"])
                config = load_json(config_path)
                self.assertEqual(config["n_attempts"], 5)
                self.assertEqual(config["n_concurrent_trials"], 1)
                self.assertEqual(config["environment"]["type"], "modal")
                self.assertTrue(config["environment"]["kwargs"]["modal_vm_runtime"])
                self.assertEqual(
                    config["agents"][0]["model_name"],
                    expected_models[model["key"]],
                )
                self.assertEqual(
                    [item["path"] for item in config["tasks"]],
                    expected_paths,
                )

        repaired = protocol["oracle"]["repaired_tasks"]
        oracle_path = ROOT / repaired["config_path"]
        self.assertEqual(sha256_file(oracle_path), repaired["config_sha256"])
        oracle = load_json(oracle_path)
        self.assertEqual(oracle["agents"][0]["name"], "oracle")
        self.assertEqual(oracle["n_concurrent_trials"], 1)
        self.assertEqual(oracle["agents"][0]["n_concurrent"], 1)
        self.assertEqual(
            [item["path"] for item in oracle["tasks"]], [expected_paths[1]]
        )
        self.assertEqual(oracle["job_name"], "transactions-release-v1-oracle-005")
        normalize = protocol["oracle"]["unchanged_normalize_task"]
        self.assertEqual(normalize["task"], TASK_NAMES[0])
        self.assertEqual(normalize["task_digest"], protocol["tasks"][0]["digest"])
        unchanged = protocol["oracle"]["unchanged_contracting_task"]
        self.assertEqual(unchanged["task"], TASK_NAMES[2])
        self.assertEqual(unchanged["task_digest"], protocol["tasks"][2]["digest"])

        inactive = protocol["inactive_prepared_configs"]
        self.assertEqual([item["key"] for item in inactive], ["glm-5.2"])
        for field in ("config", "preflight_config"):
            path = ROOT / inactive[0][f"{field}_path"]
            self.assertIn("configs/inactive", str(path))
            self.assertEqual(sha256_file(path), inactive[0][f"{field}_sha256"])

    def test_model_route_preflights_are_private_and_exact(self) -> None:
        protocol = load_json(PROTOCOL_PATH)
        preflight = protocol["model_route_preflight"]
        task_path = ROOT / preflight["task_path"]
        self.assertEqual(task_content_digest(task_path), preflight["task_digest"])
        for model in protocol["models"]:
            with self.subTest(model=model["key"]):
                config_path = ROOT / model["preflight_config_path"]
                self.assertEqual(
                    sha256_file(config_path), model["preflight_config_sha256"]
                )
                config = load_json(config_path)
                self.assertEqual(config["n_attempts"], 1)
                self.assertEqual(config["n_concurrent_trials"], 1)
                self.assertTrue(config["verifier"]["disable"])
                self.assertEqual(
                    config["agents"][0]["model_name"], model["agent_model"]
                )
                self.assertEqual(
                    [item["path"] for item in config["tasks"]],
                    [
                        "compute-bazaar-bench/evals/transactions/releases/"
                        "transactions-release-v1/preflight/model-route"
                    ],
                )

    def test_review_and_public_view_are_frozen(self) -> None:
        protocol = load_json(PROTOCOL_PATH)
        self.assertEqual(
            sha256_file(CRAFT_PATH), protocol["reporting"]["craft_rubric_sha256"]
        )
        public_view = load_json(PUBLIC_VIEW_PATH)
        self.assertEqual(public_view["protocol_sha256"], sha256_file(PROTOCOL_PATH))
        self.assertEqual(set(public_view["managed_tasks"]), set(TASK_NAMES))
        self.assertEqual(
            set(public_view["jobs"]),
            {row["job"] for row in protocol["comparison_rows"]},
        )
        self.assertEqual(set(public_view["job_metadata"]), set(public_view["jobs"]))
        origins = {
            item["execution_origin"] for item in public_view["job_metadata"].values()
        }
        self.assertEqual(
            origins, {"fresh_native_harbor", "preserved_output_adjudication"}
        )
        self.assertFalse(public_view["include_private_calibration"])

    def test_spend_gate_freezes_staged_serial_rule(self) -> None:
        gate = load_json(SPEND_GATE_PATH)
        self.assertEqual(gate["protocol_sha256"], sha256_file(PROTOCOL_PATH))
        self.assertEqual(gate["status"], "frozen_pending_live_entry_gate")
        self.assertEqual(gate["paid_calls_made_before_refreeze"], 21)
        self.assertEqual(gate["execution"]["concurrency"], 1)
        self.assertEqual(gate["execution"]["max_retries"], 0)
        self.assertEqual(gate["estimate"]["official_judge_usd"], 8.854735 / 129 * 45)
        self.assertAlmostEqual(
            gate["estimate"]["entry_required_balance_usd"],
            gate["estimate"]["complete_expected_usd"] * 1.25
            + gate["estimate"]["official_record_cost_envelope_usd"],
        )

    def test_cost_envelope_reproduces_frozen_record(self) -> None:
        self.assertEqual(derive(), load_json(COST_ENVELOPE_PATH))

    def test_live_spend_gate_fails_closed_without_network(self) -> None:
        baseline = load_json(SPEND_GATE_PATH)
        models = []
        for model_id, expected in baseline["catalog_pricing_usd_per_token"].items():
            models.append(
                {
                    "id": model_id,
                    "canonical_slug": expected["canonical_slug"],
                    "pricing": {
                        "prompt": expected["prompt"],
                        "completion": expected["completion"],
                        "input_cache_read": expected["input_cache_read"],
                    },
                }
            )
        credits = {"data": {"total_credits": 20, "total_usage": 0}}
        key = {"data": {"limit_remaining": 20}}
        passed = evaluate_gate(key, credits, {"data": models}, stage="entry")
        self.assertEqual(passed["status"], "passed")

        credits["data"]["total_usage"] = 16
        blocked = evaluate_gate(key, credits, {"data": models}, stage="entry")
        self.assertEqual(blocked["status"], "blocked")
        self.assertFalse(blocked["checks"]["account_covers_stage"])

        models[0]["pricing"]["prompt"] = "changed"
        changed = evaluate_gate(
            key,
            {"data": {"total_credits": 20, "total_usage": 0}},
            {"data": models},
            stage="entry",
        )
        self.assertEqual(changed["status"], "blocked")
        self.assertFalse(changed["checks"]["pricing_matches_frozen_gate"])

    def test_official_gate_uses_frozen_record_envelope(self) -> None:
        baseline = load_json(SPEND_GATE_PATH)
        models = [
            {
                "id": model_id,
                "canonical_slug": expected["canonical_slug"],
                "pricing": {
                    "prompt": expected["prompt"],
                    "completion": expected["completion"],
                    "input_cache_read": expected["input_cache_read"],
                },
            }
            for model_id, expected in baseline["catalog_pricing_usd_per_token"].items()
        ]
        key = {"data": {"limit_remaining": 20}}
        entry = {"account": {"account_remaining_usd": 10}}
        post_oracle = {"account": {"account_remaining_usd": 9.3}}
        result = evaluate_gate(
            key,
            {"data": {"total_credits": 20, "total_usage": 10.8}},
            {"data": models},
            stage="official",
            entry_snapshot=entry,
            post_oracle_snapshot=post_oracle,
        )
        self.assertEqual(result["status"], "passed")
        self.assertAlmostEqual(result["estimate"]["observed_oracle_stage_usd"], 0.7)
        self.assertAlmostEqual(
            result["estimate"]["required_balance_usd"],
            result["estimate"]["official_expected_usd"] * 1.25
            + baseline["estimate"]["official_record_cost_envelope_usd"],
        )

    def test_json_files_are_plain_valid_json(self) -> None:
        for path in [
            PROTOCOL_PATH,
            CRAFT_PATH,
            SPEND_GATE_PATH,
            COST_ENVELOPE_PATH,
            PUBLIC_VIEW_PATH,
        ]:
            with self.subTest(path=path.name):
                self.assertIsInstance(json.loads(path.read_text()), dict)


if __name__ == "__main__":
    unittest.main()
