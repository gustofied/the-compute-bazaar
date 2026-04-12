"""
Downloads EirGrid quarter-hourly system data Excel files.
Files are published at:
  https://www.eirgridgroup.com/site-files/library/EirGrid/System-Data-Qtr-Hourly-YYYY-YYYY.xlsx
"""
import sys
import urllib.request

YEAR = 2026
URL = f"https://www.eirgridgroup.com/site-files/library/EirGrid/System-Data-Qtr-Hourly-{YEAR}-{YEAR+1}.xlsx"
OUT = f"eirgrid_qtr_{YEAR}.xlsx"

print(f"Fetching {URL}")
try:
    urllib.request.urlretrieve(URL, OUT)
    print(f"Saved to {OUT}")
except Exception as e:
    print(f"Failed: {e}")
    print("Download manually from https://www.eirgridgroup.com and pass with --file")
    sys.exit(1)
