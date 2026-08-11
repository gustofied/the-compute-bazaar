from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import tomllib
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile

from common import AdjudicationError, load_json, sha256_file


OPENROUTER_API = "https://openrouter.ai/api/v1"
JUDGE_MODEL = "openai/gpt-5.4"
CHARACTERS_PER_TOKEN = Decimal("4")
UNCERTAINTY_MULTIPLIER = Decimal("2")


def _request_json(path: str, api_key: str) -> dict[str, Any]:
    request = Request(
        f"{OPENROUTER_API}/{path}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise AdjudicationError(
            f"OpenRouter balance gate could not read /{path}: {error}"
        ) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), (dict, list)):
        raise AdjudicationError(f"OpenRouter /{path} returned an unexpected payload")
    return payload


def _docx_text_characters(path: Path) -> int:
    try:
        with zipfile.ZipFile(path) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, ET.ParseError) as error:
        raise AdjudicationError(f"cannot estimate DOCX judge input for {path}") from error
    return sum(len(node.text or "") + 1 for node in document.iter() if node.tag.endswith("}t"))


def estimate_frozen_calls(
    commitment: dict[str, Any], repo_root: Path, adjudication_root: Path
) -> dict[str, Any]:
    input_characters = 0
    output_reference_characters = 0
    call_count = 0
    by_task: dict[str, dict[str, int]] = {}

    for source in commitment["sources"]:
        task_name = source["task"]
        task = adjudication_root / "verifier-v2" / task_name
        tests = task / "tests"
        artifact = repo_root / source["artifact"]["path"]
        document_characters = _docx_text_characters(artifact)
        shared_characters = sum(
            len((tests / filename).read_text())
            for filename in ("source-context.md", "judge-prompt.md")
        )
        task_stats = by_task.setdefault(
            task_name,
            {"calls": 0, "input_characters": 0, "output_reference_characters": 0},
        )

        original_details = load_json(
            repo_root
            / "compute-bazaar-bench/jobs/raw"
            / source["source_job"]
            / source["source_trial"]
            / "verifier/reward-details.json"
        )
        dimensions = sorted(tests.glob("*/quality.toml"))
        if len(dimensions) != 3:
            raise AdjudicationError(
                f"expected three RewardKit calls for {task_name}, found {len(dimensions)}"
            )
        for quality_path in dimensions:
            quality = tomllib.loads(quality_path.read_text())
            criteria = quality.get("criterion", [])
            criterion_characters = sum(
                len(str(item.get("description", ""))) for item in criteria
            )
            evidence_characters = len((quality_path.parent / "evidence.md").read_text())
            dimension_input = (
                document_characters
                + shared_characters
                + criterion_characters
                + evidence_characters
            )
            detail = original_details.get(quality_path.parent.name)
            if not isinstance(detail, dict) or not isinstance(
                detail.get("judge_output"), str
            ):
                raise AdjudicationError(
                    f"original judge output is unavailable for {source['source_trial']} "
                    f"dimension {quality_path.parent.name}"
                )
            dimension_output = len(detail["judge_output"])
            input_characters += dimension_input
            output_reference_characters += dimension_output
            call_count += 1
            task_stats["calls"] += 1
            task_stats["input_characters"] += dimension_input
            task_stats["output_reference_characters"] += dimension_output

    expected_calls = commitment["judge"]["expected_paid_judge_calls"]
    if call_count != expected_calls:
        raise AdjudicationError(
            f"judge-call estimate mismatch: expected {expected_calls}, got {call_count}"
        )
    return {
        "method": (
            "Agent-visible DOCX XML text, complete verifier-v2 evidence, criteria, "
            "source context, and judge prompt; output reference is the retained v1 "
            "judge JSON. Four characters per token and a 2x total-cost reserve cover "
            "RewardKit wrappers, tokenization variance, and unreported reasoning."
        ),
        "calls": call_count,
        "input_characters": input_characters,
        "output_reference_characters": output_reference_characters,
        "characters_per_token": float(CHARACTERS_PER_TOKEN),
        "uncertainty_multiplier": float(UNCERTAINTY_MULTIPLIER),
        "by_task": by_task,
        "limitations": [
            "This is a conservative planning estimate, not an OpenRouter quote or hard upper bound.",
            "RewardKit 0.1.7 does not retain provider usage or cap the judge completion length.",
            "Hidden reasoning tokens and provider reservation behavior are not observable before execution.",
        ],
    }


def evaluate_gate(
    *,
    commitment: dict[str, Any],
    commitment_sha256: str,
    repo_root: Path,
    adjudication_root: Path,
    key_payload: dict[str, Any],
    credits_payload: dict[str, Any],
    models_payload: dict[str, Any],
) -> dict[str, Any]:
    key_data = key_payload["data"]
    credits = credits_payload["data"]
    models = models_payload["data"]
    if not isinstance(key_data, dict) or not isinstance(credits, dict) or not isinstance(models, list):
        raise AdjudicationError("OpenRouter balance gate received malformed account data")
    model = next((item for item in models if item.get("id") == JUDGE_MODEL), None)
    if not isinstance(model, dict):
        raise AdjudicationError(f"frozen judge is absent from OpenRouter catalog: {JUDGE_MODEL}")
    pricing = model.get("pricing")
    if not isinstance(pricing, dict):
        raise AdjudicationError("OpenRouter judge pricing is unavailable")
    prompt_price = Decimal(str(pricing.get("prompt")))
    completion_price = Decimal(str(pricing.get("completion")))
    if prompt_price <= 0 or completion_price <= 0:
        raise AdjudicationError("OpenRouter judge pricing is not positive")

    estimate = estimate_frozen_calls(commitment, repo_root, adjudication_root)
    estimated_input_tokens = Decimal(estimate["input_characters"]) / CHARACTERS_PER_TOKEN
    estimated_output_tokens = (
        Decimal(estimate["output_reference_characters"]) / CHARACTERS_PER_TOKEN
    )
    estimated_visible_cost = (
        estimated_input_tokens * prompt_price
        + estimated_output_tokens * completion_price
    )
    required_balance = estimated_visible_cost * UNCERTAINTY_MULTIPLIER
    total_credits = Decimal(str(credits.get("total_credits")))
    total_usage = Decimal(str(credits.get("total_usage")))
    account_remaining = total_credits - total_usage
    key_remaining_raw = key_data.get("limit_remaining")
    key_remaining = (
        Decimal(str(key_remaining_raw)) if key_remaining_raw is not None else None
    )
    balance_ok = account_remaining >= required_balance
    key_limit_ok = key_remaining is None or key_remaining >= required_balance
    status = "passed" if balance_ok and key_limit_ok else "blocked"

    key_label = str(key_data.get("label") or "")
    sanitized_label = (
        f"{key_label[:12]}...{key_label[-4:]}" if len(key_label) > 20 else key_label
    )
    return {
        "schema_version": "compute-bazaar-bench.openrouter-spend-gate.v1",
        "record_kind": "openrouter_spend_gate",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "adjudication_id": commitment["adjudication_id"],
        "source_commitment_sha256": commitment_sha256,
        "judge": {
            "configured": commitment["judge"]["model"],
            "catalog_id": model["id"],
            "canonical_slug": model.get("canonical_slug"),
            "prompt_usd_per_token": str(prompt_price),
            "completion_usd_per_token": str(completion_price),
            "context_length": model.get("context_length"),
            "max_completion_tokens": (model.get("top_provider") or {}).get(
                "max_completion_tokens"
            ),
            "rewardkit_version": commitment["judge"]["rewardkit_version"],
            "expected_calls": commitment["judge"]["expected_paid_judge_calls"],
        },
        "account": {
            "key_label": sanitized_label,
            "key_limit_usd": key_data.get("limit"),
            "key_limit_remaining_usd": (
                float(key_remaining) if key_remaining is not None else None
            ),
            "key_usage_usd": key_data.get("usage"),
            "total_credits_usd": float(total_credits),
            "total_usage_usd": float(total_usage),
            "account_remaining_usd": float(account_remaining),
        },
        "estimate": {
            **estimate,
            "estimated_input_tokens": float(estimated_input_tokens),
            "estimated_reference_output_tokens": float(estimated_output_tokens),
            "estimated_visible_cost_usd": float(estimated_visible_cost),
            "required_balance_usd": float(required_balance),
            "account_headroom_usd": float(account_remaining - required_balance),
        },
        "checks": {
            "account_balance_covers_required_reserve": balance_ok,
            "key_limit_covers_required_reserve": key_limit_ok,
            "judge_matches_frozen_config": commitment["judge"]["model"]
            == f"openrouter/{JUDGE_MODEL}",
        },
        "decision": (
            "The paid replay may start immediately from this live snapshot."
            if status == "passed"
            else "Stop before paid judge execution; available balance does not meet the frozen reserve."
        ),
    }


def check_openrouter_gate(
    *,
    api_key: str,
    commitment: dict[str, Any],
    commitment_path: Path,
    repo_root: Path,
    adjudication_root: Path,
) -> dict[str, Any]:
    return evaluate_gate(
        commitment=commitment,
        commitment_sha256=sha256_file(commitment_path),
        repo_root=repo_root,
        adjudication_root=adjudication_root,
        key_payload=_request_json("key", api_key),
        credits_payload=_request_json("credits", api_key),
        models_payload=_request_json("models", api_key),
    )
