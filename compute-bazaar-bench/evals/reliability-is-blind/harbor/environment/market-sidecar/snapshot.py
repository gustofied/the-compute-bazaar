#!/usr/bin/env python3
"""Authenticated Harbor collect hook for the authoritative market ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.request


STATE_DIR = Path(os.environ.get("MARKET_STATE_DIR", "/var/lib/market"))
SNAPSHOT_TOKEN_PATH = STATE_DIR / "snapshot-token"
MARKET_URL = os.environ.get("MARKET_URL", "http://localhost:8000").rstrip("/")


def main() -> None:
    token = SNAPSHOT_TOKEN_PATH.read_text().strip()
    if not token:
        raise SystemExit("snapshot token is missing")
    body = json.dumps(
        {"action": "snapshot", "snapshot_token": token},
        separators=(",", ":"),
    ).encode()
    request = urllib.request.Request(
        f"{MARKET_URL}/v1",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read(65_536))
    if not isinstance(payload, dict) or not payload.get("ok"):
        error = (
            payload.get("error", "snapshot failed")
            if isinstance(payload, dict)
            else "snapshot failed"
        )
        raise SystemExit(error)
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
