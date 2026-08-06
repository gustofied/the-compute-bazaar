<p align="center">
  <img src="assets/compute-bazaar-wordmark.png" alt="The Compute Bazaar" width="440">
</p>

## Setup

Install the project, activate its environment, and query the bundled public market
snapshot. No cloud credentials are needed.

```bash
uv sync
source .venv/bin/activate
compute-bazaar price-index
```

`compute-bazaar` prints tables in a terminal. Use `--format json` for scripts and
agents.

## Query

```bash
compute-bazaar availability --gpu-model H100 --history --limit 20
compute-bazaar sql "select provider, gpu_model, price_usd_gpu_hr from silver.gpu_offers order by price_usd_gpu_hr limit 20"
```

The main tables are `silver.gpu_offers`, `gold.fact_gpu_price_index`, and
`gold.fact_gpu_availability`. Inspect the catalog with `compute-bazaar tables`
and `compute-bazaar describe gold.fact_gpu_price_index`.

Use another local or S3-backed lake with `--lake-root PATH`, or set
`COMPUTE_BAZAAR_LAKE_ROOT`.

Run the tests:

```bash
uv run python -m unittest discover -s tests -v
```
