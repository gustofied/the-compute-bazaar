"""Shared retry policy for read-only provider API clients."""

from __future__ import annotations

from collections.abc import Collection

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def retrying_session(
    *,
    allowed_methods: Collection[str] = ("GET",),
    backoff_factor: float = 1.0,
) -> requests.Session:
    retry = Retry(
        total=5,
        connect=3,
        read=3,
        status=5,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(method.upper() for method in allowed_methods),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
