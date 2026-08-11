#!/bin/sh
set -eu

python3 - <<'PY'
import json
import subprocess


def market_json(*arguments: str) -> dict:
    output = subprocess.check_output(["market", *arguments, "--json"], text=True)
    return json.loads(output)


while True:
    status = market_json("status")
    summary = status["summary"]
    if summary["terminal"]:
        break
    suppliers = sorted(
        status["suppliers"],
        key=lambda supplier: (-supplier["stake"], supplier["supplier_id"]),
    )
    selection = [str(supplier["supplier_id"]) for supplier in suppliers[:4]]
    market_json("select", *selection)

subprocess.run(["market", "result"], check=True)
PY
