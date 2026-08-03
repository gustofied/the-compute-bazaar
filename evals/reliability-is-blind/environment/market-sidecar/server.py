#!/usr/bin/env python3
"""Protected authoritative market service for the Harbor task.

Only collective outcomes and public stake state cross the broker boundary. The
seed and hidden supplier reliabilities remain here until Harbor finalizes the
ledger for the separate verifier.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import tempfile
import threading
from typing import Any

from market_engine import ENGINE_VERSION, UPSTREAM_REVISION, MarketConfig, MarketEngine


ARTIFACT_SCHEMA_VERSION = "reliability-is-blind.market-ledger.v1"
ARTIFACT_KIND = "authoritative_market_ledger"
ENGINE_PATH = Path(__file__).with_name("market_engine.py")
STATE_DIR = Path(os.environ.get("MARKET_STATE_DIR", "/var/lib/market"))
ARTIFACT_DIR = Path(os.environ.get("MARKET_ARTIFACT_DIR", "/market-artifacts"))
SNAPSHOT_PATH = ARTIFACT_DIR / "state.json"
SNAPSHOT_TOKEN_PATH = STATE_DIR / "snapshot-token"
MAX_REQUEST_BYTES = 16_384
MAX_AGENT_REQUESTS = 4_096
MAX_HISTORY_PAGE = 100
MAX_SELECTION_VALUES = 128


def _parse_port() -> int:
    raw = os.environ.get("MARKET_PORT", "8000")
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError("MARKET_PORT must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise RuntimeError("MARKET_PORT must be between 1 and 65535")
    return port


def _parse_seed() -> int:
    raw = os.environ.get("MARKET_SEED", "").strip()
    if not raw:
        return secrets.randbits(128)
    if not raw.isascii() or not raw.isdecimal():
        raise RuntimeError("MARKET_SEED must be an unsigned decimal integer")
    if len(raw) > 1 and raw.startswith("0"):
        raise RuntimeError("MARKET_SEED must use canonical decimal notation")
    seed = int(raw)
    if seed >= 2**256:
        raise RuntimeError("MARKET_SEED must fit within 256 bits")
    return seed


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise RuntimeError("market state contains a non-finite value")
    return value


def _complete_config(config: MarketConfig) -> dict[str, Any]:
    values = _jsonable(asdict(config))
    values.update(
        {
            "reward_amount": config.reward_amount,
            "minimum_stake": config.minimum_stake,
            "maximum_stake": config.maximum_stake,
            "ruin_threshold": config.ruin_threshold,
            "incomplete_reward": config.incomplete_reward,
        }
    )
    return values


def _write_text_atomic(path: Path, value: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    payload = (
        json.dumps(
            value,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    _write_text_atomic(path, payload)


def _post_state(observation: Any) -> dict[str, Any]:
    return {
        "completed_deals": observation.completed_deals,
        "invalid_actions": observation.invalid_actions,
        "terminal": observation.terminal,
        "terminal_reason": (
            observation.terminal_reason.value
            if observation.terminal_reason is not None
            else None
        ),
    }


class MarketRuntime:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.config = MarketConfig()
        self.seed = _parse_seed()
        self.engine = MarketEngine(self.config)
        self.engine.reset(self.seed)
        self.attempts: list[dict[str, Any]] = []
        self.request_counts: dict[str, Any] = {"total": 0, "by_action": {}}
        self.finalized = False
        self.engine_sha256 = hashlib.sha256(ENGINE_PATH.read_bytes()).hexdigest()

        SNAPSHOT_PATH.unlink(missing_ok=True)
        SNAPSHOT_TOKEN_PATH.unlink(missing_ok=True)
        _write_text_atomic(SNAPSHOT_TOKEN_PATH, secrets.token_urlsafe(48) + "\n")

    def _count(self, action: str) -> bool:
        if self.request_counts["total"] >= MAX_AGENT_REQUESTS:
            return False
        self.request_counts["total"] += 1
        by_action = self.request_counts["by_action"]
        by_action[action] = int(by_action.get(action, 0)) + 1
        return True

    def _summary(self) -> dict[str, Any]:
        observation = self.engine.observe()
        delivered = sum(deal.delivered for deal in observation.history)
        failed = observation.completed_deals - delivered
        failure_rate = (
            failed / observation.completed_deals if observation.completed_deals else 0.0
        )
        return {
            "completed_deals": observation.completed_deals,
            "horizon": observation.horizon,
            "deals_remaining": observation.deals_remaining,
            "delivered_deals": delivered,
            "failed_deals": failed,
            "delivery_rate": 1.0 - failure_rate if observation.completed_deals else 0.0,
            "failure_rate": failure_rate,
            "target_failure_rate": observation.target_failure_rate,
            "invalid_actions": observation.invalid_actions,
            "invalid_action_limit": observation.invalid_action_limit,
            "terminal": observation.terminal,
            "terminal_reason": (
                observation.terminal_reason.value
                if observation.terminal_reason is not None
                else None
            ),
        }

    def _public_state(self) -> dict[str, Any]:
        observation = self.engine.observe()
        return {
            "summary": self._summary(),
            "suppliers": _jsonable(observation.suppliers),
            "last_deal": (
                _jsonable(observation.history[-1]) if observation.history else None
            ),
            "reward_calibration": {
                "success": self.config.reward_amount,
                "failure": -self.config.slash_amount,
            },
        }

    def _snapshot_authenticated(self, provided: object) -> bool:
        if not isinstance(provided, str):
            return False
        try:
            expected = SNAPSHOT_TOKEN_PATH.read_text().strip()
        except OSError:
            return False
        return bool(expected) and hmac.compare_digest(provided, expected)

    def process(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        with self.lock:
            if action == "snapshot":
                return self._snapshot(request.get("snapshot_token"))

            if action == "ping":
                return {"ok": True, "status": "ready"}

            if self.finalized:
                return {"ok": False, "error": "market state is finalized"}
            if action not in {"status", "history", "select", "result"}:
                return {"ok": False, "error": f"unknown action: {action}"}
            if action == "select":
                requested = request.get("supplier_ids")
                if (
                    not isinstance(requested, list)
                    or len(requested) > MAX_SELECTION_VALUES
                ):
                    return {
                        "ok": False,
                        "error": "supplier_ids must be a bounded JSON list",
                    }
                if any(isinstance(value, (dict, list)) for value in requested):
                    return {
                        "ok": False,
                        "error": "supplier_ids cannot contain structured values",
                    }
                if any(
                    isinstance(value, float) and not math.isfinite(value)
                    for value in requested
                ):
                    return {
                        "ok": False,
                        "error": "supplier_ids cannot contain non-finite values",
                    }
                if self.engine.terminal:
                    return {
                        "ok": True,
                        "accepted": False,
                        "error": "rollout is already terminal",
                        "deal": None,
                        "broker_reward": None,
                        **self._public_state(),
                    }
            if not self._count(str(action)):
                return {"ok": False, "error": "market request limit exceeded"}

            if action == "status":
                return {"ok": True, **self._public_state()}
            if action == "history":
                return self._history(request)
            if action == "select":
                return self._select(request)
            return {
                "ok": True,
                "horizon": self.config.horizon,
                "result": _jsonable(self.engine.result()),
            }

    def _history(self, request: dict[str, Any]) -> dict[str, Any]:
        offset = request.get("offset", 0)
        limit = request.get("limit", 25)
        if type(offset) is not int or offset < 0:
            return {"ok": False, "error": "offset must be a non-negative integer"}
        if type(limit) is not int or not 1 <= limit <= MAX_HISTORY_PAGE:
            return {
                "ok": False,
                "error": f"limit must be between 1 and {MAX_HISTORY_PAGE}",
            }
        history = self.engine.observe().history
        return {
            "ok": True,
            "offset": offset,
            "limit": limit,
            "total": len(history),
            "deals": _jsonable(history[offset : offset + limit]),
        }

    def _select(self, request: dict[str, Any]) -> dict[str, Any]:
        requested = request.get("supplier_ids")
        assert isinstance(requested, list)

        step = self.engine.step(requested)
        event = {
            "attempt_id": len(self.attempts) + 1,
            "requested_supplier_ids": requested,
            "accepted": step.accepted,
            "error": step.error,
            "deal": _jsonable(step.deal),
            "broker_reward": step.broker_reward,
            "post_state": _post_state(step.observation),
        }
        self.attempts.append(event)
        return {
            "ok": True,
            "accepted": step.accepted,
            "error": step.error,
            "deal": _jsonable(step.deal),
            "broker_reward": step.broker_reward,
            **self._public_state(),
        }

    def _snapshot(self, provided_token: object) -> dict[str, Any]:
        if not self._snapshot_authenticated(provided_token):
            return {"ok": False, "error": "snapshot authentication failed"}
        if self.finalized or SNAPSHOT_PATH.exists():
            return {"ok": False, "error": "market state is already finalized"}

        observation = self.engine.observe()
        result = self.engine.result()
        artifact = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "artifact_kind": ARTIFACT_KIND,
            "engine": {
                "version": ENGINE_VERSION,
                "upstream_revision": UPSTREAM_REVISION,
                "sha256": self.engine_sha256,
            },
            "seed": str(self.seed),
            "config": _complete_config(self.config),
            "attempts": self.attempts,
            "final_observation": _jsonable(observation),
            "final_result": _jsonable(result),
            "request_counts": self.request_counts,
            "finalized": True,
            "snapshot": {
                "authentication": "sidecar-file-token-v1",
                "one_shot": True,
                "attempt_count": len(self.attempts),
                "completed_deals": result.completed_deals,
            },
        }
        self.finalized = True
        try:
            _write_json_atomic(SNAPSHOT_PATH, artifact)
        except Exception:
            self.finalized = False
            raise
        return {"ok": True, "snapshot": str(SNAPSHOT_PATH)}


RUNTIME = MarketRuntime()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value!r}")


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "reliability-is-blind-market/0.1.0"

    def _write(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write(200, {"ok": True})
        else:
            self._write(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1":
            self._write(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 1 or length > MAX_REQUEST_BYTES:
            self._write(413, {"ok": False, "error": "invalid request size"})
            return
        try:
            request = json.loads(
                self.rfile.read(length), parse_constant=_reject_json_constant
            )
            if not isinstance(request, dict):
                raise TypeError("request must be a JSON object")
            response = RUNTIME.process(request)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self._write(400, {"ok": False, "error": f"invalid request: {exc}"})
            return
        except Exception:
            self._write(500, {"ok": False, "error": "internal market error"})
            return
        self._write(200 if response.get("ok") else 400, response)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", _parse_port()), RequestHandler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
