"""Event helpers for the GPU market log."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from .schemas import EventEnvelope, SCHEMA_VERSION, to_jsonable, utc_now


def stable_json_dumps(value: Any) -> str:
    return json.dumps(to_jsonable(value), sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(stable_json_dumps(value))


def new_run_id(prefix: str) -> str:
    return f"{prefix}-{utc_now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


def make_event(
    *,
    event_type: str,
    provider: str,
    payload: dict[str, Any],
    run_id: str,
    trace_id: str,
    raw_ref: str | None = None,
    event_time: datetime | None = None,
) -> EventEnvelope:
    payload_hash = sha256_json(payload)
    event_id = sha256_text(
        stable_json_dumps(
            {
                "event_type": event_type,
                "provider": provider,
                "run_id": run_id,
                "raw_ref": raw_ref,
                "payload_hash": payload_hash,
            }
        )
    )
    now = utc_now()
    return EventEnvelope(
        event_id=event_id,
        event_type=event_type,
        schema_version=SCHEMA_VERSION,
        provider=provider,
        event_time=event_time or now,
        ingest_time=now,
        run_id=run_id,
        trace_id=trace_id,
        raw_ref=raw_ref,
        payload_hash=payload_hash,
        payload=payload,
    )

