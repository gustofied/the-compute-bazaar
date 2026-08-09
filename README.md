<p align="center">
  <img src="assets/compute-bazaar-wordmark.png" alt="The Compute Bazaar" width="440">
</p>

<p align="center">
  <img src="assets/compute-bazaar-terminal.png" alt="The Compute Bazaar Terminal" width="80%">
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

`data sync` downloads the latest public Silver and Gold tables. Run it again
for the newest hourly data; `data status` shows the current run and freshness,
while `price-index` prints one example market view.

`compute-bazaar` prints tables by default. Use
`compute-bazaar --format json COMMAND` for machine-readable output.

## Terminal

The Terminal is where we look at data, evaluate agents, and eventually place
trades.

Let's start with Data, and how The Compute Bazaar enables creative analysis
that can be stored, reused, shared, and used by agents. It works both ways:
people can make analyses for agents, and agents can make analyses for people or
other agents to use later. The same saved analysis can also run inside a
pipeline, for example as a recurring market analysis whenever a new hourly
observation arrives. The Compute Bazaar is extensible.

```bash
uv sync --extra api
pnpm --dir terminal install
compute-bazaar terminal
```

The Terminal opens with Data, Eval, and Trade. Data is the DataFusion and
Perspective workspace for Silver and Gold. Eval contains evaluation tasks,
jobs, and trials. Trade is locked until the execution system exists.

Start by listing the DataFusion catalog and inspecting a table.

```bash
compute-bazaar tables
compute-bazaar describe silver.gpu_offers
compute-bazaar describe gold.fact_gpu_price_index
```

Run a market command or write SQL directly.

```bash
compute-bazaar availability --gpu-model H100 --history --limit 20

compute-bazaar sql "
select provider, gpu_model, price_usd_gpu_hr
from silver.gpu_offers
order by price_usd_gpu_hr
limit 20
"
```

Open a saved query in the Terminal or send custom SQL directly into a chart.

```bash
compute-bazaar query gpu_price_index_history --terminal

compute-bazaar sql "
select observed_at, gpu, price_usd_gpu_hr
from gold.fact_gpu_price_index_history
" --terminal --chart line --x observed_at --series gpu --y price_usd_gpu_hr
```

When an analysis is worth keeping, save its SQL as a model and its Perspective
layout as a blueprint. Both remain normal repository files under `analyses/`.
The Terminal Save action writes them together.

```bash
compute-bazaar model list
compute-bazaar model run h200-under-4 --terminal
compute-bazaar blueprint open h200-under-4
```

Press `Cmd+K` inside the Terminal to run SQL, inspect tables, or move between
Data and Eval. Stop the Terminal with:

```bash
compute-bazaar terminal --stop
```
