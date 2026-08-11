from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
from typing import Any, Protocol
import zipfile

from common import (
    DELIVERABLES,
    TASK_NAMES,
    AdjudicationError,
    assert_regular_file,
    canonical_json_sha256,
    load_json,
    ORIGINAL_TASK_DIGESTS,
    repo_root_from,
    sha256_bytes,
    sha256_file,
    task_content_digest,
    tree_manifest,
    write_json,
)


ROOT = Path(__file__).resolve().parent
REPO_ROOT = repo_root_from(ROOT)
RAW_JOBS = (REPO_ROOT / "compute-bazaar-bench/jobs/raw").resolve()
DEFAULT_COMMITMENT = ROOT / "adjudication-replay-001.commitment.json"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "compute-bazaar-bench/jobs/adjudications"

REQUIRED_DOCX_MEMBERS = {"[Content_Types].xml", "word/document.xml"}
SELECTED_MODEL_KEYS = (
    "deepseek-v4-flash-0731",
    "gpt-5.6-luna",
    "glm-5.2",
)


def load_repo_secret(name: str) -> str | None:
    current = os.environ.get(name)
    if current:
        return current
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return None
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


@dataclass(frozen=True)
class RuntimeResult:
    returncode: int
    stdout: str
    stderr: str
    runtime_identity: dict[str, Any]


class VerifierRuntime(Protocol):
    def prepare(
        self, task_name: str, corrected_task: Path, verifier_digest: str
    ) -> None: ...

    def run(
        self,
        task_name: str,
        corrected_task: Path,
        workspace: Path,
        logs_dir: Path,
    ) -> RuntimeResult: ...

    def identity(self, task_name: str) -> dict[str, Any]: ...


class DockerVerifierRuntime:
    def __init__(self) -> None:
        self.images: dict[str, str] = {}

    def prepare(
        self, task_name: str, corrected_task: Path, verifier_digest: str
    ) -> None:
        image = f"compute-bazaar-adjudication:{verifier_digest[:20]}"
        command = [
            "docker",
            "build",
            "--label",
            f"compute-bazaar.adjudication.task={task_name}",
            "--label",
            f"compute-bazaar.adjudication.verifier={verifier_digest}",
            "--tag",
            image,
            str(corrected_task / "tests"),
        ]
        command.insert(2, "--pull=false")
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=1200,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise AdjudicationError(
                f"verifier image build could not complete for {task_name}: {error}"
            ) from error
        if completed.returncode != 0:
            raise AdjudicationError(
                f"verifier image build failed for {task_name}: {completed.stderr}"
            )
        inspect = subprocess.run(
            ["docker", "image", "inspect", "--format={{.Id}}", image],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        image_id = inspect.stdout.strip()
        if inspect.returncode != 0 or not image_id.startswith("sha256:"):
            raise AdjudicationError(
                f"could not bind verifier image identity for {task_name}: {inspect.stderr}"
            )
        self.images[task_name] = image_id

    def identity(self, task_name: str) -> dict[str, Any]:
        return {
            "kind": "docker",
            "image_id": self.images.get(task_name),
            "build_status": (
                "prepared" if task_name in self.images else "not_prepared"
            ),
            "network_enforcement": "public bridge; verifier is configured for OpenRouter but host allowlisting is not enforced",
        }

    def run(
        self,
        task_name: str,
        corrected_task: Path,
        workspace: Path,
        logs_dir: Path,
    ) -> RuntimeResult:
        del corrected_task
        image = self.images[task_name]
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "bridge",
            "--cpus",
            "2",
            "--memory",
            "4g",
            "--pids-limit",
            "256",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m",
            "--env",
            "OPENROUTER_API_KEY",
            "--env",
            "LITELLM_DROP_PARAMS=True",
            "--env",
            "HARBOR_TESTS_DIR=/tests",
            "--env",
            "HARBOR_WORKSPACE=/app",
            "--env",
            "HARBOR_VERIFIER_LOG_DIR=/logs/verifier",
            "--mount",
            f"type=bind,source={workspace},target=/app",
            "--mount",
            (
                f"type=bind,source={workspace / DELIVERABLES[task_name]},"
                f"target=/app/{DELIVERABLES[task_name]},readonly"
            ),
            "--mount",
            f"type=bind,source={logs_dir},target=/logs/verifier",
            image,
            "/tests/test.sh",
        ]
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=3600,
            )
            return RuntimeResult(
                completed.returncode,
                completed.stdout,
                completed.stderr,
                self.identity(task_name),
            )
        except subprocess.TimeoutExpired as error:
            stdout = (
                error.stdout.decode(errors="replace")
                if isinstance(error.stdout, bytes)
                else (error.stdout or "")
            )
            stderr = (
                error.stderr.decode(errors="replace")
                if isinstance(error.stderr, bytes)
                else (error.stderr or "")
            )
            return RuntimeResult(
                124,
                stdout,
                stderr + "\nverifier subprocess exceeded 3600 seconds",
                self.identity(task_name),
            )


class MockVerifierRuntime:
    """Deterministic verifier stand-in used only by Gate 1 tests."""

    def __init__(self, *, returncode: int = 0, mutate_artifact: bool = False):
        self.returncode = returncode
        self.mutate_artifact = mutate_artifact

    def prepare(
        self, task_name: str, corrected_task: Path, verifier_digest: str
    ) -> None:
        del task_name, corrected_task, verifier_digest

    def identity(self, task_name: str) -> dict[str, Any]:
        return {"kind": "mock", "task": task_name}

    def run(
        self,
        task_name: str,
        corrected_task: Path,
        workspace: Path,
        logs_dir: Path,
    ) -> RuntimeResult:
        deliverable = workspace / DELIVERABLES[task_name]
        if self.mutate_artifact:
            deliverable.chmod(0o644)
            deliverable.write_bytes(deliverable.read_bytes() + b"tamper")
        logs_dir.mkdir(parents=True, exist_ok=True)
        if self.returncode == 0:
            reward, details = complete_mock_reward(corrected_task)
            write_json(logs_dir / "reward.json", reward)
            write_json(logs_dir / "reward-details.json", details)
        return RuntimeResult(
            self.returncode,
            "mock verifier\n",
            "",
            self.identity(task_name),
        )


def ensure_outside_raw(path: Path) -> None:
    resolved = path.resolve()
    if resolved == RAW_JOBS or RAW_JOBS in resolved.parents:
        raise AdjudicationError(
            f"adjudication output may not be under jobs/raw: {path}"
        )


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_docx(path: Path) -> None:
    assert_regular_file(path)
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            missing = REQUIRED_DOCX_MEMBERS - names
            if missing:
                raise AdjudicationError(
                    f"DOCX archive lacks required members {sorted(missing)}: {path}"
                )
            if archive.testzip() is not None:
                raise AdjudicationError(f"DOCX archive CRC failure: {path}")
    except zipfile.BadZipFile as error:
        raise AdjudicationError(f"not a valid DOCX archive: {path}") from error


def has_nested_error(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"error", "errors"} and item not in (None, "", [], {}):
                return True
            if has_nested_error(item):
                return True
    elif isinstance(value, list):
        return any(has_nested_error(item) for item in value)
    return False


def reward_schema(corrected_task: Path) -> dict[str, list[dict[str, str]]]:
    dimensions: dict[str, list[dict[str, str]]] = {}
    for quality_path in sorted((corrected_task / "tests").glob("*/quality.toml")):
        parsed = tomllib.loads(quality_path.read_text())
        criteria = parsed.get("criterion", [])
        dimension = quality_path.parent.name
        if not criteria:
            raise AdjudicationError(
                f"semantic dimension has no criteria: {quality_path}"
            )
        dimensions[dimension] = [
            {"id": item["id"], "description": item["description"]} for item in criteria
        ]
    if len(dimensions) != 3:
        raise AdjudicationError(
            f"corrected verifier must have exactly three semantic dimensions: {corrected_task}"
        )
    ids = [item["id"] for criteria in dimensions.values() for item in criteria]
    if len(ids) != len(set(ids)):
        raise AdjudicationError(
            f"corrected verifier has duplicate criterion IDs: {corrected_task}"
        )
    return dimensions


def complete_mock_reward(
    corrected_task: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    schema = reward_schema(corrected_task)
    reward: dict[str, Any] = {}
    details: dict[str, Any] = {}
    for dimension, criteria in schema.items():
        reward[dimension] = 1.0
        details[dimension] = {
            "score": 1.0,
            "criteria": [
                {
                    "id": item["id"],
                    "name": item["id"].lower(),
                    "value": 1.0,
                    "raw": "yes",
                    "weight": 1.0,
                    "description": item["description"],
                    "reasoning": "mocked Gate 1 judge result",
                }
                for item in criteria
            ],
            "kind": "llm",
            "mock": True,
        }
    reward["output-integrity"] = 1.0
    details["output-integrity"] = {
        "score": 1.0,
        "criteria": [
            {
                "name": "valid_deliverable",
                "value": 1.0,
                "raw": True,
                "weight": 1.0,
                "description": (
                    "The required DOCX passed the verifier's archive and text-extraction checks."
                ),
            }
        ],
        "kind": "programmatic",
    }
    reward.update({"reward": 1.0, "all_pass": 1.0})
    return reward, details


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def assert_close(actual: Any, expected: float, label: str) -> None:
    if not is_number(actual) or abs(float(actual) - expected) > 0.0001:
        raise AdjudicationError(
            f"reward aggregate mismatch for {label}: expected {expected:.6f}, got {actual!r}"
        )


def validate_reward_files(
    logs_dir: Path,
    corrected_task: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reward_path = logs_dir / "reward.json"
    details_path = logs_dir / "reward-details.json"
    assert_regular_file(reward_path)
    assert_regular_file(details_path)
    reward = load_json(reward_path)
    details = load_json(details_path)
    if not isinstance(reward, dict) or not isinstance(details, dict):
        raise AdjudicationError("verifier reward outputs must be JSON objects")
    if has_nested_error(details):
        raise AdjudicationError("reward-details contains a nested verifier/judge error")
    schema = reward_schema(corrected_task)
    expected_dimensions = set(schema) | {"output-integrity"}
    if set(details) != expected_dimensions:
        raise AdjudicationError(
            "reward-details dimensions mismatch: "
            f"expected {sorted(expected_dimensions)}, got {sorted(details)}"
        )
    expected_reward_keys = expected_dimensions | {"reward", "all_pass"}
    if set(reward) != expected_reward_keys:
        raise AdjudicationError(
            "reward keys mismatch: "
            f"expected {sorted(expected_reward_keys)}, got {sorted(reward)}"
        )

    all_values: list[float] = []
    for dimension, expected_criteria in schema.items():
        detail = details[dimension]
        if not isinstance(detail, dict) or not isinstance(detail.get("criteria"), list):
            raise AdjudicationError(f"malformed reward details for {dimension}")
        actual_criteria = detail["criteria"]
        expected_by_id = {item["id"]: item for item in expected_criteria}
        actual_ids = [
            item.get("id") for item in actual_criteria if isinstance(item, dict)
        ]
        if len(actual_criteria) != len(expected_criteria) or set(actual_ids) != set(
            expected_by_id
        ):
            raise AdjudicationError(
                f"criterion coverage mismatch for {dimension}: "
                f"expected {sorted(expected_by_id)}, got {sorted(str(item) for item in actual_ids)}"
            )
        if len(actual_ids) != len(set(actual_ids)):
            raise AdjudicationError(f"duplicate criterion result in {dimension}")
        dimension_values: list[float] = []
        for criterion in actual_criteria:
            criterion_id = criterion["id"]
            if (
                criterion.get("description")
                != expected_by_id[criterion_id]["description"]
            ):
                raise AdjudicationError(
                    f"criterion description drift for {dimension}/{criterion_id}"
                )
            value = criterion.get("value")
            if not is_number(value) or float(value) not in (0.0, 1.0):
                raise AdjudicationError(
                    f"criterion value is not binary for {dimension}/{criterion_id}: {value!r}"
                )
            dimension_values.append(float(value))
        expected_score = sum(dimension_values) / len(dimension_values)
        assert_close(detail.get("score"), expected_score, f"details/{dimension}")
        assert_close(reward.get(dimension), expected_score, f"reward/{dimension}")
        all_values.extend(dimension_values)

    integrity = details["output-integrity"]
    integrity_criteria = (
        integrity.get("criteria") if isinstance(integrity, dict) else None
    )
    if not isinstance(integrity_criteria, list) or len(integrity_criteria) != 1:
        raise AdjudicationError("output-integrity must contain exactly one criterion")
    integrity_item = integrity_criteria[0]
    integrity_value = (
        integrity_item.get("value") if isinstance(integrity_item, dict) else None
    )
    if (
        not isinstance(integrity_item, dict)
        or integrity_item.get("name") != "valid_deliverable"
        or not is_number(integrity_value)
        or float(integrity_value) not in (0.0, 1.0)
    ):
        raise AdjudicationError("output-integrity criterion is malformed")
    integrity_number = float(integrity_value)
    assert_close(integrity.get("score"), integrity_number, "details/output-integrity")
    assert_close(
        reward.get("output-integrity"), integrity_number, "reward/output-integrity"
    )
    all_values.append(integrity_number)

    expected_reward = sum(all_values) / len(all_values)
    expected_all_pass = 1.0 if all(value == 1.0 for value in all_values) else 0.0
    assert_close(reward.get("reward"), expected_reward, "reward")
    assert_close(reward.get("all_pass"), expected_all_pass, "all_pass")
    return reward, details


def source_path(relative: str) -> Path:
    path = (REPO_ROOT / relative).resolve()
    if REPO_ROOT not in path.parents:
        raise AdjudicationError(f"source escapes repository: {relative}")
    return path


def validate_file_records(records: list[dict[str, Any]], label: str) -> None:
    for record in records:
        path = source_path(record["path"])
        assert_regular_file(path)
        if (
            path.stat().st_size != record["size"]
            or sha256_file(path) != record["sha256"]
        ):
            raise AdjudicationError(f"{label} provenance drift: {path}")


def validate_manifest_entry(source: dict[str, Any]) -> None:
    trial_dir = RAW_JOBS / source["source_job"] / source["source_trial"]
    manifest_path = trial_dir / "artifacts/manifest.json"
    assert_regular_file(manifest_path)
    if sha256_file(manifest_path) != source["original"]["artifact_manifest_sha256"]:
        raise AdjudicationError(f"artifact manifest hash mismatch: {trial_dir}")
    entries = load_json(manifest_path)
    matches = [
        item
        for item in entries
        if item.get("source") == source["artifact"]["source"]
        and item.get("destination") == source["artifact"]["destination"]
    ]
    if len(matches) != 1 or matches[0].get("status") != "ok":
        raise AdjudicationError(
            f"artifact manifest no longer has one status=ok entry: {trial_dir}"
        )


def validate_source(source: dict[str, Any]) -> Path:
    artifact = source_path(source["artifact"]["path"])
    validate_docx(artifact)
    if artifact.stat().st_size != source["artifact"]["size"]:
        raise AdjudicationError(f"artifact size mismatch: {artifact}")
    if sha256_file(artifact) != source["artifact"]["sha256"]:
        raise AdjudicationError(f"artifact hash mismatch: {artifact}")
    validate_manifest_entry(source)
    trial_dir = RAW_JOBS / source["source_job"] / source["source_trial"]
    checks = {
        "lock.json": source["original"]["trial_lock_sha256"],
        "config.json": source["original"]["trial_config_sha256"],
        "result.json": source["original"]["result_sha256"],
        "agent/trajectory.json": source["original"]["trajectory_sha256"],
        "verifier/reward.json": source["original"]["reward_sha256"],
        "verifier/reward-details.json": source["original"]["reward_details_sha256"],
    }
    for relative, expected in checks.items():
        path = trial_dir / relative
        assert_regular_file(path)
        if sha256_file(path) != expected:
            raise AdjudicationError(f"retained source hash mismatch: {path}")
    lock = load_json(trial_dir / "lock.json")
    if lock.get("task", {}).get("name") != source["task"]:
        raise AdjudicationError(f"trial lock task-name mismatch: {trial_dir}")
    if lock.get("task", {}).get("digest") != source["original_task_digest"]:
        raise AdjudicationError(f"trial lock task-digest mismatch: {trial_dir}")
    if lock.get("agent", {}).get("model_name") != source["source_agent_model"]:
        raise AdjudicationError(f"trial lock model mismatch: {trial_dir}")
    if (
        load_json(trial_dir / "verifier/reward.json")
        != source["original"]["reward_values"]
    ):
        raise AdjudicationError(f"original reward values mismatch: {trial_dir}")
    return artifact


def validate_commitment(commitment_path: Path) -> dict[str, Any]:
    assert_regular_file(commitment_path)
    commitment = load_json(commitment_path)
    if (
        commitment.get("schema_version")
        != "compute-bazaar-bench.adjudication-replay.v2"
    ):
        raise AdjudicationError("unsupported adjudication commitment schema")
    if commitment.get("record_kind") != "adjudication_replay":
        raise AdjudicationError("commitment is not an adjudication replay")
    if commitment.get("agent_rerun") is not False:
        raise AdjudicationError("commitment must state agent_rerun=false")
    sources = commitment.get("sources")
    if not isinstance(sources, list) or len(sources) != 43:
        raise AdjudicationError("commitment must contain exactly 43 sources")
    if canonical_json_sha256(sources) != commitment.get("sources_sha256"):
        raise AdjudicationError("commitment source-list hash mismatch")
    analysis = source_path(commitment["source_analysis"]["path"])
    assert_regular_file(analysis)
    if sha256_file(analysis) != commitment["source_analysis"]["sha256"]:
        raise AdjudicationError("source analysis hash mismatch")
    analysis_data = load_json(analysis)
    if not isinstance(analysis_data, dict) or not isinstance(
        analysis_data.get("models"), dict
    ):
        raise AdjudicationError("source analysis has no model records")
    if not set(SELECTED_MODEL_KEYS).issubset(analysis_data["models"]):
        raise AdjudicationError("source analysis lacks a selected model")
    protocol_files = commitment.get("source_protocol_files", [])
    if canonical_json_sha256(protocol_files) != commitment.get(
        "source_protocol_files_sha256"
    ):
        raise AdjudicationError("source protocol file-list hash mismatch")
    validate_file_records(protocol_files, "source protocol")
    source_jobs = commitment.get("source_jobs", [])
    if canonical_json_sha256(source_jobs) != commitment.get("source_jobs_sha256"):
        raise AdjudicationError("source job-list hash mismatch")
    for job in source_jobs:
        if len(job.get("files", [])) != 4:
            raise AdjudicationError(
                f"source job provenance is incomplete: {job.get('job')}"
            )
        if canonical_json_sha256(job["files"]) != job["files_sha256"]:
            raise AdjudicationError(f"source job file-list hash mismatch: {job['job']}")
        validate_file_records(job["files"], f"source job {job['job']}")
    policy = {
        key: commitment[key]
        for key in (
            "labels",
            "execution_origin",
            "agent_rerun",
            "judge",
            "runtime",
            "inclusion_rules",
            "retry_policy",
            "immutability",
        )
    }
    if canonical_json_sha256(policy) != commitment.get("policy_sha256"):
        raise AdjudicationError("replay policy hash mismatch")
    excluded = commitment.get("excluded_sources", [])
    if len(excluded) != 2 or canonical_json_sha256(excluded) != commitment.get(
        "excluded_sources_sha256"
    ):
        raise AdjudicationError("excluded-source commitment mismatch")
    analysis_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    expected_included: set[tuple[str, str]] = set()
    expected_excluded: set[tuple[str, str]] = set()
    for model_key in SELECTED_MODEL_KEYS:
        model = analysis_data["models"][model_key]
        if not isinstance(model.get("records"), list) or len(model["records"]) != 15:
            raise AdjudicationError(
                f"source analysis must contain 15 records for {model_key}"
            )
        for record in model.get("records", []):
            key = (model_key, record["trial"])
            if key in analysis_by_key:
                raise AdjudicationError(f"duplicate source analysis record: {key}")
            analysis_by_key[key] = record
            if record.get("model_key") != model_key or record.get("job") != model.get(
                "job"
            ):
                raise AdjudicationError(f"source analysis model/job mismatch: {key}")
            if record.get("infrastructure_error") is None:
                if not record.get("artifact_status_ok"):
                    raise AdjudicationError(
                        f"non-infrastructure analysis record lacks artifact: {key}"
                    )
                expected_included.add(key)
            else:
                expected_excluded.add(key)
    if len(expected_included) != 43 or len(expected_excluded) != 2:
        raise AdjudicationError(
            "frozen analysis denominator does not reconcile to 43 included and 2 excluded"
        )
    committed_excluded = {
        (row["source_model_key"], row["source_trial"]) for row in excluded
    }
    if committed_excluded != expected_excluded:
        raise AdjudicationError(
            "excluded trials do not match the frozen selected-model analysis"
        )
    for row in excluded:
        key = (row["source_model_key"], row["source_trial"])
        analysis_record = analysis_by_key.get(key)
        if not analysis_record or not analysis_record.get("infrastructure_error"):
            raise AdjudicationError(
                f"excluded trial lacks frozen infrastructure error: {key}"
            )
        if (
            sha256_bytes(analysis_record["infrastructure_error"].encode())
            != row["infrastructure_error_sha256"]
        ):
            raise AdjudicationError(f"excluded trial error hash mismatch: {key}")
        trial_dir = RAW_JOBS / row["source_job"] / row["source_trial"]
        if tree_manifest(trial_dir) != row["trial_tree"]:
            raise AdjudicationError(f"excluded trial tree drift: {trial_dir}")
    visible = ROOT / commitment["visible_surface_manifest"]["path"]
    assert_regular_file(visible)
    if sha256_file(visible) != commitment["visible_surface_manifest"]["sha256"]:
        raise AdjudicationError("visible-surface manifest hash mismatch")
    visible_manifest = load_json(visible)
    if not visible_manifest.get("all_visible_surfaces_equal"):
        raise AdjudicationError("visible-surface equivalence is not satisfied")
    visible_by_task = {item["task"]: item for item in visible_manifest["tasks"]}
    if set(visible_by_task) != set(TASK_NAMES):
        raise AdjudicationError("visible-surface task set mismatch")
    for task_name, row in visible_by_task.items():
        original = ROOT.parent / task_name
        if row["original_task_digest"] != ORIGINAL_TASK_DIGESTS[task_name]:
            raise AdjudicationError(
                f"visible manifest original digest mismatch: {task_name}"
            )
        if task_content_digest(original) != ORIGINAL_TASK_DIGESTS[task_name]:
            raise AdjudicationError(f"original task drift: {task_name}")
        corrected = ROOT / "verifier-v2" / task_name
        if task_content_digest(corrected) != row["corrected_task_digest"]:
            raise AdjudicationError(f"corrected task drift: {task_name}")
        tests_digest = tree_manifest(corrected / "tests")["tree_sha256"]
        if tests_digest != row["corrected_verifier_tree_sha256"]:
            raise AdjudicationError(f"corrected verifier drift: {task_name}")
    keys: set[tuple[str, str]] = set()
    included_analysis_keys: set[tuple[str, str]] = set()
    for source in sources:
        key = (source["source_job"], source["source_trial"])
        if key in keys:
            raise AdjudicationError(f"duplicate source trial: {key}")
        keys.add(key)
        row = visible_by_task[source["task"]]
        if source["corrected_task_digest"] != row["corrected_task_digest"]:
            raise AdjudicationError(f"source corrected task mismatch: {key}")
        if (
            source["corrected_verifier_tree_sha256"]
            != row["corrected_verifier_tree_sha256"]
        ):
            raise AdjudicationError(f"source corrected verifier mismatch: {key}")
        validate_source(source)
        analysis_key = (source["source_model_key"], source["source_trial"])
        analysis_record = analysis_by_key.get(analysis_key)
        if analysis_key not in expected_included or analysis_record is None:
            raise AdjudicationError(
                f"included trial is not an eligible frozen-analysis record: {analysis_key}"
            )
        if analysis_key in included_analysis_keys:
            raise AdjudicationError(
                f"duplicate included frozen-analysis record: {analysis_key}"
            )
        included_analysis_keys.add(analysis_key)
        expected_job = analysis_data["models"][source["source_model_key"]]["job"]
        if (
            source["source_job"] != expected_job
            or analysis_record.get("job") != source["source_job"]
            or analysis_record.get("task") != source["task"]
            or analysis_record.get("model_key") != source["source_model_key"]
            or analysis_record.get("artifact_status") != "ok"
            or analysis_record.get("artifact_status_ok") is not True
            or analysis_record.get("infrastructure_error") is not None
            or analysis_record.get("agent_invalid_output") is not False
        ):
            raise AdjudicationError(
                f"included source disagrees with frozen analysis: {analysis_key}"
            )
        original_reward = source["original"]["reward_values"]
        if (
            analysis_record.get("harbor_reward") != original_reward.get("reward")
            or analysis_record.get("all_pass") != original_reward.get("all_pass")
            or analysis_record.get("output_integrity")
            != original_reward.get("output-integrity")
        ):
            raise AdjudicationError(
                f"frozen analysis reward disagrees with retained reward: {analysis_key}"
            )
        trial_dir = RAW_JOBS / source["source_job"] / source["source_trial"]
        original_details = load_json(trial_dir / "verifier/reward-details.json")
        semantic_items = [
            criterion
            for dimension, detail in original_details.items()
            if dimension != "output-integrity" and isinstance(detail, dict)
            for criterion in detail.get("criteria", [])
            if isinstance(criterion, dict)
        ]
        semantic_passes = sum(
            float(item.get("value", 0.0)) == 1.0 for item in semantic_items
        )
        semantic_score = semantic_passes / len(semantic_items)
        if (
            analysis_record.get("semantic_criteria") != len(semantic_items)
            or analysis_record.get("semantic_passes") != semantic_passes
            or abs(float(analysis_record.get("semantic_score")) - semantic_score)
            > 1e-12
        ):
            raise AdjudicationError(
                f"frozen analysis semantic totals disagree with retained details: {analysis_key}"
            )
    if included_analysis_keys != expected_included:
        raise AdjudicationError(
            "included trials do not exactly match the frozen selected-model analysis"
        )
    if {row["job"] for row in source_jobs} != {
        source["source_job"] for source in sources
    }:
        raise AdjudicationError("source job provenance does not match retained sources")
    excluded_keys = {(row["source_job"], row["source_trial"]) for row in excluded}
    if keys & excluded_keys or len(keys | excluded_keys) != 45:
        raise AdjudicationError(
            "included and excluded trial denominator does not reconcile to 45"
        )
    return commitment


def replay_key(source: dict[str, Any]) -> str:
    return f"{source['source_model_key']}__{source['source_trial']}"


def base_record(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_kind": "adjudication_replay",
        "execution_origin": "preserved_agent_artifact",
        "agent_rerun": False,
        "source_job": source["source_job"],
        "source_trial": source["source_trial"],
        "source_model_key": source["source_model_key"],
        "task": source["task"],
        "original_task_digest": source["original_task_digest"],
        "corrected_task_digest": source["corrected_task_digest"],
        "corrected_verifier_tree_sha256": source["corrected_verifier_tree_sha256"],
    }


def failure_record(
    source: dict[str, Any],
    output_dir: Path,
    *,
    stage: str,
    message: str,
    runtime_identity: dict[str, Any] | None = None,
    returncode: int | None = None,
    artifact_before: str | None = None,
    artifact_after: str | None = None,
    status: str = "infrastructure_error",
) -> dict[str, Any]:
    record = {
        **base_record(source),
        "status": status,
        "failure_stage": stage,
        "failure_message": message,
        "returncode": returncode,
        "runtime_identity": runtime_identity,
        "artifact_sha256_before": artifact_before,
        "artifact_sha256_after": artifact_after,
        "amended_reward": None,
    }
    atomic_write_json(output_dir / "adjudication.json", record)
    return record


def replay_one(
    source: dict[str, Any],
    corrected_task: Path,
    output_dir: Path,
    runtime: VerifierRuntime,
) -> dict[str, Any]:
    ensure_outside_raw(output_dir)
    if output_dir.exists():
        raise AdjudicationError(
            f"refusing to overwrite adjudication output: {output_dir}"
        )
    artifact = validate_source(source)
    output_dir.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="compute-bazaar-adjudication-") as temp:
        temp_root = Path(temp)
        workspace = temp_root / "app"
        logs_dir = temp_root / "logs/verifier"
        workspace.mkdir(parents=True)
        logs_dir.mkdir(parents=True)
        staged = workspace / DELIVERABLES[source["task"]]
        shutil.copyfile(artifact, staged)
        staged.chmod(0o444)
        before = sha256_file(staged)
        if before != source["artifact"]["sha256"]:
            raise AdjudicationError(f"staged artifact hash mismatch: {artifact}")
        try:
            result = runtime.run(source["task"], corrected_task, workspace, logs_dir)
        except Exception as error:
            after_error = sha256_file(staged)
            return failure_record(
                source,
                output_dir,
                status=(
                    "integrity_error"
                    if after_error != before
                    else "infrastructure_error"
                ),
                stage=(
                    "artifact_post_verifier"
                    if after_error != before
                    else "verifier_runtime"
                ),
                message=str(error),
                runtime_identity=runtime.identity(source["task"]),
                artifact_before=before,
                artifact_after=after_error,
            )
        after = sha256_file(staged)
        (output_dir / "verifier-stdout.txt").write_text(result.stdout)
        (output_dir / "verifier-stderr.txt").write_text(result.stderr)
        if after != before:
            return failure_record(
                source,
                output_dir,
                status="integrity_error",
                stage="artifact_post_verifier",
                message=f"verifier mutated staged artifact copied from {artifact}",
                runtime_identity=result.runtime_identity,
                returncode=result.returncode,
                artifact_before=before,
                artifact_after=after,
            )
        if result.returncode != 0:
            return failure_record(
                source,
                output_dir,
                stage="verifier_process",
                message="corrected verifier exited nonzero",
                runtime_identity=result.runtime_identity,
                returncode=result.returncode,
                artifact_before=before,
                artifact_after=after,
            )
        try:
            reward, details = validate_reward_files(logs_dir, corrected_task)
        except (AdjudicationError, OSError, ValueError) as error:
            for filename in ("reward.json", "reward-details.json"):
                invalid = logs_dir / filename
                if invalid.is_file() and not invalid.is_symlink():
                    shutil.copyfile(invalid, output_dir / f"invalid-{filename}")
            return failure_record(
                source,
                output_dir,
                stage="reward_validation",
                message=str(error),
                runtime_identity=result.runtime_identity,
                returncode=result.returncode,
                artifact_before=before,
                artifact_after=after,
            )
        shutil.copyfile(logs_dir / "reward.json", output_dir / "reward.json")
        shutil.copyfile(
            logs_dir / "reward-details.json", output_dir / "reward-details.json"
        )
        record = {
            **base_record(source),
            "status": "valid",
            "runtime_identity": result.runtime_identity,
            "artifact_sha256_before": before,
            "artifact_sha256_after": after,
            "original_reward": source["original"]["reward_values"],
            "amended_reward": reward,
            "amended_reward_sha256": sha256_file(output_dir / "reward.json"),
            "amended_reward_details_sha256": sha256_file(
                output_dir / "reward-details.json"
            ),
            "nested_errors": has_nested_error(details),
        }
        atomic_write_json(output_dir / "adjudication.json", record)
        return record


def validate_attempt_record(source: dict[str, Any], record_dir: Path) -> dict[str, Any]:
    record_path = record_dir / "adjudication.json"
    assert_regular_file(record_path)
    record = load_json(record_path)
    if not isinstance(record, dict):
        raise AdjudicationError(f"adjudication record is not an object: {record_path}")
    expected_base = base_record(source)
    if any(record.get(key) != value for key, value in expected_base.items()):
        raise AdjudicationError(f"adjudication record source mismatch: {record_path}")
    status = record.get("status")
    if status not in {"valid", "infrastructure_error", "integrity_error"}:
        raise AdjudicationError(f"unknown adjudication record status: {record_path}")
    if status == "valid":
        corrected_task = ROOT / "verifier-v2" / source["task"]
        reward, details = validate_reward_files(record_dir, corrected_task)
        if (
            record.get("original_reward") != source["original"]["reward_values"]
            or record.get("amended_reward") != reward
            or record.get("amended_reward_sha256")
            != sha256_file(record_dir / "reward.json")
            or record.get("amended_reward_details_sha256")
            != sha256_file(record_dir / "reward-details.json")
            or record.get("nested_errors") != has_nested_error(details)
        ):
            raise AdjudicationError(f"adjudication reward record drift: {record_path}")
    elif record.get("amended_reward") is not None:
        raise AdjudicationError(
            f"failed adjudication record contains an amended reward: {record_path}"
        )
    return record


def record_result_row(
    run_dir: Path, source: dict[str, Any], record: dict[str, Any]
) -> dict[str, Any]:
    key = replay_key(source)
    path = run_dir / "records" / key / "adjudication.json"
    return {
        "replay_key": key,
        "source_job": record["source_job"],
        "source_trial": record["source_trial"],
        "task": record["task"],
        "status": record["status"],
        "record_path": (Path("records") / key / "adjudication.json").as_posix(),
        "record_sha256": sha256_file(path),
    }


def scan_attempt_records(
    run_dir: Path,
    selected_sources: list[dict[str, Any]],
    checkpoint: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    source_by_key = {replay_key(source): source for source in selected_sources}
    records_root = run_dir / "records"
    records: dict[str, dict[str, Any]] = {}
    if records_root.exists():
        if records_root.is_symlink() or not records_root.is_dir():
            raise AdjudicationError(
                f"invalid adjudication records directory: {records_root}"
            )
        for record_dir in sorted(records_root.iterdir()):
            if record_dir.is_symlink() or not record_dir.is_dir():
                raise AdjudicationError(
                    f"invalid adjudication record path: {record_dir}"
                )
            source = source_by_key.get(record_dir.name)
            if source is None:
                raise AdjudicationError(
                    f"attempt contains an unknown replay record: {record_dir}"
                )
            record_path = record_dir / "adjudication.json"
            if not record_path.is_file() or record_path.is_symlink():
                raise AdjudicationError(
                    "an in-flight record has no final adjudication checkpoint; "
                    f"automatic resume is blocked: {record_dir}"
                )
            record = validate_attempt_record(source, record_dir)
            if replay_key(record) != record_dir.name:
                raise AdjudicationError(
                    f"adjudication record key mismatch: {record_path}"
                )
            records[record_dir.name] = record

    if checkpoint is not None:
        checkpoint_rows: dict[str, dict[str, Any]] = {}
        for row in checkpoint.get("record_results", []):
            key = row.get("replay_key")
            if key in checkpoint_rows or key not in source_by_key:
                raise AdjudicationError(f"invalid checkpoint replay key: {key}")
            expected_relative = (
                Path("records") / str(key) / "adjudication.json"
            ).as_posix()
            if row.get("record_path") != expected_relative:
                raise AdjudicationError(f"checkpoint record path mismatch: {key}")
            path = run_dir / expected_relative
            assert_regular_file(path)
            if sha256_file(path) != row.get("record_sha256"):
                raise AdjudicationError(f"checkpoint record hash mismatch: {path}")
            record = records.get(str(key))
            if record is None or record.get("status") != row.get("status"):
                raise AdjudicationError(f"checkpoint record metadata mismatch: {path}")
            checkpoint_rows[str(key)] = row
        if checkpoint.get("status") != "running" and set(checkpoint_rows) != set(
            records
        ):
            raise AdjudicationError(
                "a finalized adjudication ledger does not match its record checkpoints"
            )
    return records


def build_run_record(
    *,
    commitment: dict[str, Any],
    commitment_sha256: str,
    attempt_id: str,
    retry_from: Path | None,
    retry_parent: dict[str, Any] | None,
    selected_sources: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    runtime_identities: dict[str, dict[str, Any]],
    run_dir: Path,
    running: bool,
    spend_gates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    counts = {
        status: sum(row["status"] == status for row in records.values())
        for status in ("valid", "infrastructure_error", "integrity_error")
    }
    if running:
        status = "running"
    elif counts["integrity_error"]:
        status = "integrity_failed"
    elif counts["valid"] == len(selected_sources):
        status = "complete"
    else:
        status = "infrastructure_incomplete"
    ordered_sources = [
        source for source in selected_sources if replay_key(source) in records
    ]
    return {
        "record_kind": "adjudication_replay_run",
        "adjudication_id": commitment["adjudication_id"],
        "attempt_id": attempt_id,
        "attempt_kind": "infrastructure_retry_only" if retry_from else "initial",
        "retry_parent": (
            {
                "path": str(retry_from.resolve()),
                "sha256": sha256_file(retry_from),
                "attempt_id": retry_parent.get("attempt_id") if retry_parent else None,
            }
            if retry_from
            else None
        ),
        "agent_rerun": False,
        "committed_sources": len(commitment["sources"]),
        "selected_sources": len(selected_sources),
        "attempted_sources": len(records),
        "remaining_sources": len(selected_sources) - len(records),
        **counts,
        "status": status,
        "source_commitment_sha256": commitment_sha256,
        "runtime_builds": runtime_identities,
        "spend_gates": spend_gates or [],
        "record_results": [
            record_result_row(run_dir, source, records[replay_key(source)])
            for source in ordered_sources
        ],
    }


def execute_replay(
    commitment_path: Path,
    output_root: Path,
    runtime: VerifierRuntime,
    *,
    attempt_id: str = "attempt-001",
    retry_from: Path | None = None,
    resume_attempt: bool = False,
    spend_gate: Path | None = None,
) -> dict[str, Any]:
    commitment = validate_commitment(commitment_path)
    if not (
        attempt_id.startswith("attempt-")
        and len(attempt_id) == 11
        and attempt_id.removeprefix("attempt-").isdigit()
    ):
        raise AdjudicationError("attempt ID must use attempt-NNN")
    if attempt_id != "attempt-001" and retry_from is None:
        raise AdjudicationError(
            "later attempts require --retry-from so valid grades cannot be replayed"
        )

    commitment_sha256 = sha256_file(commitment_path)
    spend_gates: list[dict[str, Any]] = []
    if spend_gate is not None:
        assert_regular_file(spend_gate)
        gate = load_json(spend_gate)
        if (
            gate.get("status") != "passed"
            or gate.get("source_commitment_sha256") != commitment_sha256
            or gate.get("adjudication_id") != commitment["adjudication_id"]
        ):
            raise AdjudicationError("paid replay requires a passing spend gate")
        spend_gates.append(
            {
                "path": str(spend_gate.resolve()),
                "sha256": sha256_file(spend_gate),
                "checked_at": gate.get("checked_at"),
                "account_remaining_usd": gate.get("account", {}).get(
                    "account_remaining_usd"
                ),
                "required_balance_usd": gate.get("estimate", {}).get(
                    "required_balance_usd"
                ),
            }
        )
    selected_sources = commitment["sources"]
    retry_parent: dict[str, Any] | None = None
    if retry_from is not None:
        assert_regular_file(retry_from)
        retry_parent = load_json(retry_from)
        if retry_parent.get("status") != "infrastructure_incomplete":
            raise AdjudicationError(
                "retry source must be a finalized infrastructure-incomplete attempt"
            )
        if retry_parent.get("source_commitment_sha256") != commitment_sha256:
            raise AdjudicationError("retry source uses a different commitment")
        if retry_parent.get("adjudication_id") != commitment["adjudication_id"]:
            raise AdjudicationError("retry source uses a different adjudication ID")
        if any(
            row.get("status") == "integrity_error"
            for row in retry_parent.get("record_results", [])
        ):
            raise AdjudicationError(
                "integrity failures require a repaired commitment, not an infrastructure retry"
            )
        parent_dir = retry_from.parent.resolve()
        for row in retry_parent.get("record_results", []):
            record_path = (parent_dir / row["record_path"]).resolve()
            if parent_dir not in record_path.parents:
                raise AdjudicationError(
                    "retry record path escapes its attempt directory"
                )
            assert_regular_file(record_path)
            if sha256_file(record_path) != row.get("record_sha256"):
                raise AdjudicationError(f"retry record hash mismatch: {record_path}")
            parent_record = load_json(record_path)
            if parent_record.get("status") != row.get("status") or replay_key(
                parent_record
            ) != row.get("replay_key"):
                raise AdjudicationError(
                    f"retry record metadata mismatch: {record_path}"
                )
        retry_keys = {
            row["replay_key"]
            for row in retry_parent.get("record_results", [])
            if row.get("status") == "infrastructure_error"
        }
        if not retry_keys:
            raise AdjudicationError("retry source has no infrastructure failures")
        selected_sources = [
            source
            for source in commitment["sources"]
            if replay_key(source) in retry_keys
        ]
        if {replay_key(source) for source in selected_sources} != retry_keys:
            raise AdjudicationError(
                "retry source contains unknown or duplicate replay keys"
            )

    run_dir = output_root / commitment["adjudication_id"] / attempt_id
    ensure_outside_raw(run_dir)
    checkpoint_path = run_dir / "adjudication-run.json"
    commitment_copy = run_dir / "commitment.json"
    checkpoint: dict[str, Any] | None = None
    if resume_attempt:
        if not run_dir.is_dir() or run_dir.is_symlink():
            raise AdjudicationError(
                f"cannot resume a missing or invalid adjudication run: {run_dir}"
            )
        assert_regular_file(commitment_copy)
        if sha256_file(commitment_copy) != commitment_sha256:
            raise AdjudicationError("attempt commitment copy does not match the source")
        assert_regular_file(checkpoint_path)
        checkpoint = load_json(checkpoint_path)
        expected_kind = "infrastructure_retry_only" if retry_from else "initial"
        if (
            checkpoint.get("adjudication_id") != commitment["adjudication_id"]
            or checkpoint.get("attempt_id") != attempt_id
            or checkpoint.get("attempt_kind") != expected_kind
            or checkpoint.get("source_commitment_sha256") != commitment_sha256
        ):
            raise AdjudicationError("attempt checkpoint does not match this replay")
        expected_parent_hash = sha256_file(retry_from) if retry_from else None
        actual_parent_hash = (
            checkpoint.get("retry_parent", {}).get("sha256")
            if checkpoint.get("retry_parent")
            else None
        )
        if actual_parent_hash != expected_parent_hash:
            raise AdjudicationError("attempt checkpoint retry parent mismatch")
        prior_gates = checkpoint.get("spend_gates", [])
        if not isinstance(prior_gates, list):
            raise AdjudicationError("attempt checkpoint spend-gate history is malformed")
        known_gate_hashes = {row.get("sha256") for row in prior_gates}
        spend_gates = [*prior_gates, *[row for row in spend_gates if row["sha256"] not in known_gate_hashes]]
    else:
        if run_dir.exists():
            raise AdjudicationError(
                f"refusing to overwrite adjudication run: {run_dir}"
            )
        run_dir.mkdir(parents=True)
        shutil.copyfile(commitment_path, commitment_copy)

    records = scan_attempt_records(run_dir, selected_sources, checkpoint)
    if any(record["status"] == "integrity_error" for record in records.values()):
        raise AdjudicationError(
            "an integrity failure blocks automatic continuation or retry"
        )
    if checkpoint is not None and checkpoint.get("status") != "running":
        if len(records) != len(selected_sources):
            raise AdjudicationError(
                "a finalized attempt cannot be resumed with unattempted records"
            )
        return checkpoint

    running_record = build_run_record(
        commitment=commitment,
        commitment_sha256=commitment_sha256,
        attempt_id=attempt_id,
        retry_from=retry_from,
        retry_parent=retry_parent,
        selected_sources=selected_sources,
        records=records,
        runtime_identities={
            task: runtime.identity(task)
            for task in sorted({source["task"] for source in selected_sources})
        },
        run_dir=run_dir,
        running=True,
        spend_gates=spend_gates,
    )
    atomic_write_json(checkpoint_path, running_record)
    prepared: set[str] = set()
    preparation_errors: dict[str, str] = {}
    for source in selected_sources:
        key = replay_key(source)
        if key in records:
            continue
        task_name = source["task"]
        corrected_task = ROOT / "verifier-v2" / task_name
        if task_name not in prepared and task_name not in preparation_errors:
            try:
                runtime.prepare(
                    task_name,
                    corrected_task,
                    source["corrected_verifier_tree_sha256"],
                )
                prepared.add(task_name)
            except Exception as error:
                preparation_errors[task_name] = str(error)
        record_dir = run_dir / "records" / replay_key(source)
        if task_name in preparation_errors:
            record_dir.mkdir(parents=True)
            record = failure_record(
                source,
                record_dir,
                stage="verifier_prepare",
                message=preparation_errors[task_name],
                runtime_identity=runtime.identity(task_name),
            )
        else:
            record = replay_one(
                source,
                corrected_task,
                record_dir,
                runtime,
            )
        records[key] = record
        running_record = build_run_record(
            commitment=commitment,
            commitment_sha256=commitment_sha256,
            attempt_id=attempt_id,
            retry_from=retry_from,
            retry_parent=retry_parent,
            selected_sources=selected_sources,
            records=records,
            runtime_identities={
                task: runtime.identity(task)
                for task in sorted({source["task"] for source in selected_sources})
            },
            run_dir=run_dir,
            running=True,
            spend_gates=spend_gates,
        )
        atomic_write_json(checkpoint_path, running_record)
        if record["status"] == "integrity_error":
            break

    run_record = build_run_record(
        commitment=commitment,
        commitment_sha256=commitment_sha256,
        attempt_id=attempt_id,
        retry_from=retry_from,
        retry_parent=retry_parent,
        selected_sources=selected_sources,
        records=records,
        runtime_identities={
            task: runtime.identity(task)
            for task in sorted({source["task"] for source in selected_sources})
        },
        run_dir=run_dir,
        running=False,
        spend_gates=spend_gates,
    )
    atomic_write_json(checkpoint_path, run_record)
    return run_record


def run_modal_preflight(
    commitment_path: Path,
    output_root: Path,
    *,
    preflight_id: str = "modal-preflight-001",
) -> dict[str, Any]:
    from modal_backend import ModalVerifierRuntime

    commitment = validate_commitment(commitment_path)
    commitment_sha256 = sha256_file(commitment_path)
    run_dir = output_root / commitment["adjudication_id"] / preflight_id
    ensure_outside_raw(run_dir)
    if run_dir.exists():
        raise AdjudicationError(f"refusing to overwrite Modal preflight: {run_dir}")
    run_dir.mkdir(parents=True)
    shutil.copyfile(commitment_path, run_dir / "commitment.json")

    selected: list[dict[str, Any]] = []
    for task_name in TASK_NAMES:
        source = next(
            source for source in commitment["sources"] if source["task"] == task_name
        )
        selected.append(source)
    mock_rewards = {
        task_name: complete_mock_reward(ROOT / "verifier-v2" / task_name)
        for task_name in TASK_NAMES
    }
    runtime: ModalVerifierRuntime | None = None
    records: list[dict[str, Any]] = []

    def checkpoint(status: str) -> dict[str, Any]:
        report = {
            "schema_version": "compute-bazaar-bench.modal-preflight.v1",
            "record_kind": "adjudication_replay_preflight",
            "preflight_id": preflight_id,
            "adjudication_id": commitment["adjudication_id"],
            "source_commitment_sha256": commitment_sha256,
            "backend": "modal_sandbox",
            "paid_judge_calls": 0,
            "network_policy": "blocked",
            "judge_secret_injected": False,
            "selected_sources": len(selected),
            "completed_sources": len(records),
            "status": status,
            "runtime_builds": {
                task: (
                    runtime.identity(task)
                    if runtime is not None
                    else {
                        "backend": "modal_sandbox",
                        "build_status": "not_connected",
                        "mode": "mock_preflight",
                    }
                )
                for task in sorted(TASK_NAMES)
            },
            "records": records,
        }
        atomic_write_json(run_dir / "modal-preflight.json", report)
        return report

    checkpoint("connecting")
    try:
        runtime = ModalVerifierRuntime(mock_rewards=mock_rewards)
        checkpoint("building")
        for task_name in TASK_NAMES:
            source = next(row for row in selected if row["task"] == task_name)
            runtime.prepare(
                task_name,
                ROOT / "verifier-v2" / task_name,
                source["corrected_verifier_tree_sha256"],
            )
            checkpoint("running")
        for source in selected:
            task_name = source["task"]
            artifact = validate_source(source)
            key = replay_key(source)
            record_dir = run_dir / "records" / key
            record_dir.mkdir(parents=True)
            with tempfile.TemporaryDirectory(
                prefix="compute-bazaar-modal-preflight-"
            ) as temp:
                temp_root = Path(temp)
                workspace = temp_root / "app"
                logs_dir = temp_root / "logs/verifier"
                workspace.mkdir(parents=True)
                logs_dir.mkdir(parents=True)
                staged = workspace / DELIVERABLES[task_name]
                shutil.copyfile(artifact, staged)
                staged.chmod(0o444)
                before = sha256_file(staged)
                result = runtime.run(
                    task_name,
                    ROOT / "verifier-v2" / task_name,
                    workspace,
                    logs_dir,
                )
                after = sha256_file(staged)
                if result.returncode != 0:
                    raise AdjudicationError(
                        f"mock verifier failed for {task_name}: {result.stderr}"
                    )
                reward, details = validate_reward_files(
                    logs_dir, ROOT / "verifier-v2" / task_name
                )
                identity = result.runtime_identity
                sandbox = identity.get("last_sandbox") or {}
                required_probes = (
                    sandbox.get("secret_absent") is True
                    and sandbox.get("network_probe_blocked") is True
                    and sandbox.get("unprivileged_write_denied") is True
                    and sandbox.get("terminated") is True
                    and sandbox.get("detached") is True
                    and sandbox.get("artifact_sha256_before") == before
                    and sandbox.get("artifact_sha256_after") == after
                    and before == after == source["artifact"]["sha256"]
                )
                if not required_probes:
                    raise AdjudicationError(
                        f"Modal boundary probe failed for {task_name}: {sandbox}"
                    )
                shutil.copyfile(logs_dir / "reward.json", record_dir / "reward.json")
                shutil.copyfile(
                    logs_dir / "reward-details.json",
                    record_dir / "reward-details.json",
                )
                (record_dir / "verifier-stdout.txt").write_text(result.stdout)
                (record_dir / "verifier-stderr.txt").write_text(result.stderr)
                record = {
                    "replay_key": key,
                    "task": task_name,
                    "source_job": source["source_job"],
                    "source_trial": source["source_trial"],
                    "artifact_sha256_before": before,
                    "artifact_sha256_after": after,
                    "reward_sha256": sha256_file(record_dir / "reward.json"),
                    "reward_details_sha256": sha256_file(
                        record_dir / "reward-details.json"
                    ),
                    "reward": reward,
                    "nested_errors": has_nested_error(details),
                    "runtime_identity": identity,
                    "status": "passed",
                }
                atomic_write_json(record_dir / "preflight.json", record)
                records.append(
                    {
                        "replay_key": key,
                        "task": task_name,
                        "status": "passed",
                        "record_path": (
                            Path("records") / key / "preflight.json"
                        ).as_posix(),
                        "record_sha256": sha256_file(record_dir / "preflight.json"),
                    }
                )
                checkpoint("running")
    except Exception as error:
        failed = checkpoint("failed")
        failed["failure"] = str(error)
        atomic_write_json(run_dir / "modal-preflight.json", failed)
        raise
    return checkpoint("passed")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay corrected Transactions verifiers over preserved DOCX files."
    )
    parser.add_argument("--commitment", type=Path, default=DEFAULT_COMMITMENT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--attempt-id", default="attempt-001")
    parser.add_argument(
        "--retry-from",
        type=Path,
        help="prior adjudication-run.json; retries only its infrastructure failures",
    )
    parser.add_argument(
        "--resume-attempt",
        action="store_true",
        help="recover final record checkpoints and continue only unattempted records",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="verify all Gate 1 hashes and inputs without building or running a verifier",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run the paid corrected verifier replay",
    )
    parser.add_argument(
        "--modal-preflight",
        action="store_true",
        help="build all verifier-v2 images and run three mocked, network-blocked Modal checks",
    )
    parser.add_argument(
        "--balance-check",
        action="store_true",
        help="record the live OpenRouter balance gate without judge calls",
    )
    parser.add_argument("--preflight-id", default="modal-preflight-001")
    parser.add_argument(
        "--backend",
        choices=("modal", "docker"),
        default="modal",
        help="execution backend; Gate 2 uses Modal",
    )
    parser.add_argument(
        "--acknowledge-paid-judge",
        action="store_true",
        help="required acknowledgement for 129 expected GPT-5.4 judge calls",
    )
    args = parser.parse_args()
    if sum(
        (args.validate_only, args.execute, args.modal_preflight, args.balance_check)
    ) != 1:
        parser.error(
            "choose exactly one of --validate-only, --modal-preflight, --balance-check, or --execute"
        )
    commitment = validate_commitment(args.commitment)
    if args.validate_only:
        print(
            f"validated {len(commitment['sources'])} preserved outputs; "
            "no verifier or judge was run"
        )
        return
    if args.modal_preflight:
        if args.backend != "modal":
            parser.error("--modal-preflight requires --backend modal")
        report = run_modal_preflight(
            args.commitment,
            args.output_root,
            preflight_id=args.preflight_id,
        )
        if report["status"] != "passed":
            raise SystemExit(2)
        return
    openrouter_key = load_repo_secret("OPENROUTER_API_KEY")
    if not openrouter_key:
        parser.error("OPENROUTER_API_KEY is required for the live balance gate")
    from openrouter_gate import check_openrouter_gate

    gate = check_openrouter_gate(
        api_key=openrouter_key,
        commitment=commitment,
        commitment_path=args.commitment,
        repo_root=REPO_ROOT,
        adjudication_root=ROOT,
    )
    gate_root = (
        args.output_root / commitment["adjudication_id"] / "spend-gates"
    )
    ensure_outside_raw(gate_root)
    gate_root.mkdir(parents=True, exist_ok=True)
    gate_index = 1
    while (gate_root / f"openrouter-gate-{gate_index:03d}.json").exists():
        gate_index += 1
    gate_path = gate_root / f"openrouter-gate-{gate_index:03d}.json"
    atomic_write_json(gate_path, gate)
    print(
        f"OpenRouter gate {gate['status']}: "
        f"${gate['account']['account_remaining_usd']:.4f} available; "
        f"${gate['estimate']['required_balance_usd']:.4f} required; "
        f"recorded at {gate_path}"
    )
    if args.balance_check:
        if gate["status"] != "passed":
            raise SystemExit(2)
        return
    if not args.acknowledge_paid_judge:
        parser.error("--execute requires --acknowledge-paid-judge")
    if args.backend != "modal":
        parser.error("Gate 2 paid execution requires --backend modal")
    if gate["status"] != "passed":
        raise SystemExit(2)
    if args.backend == "modal":
        from modal_backend import ModalVerifierRuntime

        runtime: VerifierRuntime = ModalVerifierRuntime(openrouter_key=openrouter_key)
    else:
        os.environ["OPENROUTER_API_KEY"] = openrouter_key
        runtime = DockerVerifierRuntime()
    run = execute_replay(
        args.commitment,
        args.output_root,
        runtime,
        attempt_id=args.attempt_id,
        retry_from=args.retry_from,
        resume_attempt=args.resume_attempt,
        spend_gate=gate_path,
    )
    if run["status"] != "complete":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
