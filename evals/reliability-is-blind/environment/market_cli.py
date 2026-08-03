#!/usr/bin/env python3
"""Public command-line interface for the Reliability Is Blind market."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


BASE_URL = os.environ.get("MARKET_URL", "http://market:8000").rstrip("/")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def request(payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    http_request = urllib.request.Request(
        f"{BASE_URL}/v1",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=10) as response:
            encoded = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        encoded = exc.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise SystemExit(f"market service unavailable: {exc}") from exc

    if len(encoded) > MAX_RESPONSE_BYTES:
        raise SystemExit("market response exceeded the size limit")
    try:
        response = json.loads(encoded)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit("market returned an invalid response") from exc
    if not isinstance(response, dict) or not response.get("ok"):
        error = (
            response.get("error", "market request failed")
            if isinstance(response, dict)
            else "market request failed"
        )
        raise SystemExit(error)
    return response


def _print_json(response: dict[str, Any]) -> None:
    print(json.dumps(response, indent=2, sort_keys=True, allow_nan=False))


def _print_summary(summary: dict[str, Any]) -> None:
    print(
        "Book: "
        f"{summary['completed_deals']}/{summary['horizon']} deals, "
        f"{summary['delivered_deals']} delivered, "
        f"{summary['failed_deals']} failed, "
        f"failure rate {summary['failure_rate']:.2%} "
        f"(target <= {summary['target_failure_rate']:.2%})"
    )
    print(
        f"Invalid actions: {summary['invalid_actions']}/"
        f"{summary['invalid_action_limit']} | "
        f"Terminal: {str(summary['terminal']).lower()}"
        + (f" ({summary['terminal_reason']})" if summary.get("terminal_reason") else "")
    )


def _print_suppliers(suppliers: list[dict[str, Any]]) -> None:
    rendered = "  ".join(
        f"{supplier['supplier_id']}:{supplier['stake']:.6f}" for supplier in suppliers
    )
    print(f"Eligible suppliers (ID:stake): {rendered}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="market",
        description="Play one hidden-reliability compute brokerage market.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("ping", help=argparse.SUPPRESS)

    status = subparsers.add_parser("status", help="Show current public market state")
    status.add_argument("--json", action="store_true", dest="as_json")

    history = subparsers.add_parser("history", help="Show the public deal ledger")
    history.add_argument("--offset", type=int, default=0)
    history.add_argument("--limit", type=int, default=25)
    history.add_argument("--json", action="store_true", dest="as_json")

    select = subparsers.add_parser(
        "select", help="Place supplier IDs into the next deal"
    )
    select.add_argument("supplier_ids", type=int, nargs="*")
    select.add_argument("--json", action="store_true", dest="as_json")

    result = subparsers.add_parser("result", help="Show the current book result")
    result.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args()

    if args.command == "ping":
        request({"action": "ping"})
        print("ready")
        return

    if args.command == "status":
        response = request({"action": "status"})
        if args.as_json:
            _print_json(response)
        else:
            _print_summary(response["summary"])
            _print_suppliers(response["suppliers"])
            if response.get("last_deal") is not None:
                deal = response["last_deal"]
                outcome = "delivered" if deal["delivered"] else "failed"
                print(
                    f"Last deal {deal['deal_id']}: "
                    f"{' '.join(str(value) for value in deal['supplier_ids'])} -> "
                    f"{outcome}"
                )
        return

    if args.command == "history":
        response = request(
            {"action": "history", "offset": args.offset, "limit": args.limit}
        )
        if args.as_json:
            _print_json(response)
        elif not response["deals"]:
            print("No deals in this page.")
        else:
            print(
                f"Deals {response['offset'] + 1}-"
                f"{response['offset'] + len(response['deals'])} "
                f"of {response['total']}"
            )
            for deal in response["deals"]:
                outcome = "delivered" if deal["delivered"] else "failed"
                suppliers = " ".join(str(value) for value in deal["supplier_ids"])
                print(f"  {deal['deal_id']}: {suppliers} -> {outcome}")
        return

    if args.command == "select":
        response = request({"action": "select", "supplier_ids": args.supplier_ids})
        if args.as_json:
            _print_json(response)
        elif not response["accepted"]:
            print(f"Selection rejected: {response['error']}")
            _print_summary(response["summary"])
        else:
            deal = response["deal"]
            outcome = "DELIVERED" if deal["delivered"] else "FAILED"
            print(
                f"Deal {deal['deal_id']} {outcome} | "
                f"broker reward {response['broker_reward']:+.6f}"
            )
            _print_summary(response["summary"])
            _print_suppliers(response["suppliers"])
        return

    if args.command == "result":
        response = request({"action": "result"})
        if args.as_json:
            _print_json(response)
        else:
            result_value = response["result"]
            print(
                f"Completion: {result_value['completion']} | "
                f"Reward: {result_value['primary_reward']:+.6f} | "
                f"Deals: {result_value['completed_deals']}/"
                f"{response['horizon']}"
            )
            print(
                f"Delivery rate: {result_value['delivery_rate']:.2%} | "
                f"Failure rate: {result_value['failure_rate']:.2%} | "
                "Reliability target met: "
                f"{str(result_value['target_met']).lower()}"
            )
            print(
                f"Eligible suppliers: {result_value['eligible_supplier_count']} | "
                f"Reason: {result_value['terminal_reason']}"
            )
        return

    parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(1)
