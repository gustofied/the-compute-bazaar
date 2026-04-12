"""
Pulls ROI and NI actual demand from the EirGrid Smart Grid Dashboard API.
Saves a CSV with columns: DateTime_UTC, IE_MW, NI_MW

API: https://www.smartgriddashboard.com/DashboardService.svc/data
     ?area=demandactual&region={ROI|NI}
     &datefrom=01-Jan-2026+00%3A00&dateto=01-Feb-2026+21%3A59
"""
import argparse
from datetime import date, timedelta
from calendar import monthrange
import requests
import pandas as pd


BASE = "https://www.smartgriddashboard.com/DashboardService.svc/data"
FMT  = "%d-%b-%Y"   # e.g. 01-Jan-2026


def fetch_month(region: str, year: int, month: int) -> list[dict]:
    start = date(year, month, 1)
    last  = monthrange(year, month)[1]
    end   = date(year, month, last)
    params = {
        "area":     "demandactual",
        "region":   region,
        "datefrom": start.strftime(FMT) + "+00%3A00",
        "dateto":   end.strftime(FMT)   + "+21%3A59",
    }
    url = BASE + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json().get("Rows", [])


def fetch_range(region: str, start: date, end: date) -> pd.DataFrame:
    rows = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        print(f"  {region} {y}-{m:02d} ... ", end="", flush=True)
        chunk = fetch_month(region, y, m)
        rows.extend(chunk)
        print(f"{len(chunk)} rows")
        m += 1
        if m > 12:
            m, y = 1, y + 1

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

    print("Fetching ROI demand...")
    roi = fetch_range("ROI", start, end)
    print("Fetching NI demand...")
    ni  = fetch_range("NI",  start, end)

    df = roi.join(ni, how="outer").rename(columns={"ROI": "IE_MW", "NI": "NI_MW"})
    df.to_csv(args.out)
    print(f"\nSaved {len(df)} rows to {args.out}")


if __name__ == "__main__":
    main()
