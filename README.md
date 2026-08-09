<p align="center">
  <img src="assets/compute-bazaar-wordmark.png" alt="The Compute Bazaar" width="440"><br>
  <strong>The Compute Bazaar</strong><br>
  <a href="#terminal">Terminal</a> • Data • Eval • Fleet • Trade
</p>

My vision is to build The Compute Bazaar as much for humans as for
machine-to-machine work.

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

More detail: [Architecture](docs/architecture.md).

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

## Query

Start by listing the DataFusion catalog and inspecting a table.

```bash
compute-bazaar tables
compute-bazaar describe silver.gpu_offers
compute-bazaar describe gold.fact_gpu_price_index
```

Run a built-in market query or write SQL directly.

```bash
compute-bazaar availability --gpu-model H100 --history --limit 20

compute-bazaar sql "
select provider, gpu_model, price_usd_gpu_hr
from silver.gpu_offers
order by price_usd_gpu_hr
limit 20
"
```

## Terminal

<p align="center">
  <img src="assets/compute-bazaar-terminal.png" alt="The Compute Bazaar Terminal" width="80%">
</p>

The Terminal is where we look at data, evaluate agents, and eventually place
trades.

Let's start with Data, and how The Compute Bazaar enables market models and
views that can be stored, reused, shared, and used by agents. It works both
ways: people can make models for agents, and agents can make models and views
for people or other agents to use later. A model can also run inside a pipeline,
for example whenever a new hourly observation arrives. The Compute Bazaar is
extensible.

```bash
uv sync --extra terminal
pnpm --dir terminal install
compute-bazaar terminal
```

The Terminal opens with Data, Eval, and Trade. Data is where DataFusion queries
market data and [Perspective](https://perspective-dev.github.io) turns the
results into tables and charts. Eval contains agent evaluation tasks, jobs, and
trials powered by Harbor. Trade is in the works.

Data can open a saved query or custom SQL as an interactive table or chart.

```bash
compute-bazaar query gpu_price_index_history --terminal

compute-bazaar sql "
select
  gold_observed_at as observed_at,
  benchmark_family_id as gpu,
  benchmark_usd_gpu_hr as price_usd_gpu_hr
from gold.fact_gpu_price_index_history
where benchmark_family_id in ('H100', 'H200', 'B200', 'B300')
order by observed_at, gpu
" --terminal --chart line --x observed_at --series gpu --y price_usd_gpu_hr
```

A market model contains reusable DataFusion SQL. Its view describes how
Perspective displays the result. Terminal Save writes both under `analyses/`,
where they can be rerun, shared, reviewed, or used by agents.

```bash
compute-bazaar model list
compute-bazaar model run h200-under-4
compute-bazaar blueprint open h200-under-4
```

For anyone who wants to read the market, whether a quant, a broker, or someone
looking in from the outside, being able to curate your own market models and
views is useful. The Compute Bazaar gives you that: write the model, save its
view, and run it again as new data comes in.

Press `Cmd+K` inside the Terminal to run SQL, inspect tables, or move between
Data and Eval. Stop the Terminal with:

```bash
compute-bazaar terminal --stop
```
