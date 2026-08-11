#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{path.name} must contain a non-empty object")
    return value


def criterion_errors(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        error = value.get("error")
        if error:
            errors.append(f"{path}: {error}")
        for key, child in value.items():
            errors.extend(criterion_errors(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(criterion_errors(child, f"{path}[{index}]"))
    return errors


def reject(reward_path: Path, message: str) -> int:
    reward_path.unlink(missing_ok=True)
    print(message, file=sys.stderr)
    return 3


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_rewardkit.py LOGS_DIR", file=sys.stderr)
        return 2

    logs = Path(sys.argv[1])
    reward_path = logs / "reward.json"
    try:
        reward = load_object(reward_path)
        details = load_object(logs / "reward-details.json")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return reject(reward_path, f"RewardKit output error: {exc}")

    missing = {"reward", "all_pass"} - reward.keys()
    if missing:
        return reject(
            reward_path,
            f"RewardKit output error: missing reward keys: {', '.join(sorted(missing))}",
        )

    errors = criterion_errors(details)
    if errors:
        return reject(
            reward_path,
            "RewardKit judge error: " + "; ".join(errors),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
