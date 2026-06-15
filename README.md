# The Compute Bazaar

Artefacts from tinkering with compute markets.

## Setup

This is a `uv` project. Install the locked environment with:

```sh
uv sync
```

Run scripts through the project entry points:

```sh
uv run ireland-compute-map
uv run ie-dc-share
uv run download-eirgrid --start 2026-01-01 --end 2026-01-31 --out eirgrid_demand.csv
uv run ie-dc-consumption --file eirgrid_demand.csv --plot ireland_consumption.png
uv run ie-flow-map --file /path/to/System-Data-Qtr-Hourly.xlsx --out ie_flow_map.png
```

Scripts that consume EirGrid Excel exports require `--file /path/to/export.xlsx`.
