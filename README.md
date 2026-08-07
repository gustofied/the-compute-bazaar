<p align="center">
  <img src="assets/compute-bazaar-wordmark.png" alt="The Compute Bazaar" width="440">
</p>

## Setup

Install the project and download the public market lake. No cloud credentials
are needed.

```bash
uv sync
source .venv/bin/activate
compute-bazaar data sync
compute-bazaar data status
compute-bazaar price-index
```

`compute-bazaar` prints tables in a terminal. Use
`compute-bazaar --format json COMMAND` for programs.

The CLI verifies and caches the latest sanitized Silver tables and complete
published Gold history for local DataFusion queries. Later runs use that copy.
Set `COMPUTE_BAZAAR_DATA_HOME` to choose its cache location.

## Query

```bash
compute-bazaar availability --gpu-model H100 --history --limit 20
compute-bazaar sql "select provider, gpu_model, price_usd_gpu_hr from silver.gpu_offers order by price_usd_gpu_hr limit 20"
```

The main tables are `silver.gpu_offers`, `gold.fact_gpu_price_index`, and
`gold.fact_gpu_availability`. Inspect the catalog with `compute-bazaar tables`
and `compute-bazaar describe gold.fact_gpu_price_index`.

Use another local or S3-backed lake with `--lake-root PATH`, or set
`COMPUTE_BAZAAR_LAKE_ROOT`. Direct S3 access requires `uv sync --extra s3`;
the public sync above does not need AWS credentials.

## API

```bash
uv sync --extra api
compute-bazaar api
```

FastAPI is the optional typed interface. Public typed operations are supported;
scratch SQL stays operator-only unless explicitly enabled and authenticated.
