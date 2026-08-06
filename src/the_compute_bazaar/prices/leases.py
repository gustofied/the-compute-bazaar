"""Local and S3 leases for short publication transactions."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from .storage import _s3_client


class LeaseBusyError(RuntimeError):
    """Raised when another process owns a mutable dataset's publication lease."""


@contextmanager
def exclusive_lease(uri: str, *, ttl_seconds: int = 1800) -> Iterator[None]:
    """Serialize a short read/merge/publish transaction locally or in S3."""
    if ttl_seconds < 60:
        raise ValueError("Lease TTL must be at least 60 seconds")
    if uri.startswith("s3://"):
        with _s3_exclusive_lease(uri, ttl_seconds=ttl_seconds):
            yield
        return

    import fcntl

    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LeaseBusyError(f"Publication lease is already held: {uri}") from exc
        acquired = True
        _write_local_lease(descriptor, state="active")
        yield
    finally:
        try:
            if acquired:
                _write_local_lease(descriptor, state="released")
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


@contextmanager
def _s3_exclusive_lease(uri: str, *, ttl_seconds: int) -> Iterator[None]:
    from botocore.exceptions import ClientError

    parsed = urlparse(uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    client = _s3_client()
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    active_payload = _lease_payload(
        token=token,
        state="active",
        acquired_at=now,
        expires_at=expires_at,
    )

    etag: str
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {
            "NoSuchKey",
            "NoSuchObject",
            "404",
        }:
            raise
        try:
            response = client.put_object(
                Bucket=bucket,
                Key=key,
                Body=active_payload,
                ContentType="application/json",
                IfNoneMatch="*",
            )
        except ClientError as put_exc:
            if (
                put_exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                == 412
            ):
                raise LeaseBusyError(
                    f"Publication lease was acquired concurrently: {uri}"
                ) from put_exc
            raise
        etag = str(response["ETag"])
    else:
        existing_etag = str(response["ETag"])
        existing = json.loads(response["Body"].read().decode("utf-8"))
        existing_expiry = datetime.fromisoformat(str(existing["expires_at"]))
        if existing_expiry > now:
            raise LeaseBusyError(
                f"Publication lease is held until {existing_expiry.isoformat()}: {uri}"
            )
        try:
            response = client.put_object(
                Bucket=bucket,
                Key=key,
                Body=active_payload,
                ContentType="application/json",
                IfMatch=existing_etag,
            )
        except ClientError as put_exc:
            if (
                put_exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                == 412
            ):
                raise LeaseBusyError(
                    f"Publication lease was renewed concurrently: {uri}"
                ) from put_exc
            raise
        etag = str(response["ETag"])

    try:
        yield
    finally:
        released_at = datetime.now(timezone.utc)
        released_payload = _lease_payload(
            token=token,
            state="released",
            acquired_at=now,
            expires_at=released_at,
        )
        try:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=released_payload,
                ContentType="application/json",
                IfMatch=etag,
            )
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise


def _lease_payload(
    *,
    token: str,
    state: str,
    acquired_at: datetime,
    expires_at: datetime,
) -> bytes:
    return json.dumps(
        {
            "token": token,
            "state": state,
            "acquired_at": acquired_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        },
        sort_keys=True,
    ).encode("utf-8")


def _write_local_lease(descriptor: int, *, state: str) -> None:
    now = datetime.now(timezone.utc)
    payload = _lease_payload(
        token=str(os.getpid()),
        state=state,
        acquired_at=now,
        expires_at=now,
    )
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    os.write(descriptor, payload)
    os.fsync(descriptor)
