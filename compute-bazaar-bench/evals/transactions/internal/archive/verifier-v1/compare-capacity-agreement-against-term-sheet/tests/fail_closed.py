#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

def main() -> int:
    tests = Path(__file__).resolve().parent
    logs = Path(os.environ.get("HARBOR_VERIFIER_LOG_DIR", "/logs/verifier"))
    dimensions = sorted(
        item.name
        for item in tests.iterdir()
        if item.is_dir() and not item.name.startswith((".", "__"))
    )
    rewards = {name: 0.0 for name in dimensions}
    rewards.update({"reward": 0.0, "all_pass": 0.0})
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "reward.json").write_text(json.dumps(rewards, indent=2) + "\n")
    (logs / "reward-details.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "failure_kind": "invalid_deliverable",
                "message": (
                    sys.argv[1]
                    if len(sys.argv) > 1
                    else "output integrity check failed"
                ),
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
