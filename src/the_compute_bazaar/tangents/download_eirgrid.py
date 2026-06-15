"""
Pulls ROI and NI actual demand from the EirGrid Smart Grid Dashboard API.
Saves a CSV with columns: DateTime_UTC, IE_MW, NI_MW

API: https://www.smartgriddashboard.com/DashboardService.svc/data
     ?area=demandactual&region={ROI|NI}
     &datefrom=01-Jan-2026+00%3A00&dateto=01-Feb-2026+21%3A59
"""
import argparse
import time
from datetime import date
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd


BASE = "https://www.smartgriddashboard.com/DashboardService.svc/data"
FMT  = "%d-%b-%Y"   # e.g. 01-Jan-2026

CHUNK_DAYS = 7


def make_session() -> requests.Session:
    retry = Retry(
        total=8,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.smartgriddashboard.com/",
    })
    return s


def init_session(s: requests.Session):
    """Hit the dashboard homepage to establish cookies before API calls."""
    s.get("https://www.smartgriddashboard.com/", timeout=30)


def fetch_window(
    session: requests.Session,
    region: str,
    start: date,
    end: date,
    retries: int = 5,
) -> list[dict]:
    params = {
        "area":     "demandactual",
        "region":   region,
        "datefrom": start.strftime(FMT) + "+00%3A00",
        "dateto":   end.strftime(FMT)   + "+23%3A59",
    }
    url = BASE + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    for attempt in range(retries):
        r = session.get(url, timeout=60)
        if r.status_code == 403:
            wait = 5 * (attempt + 1)
            print(f"403 rate-limited, re-init session and wait {wait}s")
            time.sleep(wait)
            init_session(session)
            continue
        r.raise_for_status()
        return r.json().get("Rows", [])
    r.raise_for_status()


def fetch_range(
    session: requests.Session,
    region: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    from datetime import timedelta
    rows = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), end)
        print(f"  {region} {cursor} -> {chunk_end} ... ", end="", flush=True)
        chunk = fetch_window(session, region, cursor, chunk_end)
        rows.extend(chunk)
        print(f"{len(chunk)} rows")
        time.sleep(2)
        cursor = chunk_end + timedelta(days=1)

    df = pd.DataFrame(rows)
    # typical columns: EffectiveTime, Value, (FieldName / Region)
    df["DateTime_UTC"] = pd.to_datetime(df["EffectiveTime"], dayfirst=True, utc=True)
    df = df.set_index("DateTime_UTC").sort_index()
    return df[["Value"]].rename(columns={"Value": region})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-01-01", help="YYYY-MM-DD")
    parser.add_argument("--end",   default="2026-12-31", help="YYYY-MM-DD")
    parser.add_argument("--out",   default="eirgrid_demand.csv")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    session = make_session()
    init_session(session)

    print("Fetching ROI demand...")
    roi = fetch_range(session, "ROI", start, end)
    print("Fetching NI demand...")
    ni  = fetch_range(session, "NI",  start, end)

    df = roi.join(ni, how="outer").rename(columns={"ROI": "IE_MW", "NI": "NI_MW"})
    df.to_csv(args.out)
    print(f"\nSaved {len(df)} rows to {args.out}")


if __name__ == "__main__":
    main()
