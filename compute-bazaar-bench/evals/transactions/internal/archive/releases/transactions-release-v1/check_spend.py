from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[4]
PROTOCOL_PATH = ROOT / "transactions-release-v1.commitment.json"
BASELINE_GATE_PATH = ROOT / "spend-gate-002.json"
COST_ENVELOPE_PATH = ROOT / "cost-envelope-001.json"
OPENROUTER_API = "https://openrouter.ai/api/v1"


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_secret(name: str) -> str | None:
    if value := os.environ.get(name):
        return value
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


def request_json(path: str, api_key: str) -> dict[str, Any]:
    request = Request(
        f"{OPENROUTER_API}/{path}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise RuntimeError(f"OpenRouter /{path} failed: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"OpenRouter /{path} returned an invalid response")
    return payload


def _token_cost(tokens: dict[str, Any], pricing: dict[str, Any]) -> float:
    input_tokens = float(tokens["input"])
    cache_tokens = float(tokens["cache"])
    output_tokens = float(tokens["output"])
    if cache_tokens > input_tokens:
        raise RuntimeError("cache token reference exceeds input tokens")
    return (
        (input_tokens - cache_tokens) * float(pricing["prompt"])
        + cache_tokens * float(pricing["input_cache_read"])
        + output_tokens * float(pricing["completion"])
    )


def _snapshot_remaining(snapshot: dict[str, Any]) -> float:
    account = snapshot.get("account")
    if not isinstance(account, dict) or account.get("account_remaining_usd") is None:
        raise RuntimeError("live gate snapshot is missing account remaining balance")
    return float(account["account_remaining_usd"])


def evaluate_gate(
    key_payload: dict[str, Any],
    credits_payload: dict[str, Any],
    models_payload: dict[str, Any],
    *,
    stage: str = "entry",
    entry_snapshot: dict[str, Any] | None = None,
    post_oracle_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline = json.loads(BASELINE_GATE_PATH.read_text())
    protocol_hash = sha256_file(PROTOCOL_PATH)
    if baseline["protocol_sha256"] != protocol_hash:
        raise RuntimeError("spend gate does not bind the frozen release protocol")
    expected_envelope_hash = baseline["estimate"]["sources"]["cost_envelope_sha256"]
    if sha256_file(COST_ENVELOPE_PATH) != expected_envelope_hash:
        raise RuntimeError("spend gate does not bind the cost envelope")

    key = key_payload.get("data")
    credits = credits_payload.get("data")
    models = models_payload.get("data")
    if not isinstance(key, dict) or not isinstance(credits, dict):
        raise RuntimeError("OpenRouter account response is malformed")
    if not isinstance(models, list):
        raise RuntimeError("OpenRouter model response is malformed")

    catalog = {item.get("id"): item for item in models if isinstance(item, dict)}
    pricing_matches = True
    live_pricing: dict[str, dict[str, Any]] = {}
    for model_id, expected in baseline["catalog_pricing_usd_per_token"].items():
        current = catalog.get(model_id)
        if not isinstance(current, dict):
            pricing_matches = False
            continue
        if current.get("canonical_slug") != expected["canonical_slug"]:
            pricing_matches = False
        current_pricing = current.get("pricing") or {}
        live_pricing[model_id] = current_pricing
        for field in ("prompt", "completion", "input_cache_read"):
            if str(current_pricing.get(field)) != expected[field]:
                pricing_matches = False

    frozen_estimate = baseline["estimate"]
    reference = frozen_estimate["sources"]
    mistral_pricing = live_pricing.get("mistralai/mistral-small-2603")
    if not isinstance(mistral_pricing, dict):
        official_agent = float(frozen_estimate["official_agent_usd"])
        route_preflight = float(frozen_estimate["route_preflight_agent_usd"])
    else:
        official_agent = _token_cost(
            reference["mistral_official_reference_tokens"], mistral_pricing
        )
        route_preflight = _token_cost(
            reference["mistral_route_preflight_reference_tokens"], mistral_pricing
        )
    judge_mean = float(reference["judge_mean_batch_usd"])
    oracle_expected = float(frozen_estimate["oracle_judge_usd"])
    official_judge = judge_mean * int(reference["official_judge_batches"])
    official_expected = official_judge + official_agent
    complete_expected = oracle_expected + route_preflight + official_expected
    record_envelope = float(frozen_estimate["official_record_cost_envelope_usd"])

    account_remaining = float(credits["total_credits"]) - float(credits["total_usage"])
    key_remaining_raw = key.get("limit_remaining")
    key_remaining = float(key_remaining_raw) if key_remaining_raw is not None else None
    observed_oracle: float | None = None
    observed_route: float | None = None
    if stage == "entry":
        required = (
            complete_expected
            * (1 + float(frozen_estimate["entry_contingency_fraction"]))
            + record_envelope
        )
        rule = (
            "Complete known spend plus 25 percent and the empirical record "
            "envelope before the first paid call."
        )
    elif stage == "post_oracle":
        if entry_snapshot is None:
            raise RuntimeError("post_oracle requires the entry snapshot")
        observed_oracle = max(
            _snapshot_remaining(entry_snapshot) - account_remaining,
            0.0,
        )
        required = (
            route_preflight
            + official_expected
            * (1 + float(frozen_estimate["official_contingency_fraction"]))
            + record_envelope
        )
        rule = (
            "Enough balance for route preflight, the complete official job plus "
            "25 percent, and the empirical record envelope."
        )
    elif stage == "official":
        if entry_snapshot is None or post_oracle_snapshot is None:
            raise RuntimeError("official requires the entry and post-Oracle snapshots")
        entry_remaining = _snapshot_remaining(entry_snapshot)
        post_oracle_remaining = _snapshot_remaining(post_oracle_snapshot)
        observed_oracle = max(entry_remaining - post_oracle_remaining, 0.0)
        observed_route = max(post_oracle_remaining - account_remaining, 0.0)
        required = (
            official_expected
            * (1 + float(frozen_estimate["official_contingency_fraction"]))
            + record_envelope
        )
        rule = (
            "Complete official estimate plus 25 percent and the empirical record "
            "envelope."
        )
    else:
        raise RuntimeError(f"unknown gate stage: {stage}")

    account_ok = account_remaining >= required
    key_ok = key_remaining is None or key_remaining >= required
    passed = account_ok and key_ok and pricing_matches
    return {
        "schema_version": "compute-bazaar-bench.transactions.live-spend-gate.v3",
        "stage": stage,
        "status": "passed" if passed else "blocked",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": protocol_hash,
        "account": {
            "key_limit_usd": key.get("limit"),
            "key_limit_remaining_usd": key_remaining,
            "key_usage_usd": key.get("usage"),
            "total_credits_usd": float(credits["total_credits"]),
            "total_usage_usd": float(credits["total_usage"]),
            "account_remaining_usd": account_remaining,
        },
        "estimate": {
            "oracle_expected_usd": oracle_expected,
            "route_preflight_expected_usd": route_preflight,
            "official_judge_expected_usd": official_judge,
            "official_agent_expected_usd": official_agent,
            "official_expected_usd": official_expected,
            "complete_expected_usd": complete_expected,
            "record_cost_envelope_usd": record_envelope,
            "observed_oracle_stage_usd": observed_oracle,
            "observed_route_preflight_usd": observed_route,
            "required_balance_usd": required,
            "headroom_usd": account_remaining - required,
            "modal_usd": None,
        },
        "checks": {
            "pricing_matches_frozen_gate": pricing_matches,
            "account_covers_stage": account_ok,
            "key_limit_covers_stage": key_ok,
        },
        "rule": rule,
    }


def _load_snapshot(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text())
    if payload.get("protocol_sha256") != sha256_file(PROTOCOL_PATH):
        raise RuntimeError(f"snapshot does not bind the current protocol: {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", choices=("entry", "post_oracle", "official"), required=True
    )
    parser.add_argument("--entry-snapshot", type=Path)
    parser.add_argument("--post-oracle-snapshot", type=Path)
    parser.add_argument("--write", type=Path)
    args = parser.parse_args()

    api_key = load_secret("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is missing")
    result = evaluate_gate(
        request_json("key", api_key),
        request_json("credits", api_key),
        request_json("models", api_key),
        stage=args.stage,
        entry_snapshot=_load_snapshot(args.entry_snapshot),
        post_oracle_snapshot=_load_snapshot(args.post_oracle_snapshot),
    )
    rendered = json.dumps(result, indent=2) + "\n"
    if args.write is not None:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        with args.write.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered, end="")
    if result["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
