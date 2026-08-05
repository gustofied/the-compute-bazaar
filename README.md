<p align="center">
  <img src="docs/assets/compute-bazaar-wordmark.png" alt="The Compute Bazaar" width="600">
</p>

# The Compute Bazaar

The Compute Bazaar is an open compute-market data project. It collects public
GPU, VM, and sandbox observations, preserves source evidence, normalizes unlike
offers, and makes the resulting market data available for analysis.

The public website presents selected market views. The repository is becoming
the place where developers can fetch the underlying public data, query it with
DataFusion, and run their own local market-data pipeline.

## Current State

The operating pipeline is live and publishes public-safe data at
[bazaar.adamsioud.com](https://bazaar.adamsioud.com). The Python project already
contains provider ingestion, bronze/silver/gold processing, DataFusion queries,
scheduled Windmill jobs, AutoMQ event publishing, S3 storage, public JSON
exports, and local inspection tools.

The public clone-and-run interface is still being consolidated. Today, the
existing commands are available through `gpu-prices`; the intended public entry
point will be a unified `compute-bazaar` CLI. Existing commands will remain as
compatibility aliases while that interface is introduced.

## Public Data

Current publication-safe examples:

```text
https://bazaar.adamsioud.com/gpu-benchmark/h100.json
https://bazaar.adamsioud.com/gpu-benchmark/h200.json
https://bazaar.adamsioud.com/sandbox/rates.json
```

These are generated views of selected gold data. Private provider evidence,
internal lake objects, credentials, and infrastructure state are not exposed.

## Development

This is a Python 3.13 `uv` project.

```sh
uv sync
uv run python -m unittest discover -v
```

The complete Stage 1 operational README has been retained at
[docs/archive/README-stage1-2026-08-05.md](docs/archive/README-stage1-2026-08-05.md)
while the public project interface is rebuilt deliberately.

## Direction

The public workflow we are working toward is:

```text
clone the repository
  -> fetch a public market snapshot
  -> inspect its provenance and schemas
  -> query Parquet with DataFusion
  -> run saved or exploratory analysis
  -> optionally operate an independent provider-ingestion pipeline
```

Documentation will return to this README section by section as each interface
is reviewed and made reproducible for a new contributor.
