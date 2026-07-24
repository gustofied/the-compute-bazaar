"""European Central Bank reference-rate helpers."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

import requests


DEFAULT_ECB_EUR_USD_URL = (
    "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
)


@dataclass(frozen=True)
class EcbRateFetch:
    raw_payload: str
    rate: float
    observed_date: str


def fetch_latest_eur_usd_rate(
    session: requests.Session,
    *,
    fx_url: str = DEFAULT_ECB_EUR_USD_URL,
) -> EcbRateFetch:
    response = session.get(
        fx_url,
        params={"lastNObservations": 1, "format": "csvdata"},
        headers={
            "Accept": "text/csv",
            "User-Agent": "the-compute-bazaar/0.1",
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.text
    rows = list(csv.DictReader(io.StringIO(payload)))
    if not rows:
        raise ValueError("ECB EUR/USD response contained no observations")
    row = rows[-1]
    observed_date = str(row.get("TIME_PERIOD") or "").strip()
    try:
        rate = float(row.get("OBS_VALUE") or "")
    except (TypeError, ValueError) as exc:
        raise ValueError("ECB EUR/USD response was missing a valid latest rate") from exc
    if rate <= 0 or not observed_date:
        raise ValueError("ECB EUR/USD response was missing a valid latest rate")
    return EcbRateFetch(
        raw_payload=payload,
        rate=rate,
        observed_date=observed_date,
    )
