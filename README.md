<p align="center">
  <img src="assets/compute-bazaar-wordmark.webp" alt="The Compute Bazaar" width="440"><br>
  <strong>The Compute Bazaar</strong><br>
  <a href="#terminal">Terminal</a> • <a href="#data">Data</a> • <a href="#eval">Eval</a> • <a href="#fleet">Fleet</a> • Trade<br><br>
  <a href="https://www.adamsioud.com/exemplars/compute/feeling_the_compute">Article</a>
</p>

With The Compute Bazaar, you sit at the compute trading desk. Use live and
historical market data to analyse the market and build your own models. Find and
rent compute, then operate and monitor it through Fleet. Connect Codex/OpenCode
through ACP. In Eval, create and run Harbor benchmarks for agents across compute
deal work and compute market games. Finally, Trade explores financial
instruments for hedging compute price and availability risk.

The Compute Bazaar is ongoing work, continuing ideas from my earlier work on
[OUDAU](https://www.adamsioud.com/projects/oudau.html).

## Setup

Install The Compute Bazaar.

```console
$ curl -fsSL https://raw.githubusercontent.com/gustofied/the-compute-bazaar/refs/heads/main/install.sh | sh
```

Or clone the repository.

```console
$ git clone https://github.com/gustofied/the-compute-bazaar.git
$ cd the-compute-bazaar
$ ./install.sh
```

Open the Terminal.

```console
$ compute-bazaar terminal
```

## Architecture

The Bazaar uses Windmill for orchestration, AutoMQ for event streaming, S3 for
storage, Parquet for the lake format, DataFusion for queries, Perspective for
dashboards/views, Tauri for the Terminal, ACP for agents, and Harbor for Eval.
Read more about the [pipeline](infra/windmill/README.md), [public
lake](infra/aws/public-feed/README.md), and [architecture](docs/architecture.md).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/compute-bazaar-architecture-dark.png">
    <img src="assets/compute-bazaar-architecture.png" alt="The Compute Bazaar architecture" width="92%">
  </picture>
</p>

## Data

Bronze keeps raw evidence, Silver is normalized market data, and Gold contains
shared models such as GPU price and availability indexes. A sanitized Silver
and Gold lake is published to a rolling GitHub Release for
`compute-bazaar data sync`.

`compute-bazaar` prints tables by default. Use
`compute-bazaar --format json COMMAND` for machine-readable output.

Start by listing the DataFusion catalog and inspecting a table.

```bash
compute-bazaar tables
compute-bazaar describe silver.offer_observations
compute-bazaar describe gold.fact_gpu_price_index
```

Run a built-in market query or write SQL directly.

```bash
compute-bazaar availability --gpu-model H100 --history --limit 20

compute-bazaar sql "
select provider, gpu_model, price_usd_gpu_hr
from silver.offer_observations
where observation_purpose = 'scheduled'
order by price_usd_gpu_hr
limit 20
"
```

`listings` reads the synced hourly record. `offers` asks RunPod and Verda what
can be selected now. Both use `silver.offer_observations`; the row says whether
it came from the hourly run or a direct provider read.

```bash
compute-bazaar offers list --provider runpod --gpu-model H100
compute-bazaar offers inspect OFFER_ID
```

RunPod's live catalog is public. Verda live availability uses the OAuth values
shown in `.env.example`.

The Sesterce market path writes a separate local lake:

```bash
export SESTERCE_API_KEY=...
compute-bazaar market ingest sesterce
compute-bazaar terminal market
```

That Terminal exposes `silver.gpu_offers`. The default Terminal continues to
use the synced public Silver and Gold lake.

The full provider cycle can also run locally without Windmill, AutoMQ, or AWS:

```bash
uv sync --extra market
compute-bazaar market refresh
compute-bazaar terminal local
```

Use `--provider NAME` more than once to limit a refresh. Private sources read
their existing environment credentials. Each run records the market at that
moment; periods when it is not running cannot be reconstructed later.

To update the public snapshot, publish the sanitized lake created by that run:

```bash
compute-bazaar data publish
```

Publishing uses the authenticated GitHub CLI. Raw evidence and credentials are
never included in the release.

Before shutting down an S3 deployment, keep one private offline archive:

```bash
uv sync --extra s3
compute-bazaar data archive --source-root s3://YOUR_BUCKET/
compute-bazaar data verify-archive
```

The archive is incremental, checksummed, ignored by Git, and can replay its
original `s3://` references through `data/cloud-archive/offline.env`.

## Terminal

<p align="center">
  <img src="assets/compute-bazaar-terminal.png" alt="The Compute Bazaar Terminal" width="80%">
</p>

The Terminal is where we look at data, operate Fleet, and evaluate agents.

Let's start with Data, and how The Compute Bazaar enables market models and
views that can be stored, reused, shared, and used by agents. It works both
ways: people can make models for agents, and agents can make models and views
for people or other agents to use later. A model can also run inside a pipeline,
for example whenever a new hourly observation arrives. The Compute Bazaar is
extensible.

The Terminal opens with Data, Fleet, Eval, and Trade. Data is where DataFusion
queries market data and [Perspective](https://perspective-dev.github.io) turns
the results into tables and charts. Eval contains agent evaluation tasks, jobs,
and trials powered by Harbor. Trade is reserved for later research. The
Terminal currently supports macOS and Linux.

The side drawer has Shell and Agent tabs. Agent runs through ACP and uses the
same `compute-bazaar` CLI; results opened with `--terminal` appear in Data.

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
Perspective displays the result. Terminal Save keeps personal models and views
outside the Git checkout. They can be rerun or used by agents without being
shared.

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

## Eval

[Compute Bazaar Bench](https://github.com/gustofied/the-compute-bazaar/tree/main/compute-bazaar-bench) is a benchmark for evaluating agents on compute-market tasks.

<p align="center">
  <a href="https://github.com/gustofied/the-compute-bazaar/tree/main/compute-bazaar-bench"><img src="assets/compute-bazaar-eval.webp" alt="The Compute Bazaar Eval" width="80%"></a>
</p>

I created something I call Tourneys, where you can compare agents on these
tasks under the same conditions, using the same seeds, harness, and setup.

## Fleet

<p align="center">
  <img src="assets/compute-bazaar-fleet.webp" alt="The Compute Bazaar Fleet monitoring a live NVIDIA node" width="80%">
</p>

Fleet operates NVIDIA nodes over SSH. A node can be provisioned from a live
offer or attached through OpenSSH. Fleet records inventory, runs readiness
checks, monitors telemetry and health every five seconds, and tracks workloads
and logs.

```text
Live offer
  -> availability check
  -> provision
  -> allocation ----+
                    |
SSH host -> attach -+-> Fleet node
                          |
                          +-> inventory
                          +-> readiness and diagnostics
                          +-> telemetry and health
                          +-> workloads and logs
```

Attach an existing node by SSH host alias. OpenSSH resolves its address, user,
key, agent, and jump host; Fleet stores only the alias.

```bash
compute-bazaar fleet attach gpu-singapore-01 --expect H100 --count 8
```

Or use the Sesterce market path to launch an offer.

```bash
compute-bazaar market ingest sesterce

compute-bazaar fleet plan OBSERVATION_ID \
  --name HOST \
  --ssh-key-id SESTERCE_KEY_ID

compute-bazaar fleet launch OBSERVATION_ID \
  --name HOST \
  --ssh-key-id SESTERCE_KEY_ID \
  --max-hourly-usd 4 \
  --runtime-minutes 30 \
  --confirm
```

RunPod remains available through its direct provider path.

```bash
compute-bazaar offers list --provider runpod

compute-bazaar launch run OFFER_ID \
  --name HOST \
  --image runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404 \
  --max-hourly-usd 0.75 \
  --runtime-minutes 30 \
  --confirm-spend
```

Inspect it, run readiness checks, monitor it, and run workloads through the CLI
or Terminal.

```bash
compute-bazaar fleet hosts
compute-bazaar fleet inspect HOST_ID
compute-bazaar fleet doctor HOST_ID
compute-bazaar terminal
compute-bazaar fleet workload run HOST_ID --name training -- python train.py
compute-bazaar fleet workload list --host HOST_ID
compute-bazaar fleet workload logs WORKLOAD_ID
compute-bazaar fleet terminate HOST_ID --confirm
```

The existing public/direct catalog also exposes private allocation and Fleet
views:

```bash
compute-bazaar sql "select * from silver.current_offers order by price_usd_gpu_hr"
compute-bazaar sql "select * from silver.offer_observations order by observed_at desc"
compute-bazaar sql "select * from fleet.nodes order by created_at desc"
compute-bazaar sql "select * from gold.fact_market_to_fleet"
compute-bazaar model run gpu-launch-candidates
```

`launch run` checks availability and price again before spending, then records
the offer on the allocation. Fleet keeps node inventory, five-second telemetry,
workload state, exit codes, and logs. Remote workloads continue when the
Terminal closes.

If a launch ends before RunPod confirms the result, reconcile it before trying
again.

```bash
compute-bazaar launch reconcile ATTEMPT_ID
```

For Sesterce, the runtime budget and deadline are recorded and shown in Fleet,
but automatic shutdown is not guaranteed. Terminate the host explicitly. After
an ambiguous Sesterce create failure, check Sesterce before retrying; automated
reconciliation currently covers RunPod only.

Trade remains a research direction around availability, price and basis,
operator breadth, and bounded execution. There is no matching engine here.
