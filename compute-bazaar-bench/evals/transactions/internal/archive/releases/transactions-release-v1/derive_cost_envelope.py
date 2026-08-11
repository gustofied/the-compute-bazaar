from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import tomllib
import xml.etree.ElementTree as ET
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[4]
TRANSACTIONS_ROOT = ROOT.parents[1]
REPLAY_ROOT = (
    REPO_ROOT / "compute-bazaar-bench/jobs/adjudications/"
    "transactions-comparison-v1-adjudication-replay-001/attempt-001"
)
ORACLE_ROOT = (
    REPO_ROOT / "compute-bazaar-bench/jobs/raw/transactions-release-v1-oracle-001"
)
PRE_GATE = REPLAY_ROOT.parent / "spend-gates/openrouter-gate-002.json"
POST_GATE = REPLAY_ROOT.parent / "spend-gates/openrouter-gate-007.json"
ENTRY_GATE = (
    REPO_ROOT / "compute-bazaar-bench/jobs/reports/transactions-release-v1/"
    "live-gates/entry-002.json"
)
POST_ORACLE_GATE = ENTRY_GATE.parent / "post-oracle-001.json"

PROMPT_PRICE = Decimal("0.0000025")
COMPLETION_PRICE = Decimal("0.000015")
CHARACTERS_PER_TOKEN = Decimal("4")
RECORD_CONTINGENCY = Decimal("0.25")

ORACLE_ARTIFACTS = {
    "normalize-buyer-mandate": (
        TRANSACTIONS_ROOT / "normalize-buyer-mandate/solution/buyer-mandate-brief.docx"
    ),
    "draft-capacity-data-room-population-plan": (
        TRANSACTIONS_ROOT / "draft-capacity-data-room-population-plan/solution/"
        "capacity-data-room-population-plan.docx"
    ),
    "compare-capacity-agreement-against-term-sheet": (
        TRANSACTIONS_ROOT / "compare-capacity-agreement-against-term-sheet/solution/"
        "capacity-agreement-deviation-report.docx"
    ),
}


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def docx_text_characters(path: Path) -> int:
    with ZipFile(path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
    return sum(
        len(node.text or "") + 1 for node in document.iter() if node.tag.endswith("}t")
    )


def visible_cost(
    task_name: str,
    artifact_path: Path,
    reward_details_path: Path,
) -> Decimal:
    tests = TRANSACTIONS_ROOT / task_name / "tests"
    document_characters = docx_text_characters(artifact_path)
    shared_characters = sum(
        len((tests / filename).read_text())
        for filename in ("source-context.md", "judge-prompt.md")
    )
    reward_details = load_json(reward_details_path)
    input_characters = 0
    output_characters = 0
    dimensions = sorted(tests.glob("*/quality.toml"))
    if len(dimensions) != 3:
        raise RuntimeError(f"expected three dimensions: {task_name}")
    for quality_path in dimensions:
        quality = tomllib.loads(quality_path.read_text())
        input_characters += (
            document_characters
            + shared_characters
            + sum(
                len(str(item.get("description", "")))
                for item in quality.get("criterion", [])
            )
            + len((quality_path.parent / "evidence.md").read_text())
        )
        detail = reward_details.get(quality_path.parent.name)
        if not isinstance(detail, dict) or not isinstance(
            detail.get("judge_output"), str
        ):
            raise RuntimeError(
                f"missing judge output: {reward_details_path} {quality_path.parent.name}"
            )
        output_characters += len(detail["judge_output"])
    return (
        Decimal(input_characters) / CHARACTERS_PER_TOKEN * PROMPT_PRICE
        + Decimal(output_characters) / CHARACTERS_PER_TOKEN * COMPLETION_PRICE
    )


def derive() -> dict:
    pre = load_json(PRE_GATE)
    post = load_json(POST_GATE)
    actual_replay_cost = Decimal(str(post["account"]["total_usage_usd"])) - Decimal(
        str(pre["account"]["total_usage_usd"])
    )

    records = []
    for record_path in sorted((REPLAY_ROOT / "records").glob("*/adjudication.json")):
        record = load_json(record_path)
        if record.get("status") != "valid":
            raise RuntimeError(f"replay record is not valid: {record_path}")
        details_path = record_path.parent / "reward-details.json"
        artifact_path = (
            REPO_ROOT
            / "compute-bazaar-bench/jobs/raw"
            / record["source_job"]
            / record["source_trial"]
            / "artifacts/app"
            / ORACLE_ARTIFACTS[record["task"]].name
        )
        records.append(
            {
                "task": record["task"],
                "source_job": record["source_job"],
                "source_trial": record["source_trial"],
                "visible_cost": visible_cost(
                    record["task"], artifact_path, details_path
                ),
            }
        )
    if len(records) != 43:
        raise RuntimeError(f"expected 43 replay records, found {len(records)}")

    visible_replay_cost = sum(
        (row["visible_cost"] for row in records), start=Decimal("0")
    )
    calibration_factor = actual_replay_cost / visible_replay_cost
    for row in records:
        row["calibrated_cost"] = row["visible_cost"] * calibration_factor
    largest_record = max(records, key=lambda row: row["calibrated_cost"])
    record_envelope = largest_record["calibrated_cost"] * (
        Decimal("1") + RECORD_CONTINGENCY
    )

    oracle_trials = {}
    for task_name, artifact_path in ORACLE_ARTIFACTS.items():
        trial_dirs = [
            path
            for path in ORACLE_ROOT.iterdir()
            if path.is_dir()
            and Path(load_json(path / "config.json")["task"]["path"]).name == task_name
        ]
        if len(trial_dirs) != 1:
            raise RuntimeError(f"expected one Oracle -001 trial: {task_name}")
        visible = visible_cost(
            task_name,
            artifact_path,
            trial_dirs[0] / "verifier/reward-details.json",
        )
        oracle_trials[task_name] = {
            "visible_cost_usd": float(visible),
            "reference_trial": trial_dirs[0].name,
        }

    entry_gate = load_json(ENTRY_GATE)
    post_oracle_gate = load_json(POST_ORACLE_GATE)
    actual_oracle_cost = Decimal(
        str(entry_gate["account"]["account_remaining_usd"])
    ) - Decimal(str(post_oracle_gate["account"]["account_remaining_usd"]))
    oracle_visible_total = sum(
        (Decimal(str(row["visible_cost_usd"])) for row in oracle_trials.values()),
        start=Decimal("0"),
    )
    oracle_calibration_factor = actual_oracle_cost / oracle_visible_total
    for row in oracle_trials.values():
        row["oracle_calibrated_expected_usd"] = float(
            Decimal(str(row["visible_cost_usd"])) * oracle_calibration_factor
        )

    repaired_tasks = ("draft-capacity-data-room-population-plan",)
    repaired_oracle_expected = sum(
        (
            Decimal(str(oracle_trials[task]["oracle_calibrated_expected_usd"]))
            for task in repaired_tasks
        ),
        start=Decimal("0"),
    )
    return {
        "schema_version": "compute-bazaar-bench.transactions.cost-envelope.v1",
        "method": (
            "Each replay record is priced from its exact DOCX text, release-grader "
            "evidence and criteria, and retained judge JSON at four characters per "
            "token. The estimates are scaled to the independently reconciled 129-call "
            "OpenRouter account delta. The largest calibrated three-call record then "
            "receives a further 25 percent reserve."
        ),
        "replay": {
            "records": len(records),
            "judge_calls": len(records) * 3,
            "actual_cost_usd": float(actual_replay_cost),
            "visible_estimate_usd": float(visible_replay_cost),
            "calibration_factor": float(calibration_factor),
            "largest_calibrated_record": {
                "task": largest_record["task"],
                "source_job": largest_record["source_job"],
                "source_trial": largest_record["source_trial"],
                "cost_usd": float(largest_record["calibrated_cost"]),
            },
            "record_contingency_fraction": float(RECORD_CONTINGENCY),
            "record_cost_envelope_usd": float(record_envelope),
        },
        "oracle": {
            "reference_job": "transactions-release-v1-oracle-001",
            "actual_cost_usd": float(actual_oracle_cost),
            "visible_estimate_usd": float(oracle_visible_total),
            "calibration_factor": float(oracle_calibration_factor),
            "trials": oracle_trials,
            "repaired_tasks": list(repaired_tasks),
            "repaired_tasks_expected_usd": float(repaired_oracle_expected),
        },
        "limitations": [
            "RewardKit 0.1.7 did not retain OpenRouter generation IDs or per-call usage.",
            "The account key cannot access OpenRouter's management-only activity API.",
            "The record envelope is an empirical budgeting bound, not a provider guarantee.",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(derive(), indent=2))
