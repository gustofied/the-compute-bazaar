<p align="center">
  <img src="assets/compute-bazaar-wordmark.png" alt="The Compute Bazaar" width="440">
</p>

My vision is for The Compute Bazaar to become the ultimate tool for analysing
compute markets, built as much for humans as for machine-to-machine work.

## Architecture

I use Windmill to orchestrate the hourly data pipeline. It runs ingestion every
hour and publishes the live data through AutoMQ, a Kafka-compatible event
stream. I use S3 for storage: a Bronze layer for raw data, a Silver layer for
normalized data ready for analysis, and Gold models for things such as GPU price
indexes and availability.

This data can be queried with DataFusion, an SQL query engine built on Apache
Arrow. Perspective also accepts Arrow data, so I am currently exploring it to
visualize the query results. All of this can be used through the CLI and
Terminal.

The idea behind the lake being object storage is that agents can use SQL for
analysis or inspect the underlying files directly, such as contracts, deals, or
whatever else needs source evidence. This matters because compute markets are
not just quantitative, but qualitative too.

## Setup

Install the project and sync the hourly updated public market lake.

```bash
git clone https://github.com/gustofied/the-compute-bazaar.git
cd the-compute-bazaar
uv sync
source .venv/bin/activate
compute-bazaar data sync
compute-bazaar data status
compute-bazaar price-index
```

`compute-bazaar` prints tables by default. Use
`compute-bazaar --format json COMMAND` for machine-readable output.

## Query

```bash
compute-bazaar availability --gpu-model H100 --history --limit 20
compute-bazaar sql "select provider, gpu_model, price_usd_gpu_hr from silver.gpu_offers order by price_usd_gpu_hr limit 20"
```

The lake contains normalized offers, GPU price indexes, and availability
history. Browse it with `compute-bazaar tables` and inspect any table with
`compute-bazaar describe TABLE`.

## Analyses

Reusable read-only SQL models live in `analyses/models`; Perspective blueprints
in `analyses/blueprints` reference those models.

```bash
compute-bazaar model list
compute-bazaar model run h200-under-4
compute-bazaar blueprint open h200-under-4
```

Save a model from a SQL file with `compute-bazaar model save ID --file query.sql`.
The Terminal Save action writes both the model and its current blueprint.

Use another local or S3-backed lake with `--lake-root PATH`, or set
`COMPUTE_BAZAAR_LAKE_ROOT`. Direct S3 access requires `uv sync --extra s3`;
the public sync above does not need AWS credentials.

## API

```bash
uv sync --extra api
compute-bazaar api
```

FastAPI exposes optional typed reads. Scratch SQL remains local and
operator-only.

## Terminal

```bash
uv sync --extra api
pnpm --dir terminal install
compute-bazaar terminal
compute-bazaar terminal --stop
compute-bazaar query gpu_price_index_history --terminal
compute-bazaar sql "select * from gold.fact_gpu_price_index" --terminal
```

`compute-bazaar terminal` opens a main menu:

- **Data** opens the DataFusion and Perspective workspace for Silver and Gold.
- **Eval** opens the full private evaluation viewer for tasks, jobs, trials, and notes.
- **Trade** is visible but locked until the execution system exists.

The command starts the local backend, opens the repo-owned Tauri window, and
returns the shell prompt. Use `compute-bazaar terminal --foreground --open` for
browser development.
Press `Cmd+K` in any workspace to run read-only SQL or commands such as `data`,
`eval`, `tables`, `view gpu-index-history`, and `describe gold.fact_gpu_price_index`.

Custom SQL can open directly as a chart:

```bash
compute-bazaar sql "select observed_at, gpu, price_usd_gpu_hr from gold.fact_gpu_price_index_history" --terminal --chart line --x observed_at --series gpu --y price_usd_gpu_hr
```

DataFusion runs every Data query and Perspective renders the Arrow result.
Saved analyses keep SQL and layout as reviewable repository files. Evaluation
reports remain in their purpose-built viewer. The server listens on localhost only.
