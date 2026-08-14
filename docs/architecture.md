# Architecture

```text
Public market
  provider APIs -> Windmill -> Bronze -> Silver -> Gold -> public lake

Rebuilt market path
  source API -> Bronze -> silver.gpu_offers -> preflight -> allocation -> Fleet
```

## Market data

Windmill runs provider ingestion each hour. AutoMQ carries the live observations
as a Kafka-compatible stream. S3 keeps the durable lake:

```text
Bronze  raw provider evidence
Silver  normalized market data
Gold    shared market models
```

A sanitized Silver and Gold copy is published as the public lake. The CLI syncs
that Parquet data locally, so DataFusion can query it without cloud credentials
or a database server.

The deployed public path uses one observation table:

```text
silver.offer_observations
  scheduled   hourly market record used by Gold
  interactive direct provider read
  preflight   provider read immediately before launch
```

Windmill writes scheduled rows to S3 each hour and publishes them to AutoMQ.
Direct RunPod and Verda reads and their launch checks are kept locally and
unioned into `silver.offer_observations`. `observation_purpose` says why a row
exists.

The rebuilt `market/` path starts again from a smaller contract:

```text
SourceRead -> Bronze -> GpuOffer -> silver.gpu_offers -> MarketGeneration
```

It currently supports Sesterce and a local lake. A source read records request
metadata and the full response. A normalized row keeps source, intermediary,
operator, offer, GPU, region, price, availability, and source-run identity. A
successful empty response still produces typed Silver evidence. The generation
format accepts several source runs, while `compute-bazaar market ingest`
currently publishes one source run per invocation.

These are two selectable catalogs, not one universal SQL catalog. The default
CLI and Terminal use the synced public Silver/Gold lake. `compute-bazaar terminal
lake2` opens the rebuilt local market lake. Fleet reads its private operational
ledger separately.

## Query layer

DataFusion runs SQL over the lake and returns Apache Arrow data. The CLI prints
the result directly; the Terminal passes the same Arrow result to Perspective
for interactive tables and charts.

## Market models

A market model is a reusable way of reading the compute market:

```text
market lake -> DataFusion SQL model -> Arrow result -> Perspective view
```

The SQL is the model logic. The view decides how its result is displayed. An
index, benchmark, curve, signal, or monitor is something the model may produce.

This also fits agents. An agent can run or write a model without opening the
Terminal, save it for later, or leave a view for a person or another agent to
use as new market data arrives.

The model and view remain separate, following
[Rerun's blueprint idea](https://rerun.io/docs/concepts/visualization/blueprints).
A working model becomes Gold only when it should be a shared data contract.

## Interfaces

The CLI and Terminal use the same DataFusion engine. Data is available now,
Eval contains the Harbor evaluation viewer, and Trade remains a research
direction rather than an implemented exchange.

Shell is a local PTY. Agent is a Bazaar thread connected to an external agent
over ACP. `acpx` is the internal ACP client beneath `AgentSession`, not part of
the Terminal contract. Eval stays in Harbor. The agent works through the repo
checkout using normal repo tools and `compute-bazaar`; Bazaar exposes no MCP
server or GUI control.

## Fleet

Fleet has two entry paths:

```text
offer -> launch -> allocation -\
                               -> Fleet machine -> inspect -> monitor -> workload
existing machine -> SSH attach /
```

SSH attachments use native OpenSSH targets, so host config, agents, and jump
hosts remain outside Bazaar. The registry stores the target and expected NVIDIA
hardware, while inspections store what the machine actually reports.

`silver.current_offers` is the latest direct observation for each provider
selection. `fleet.allocations` links a machine to the exact final-check row.
`gold.fact_market_to_fleet` compares the selected price with the nearest prior
GPU Price Index and the machine that was delivered. Private machine data stays
local.

SQL or an agent can find a candidate and prepare a launch plan. Creating a paid
machine requires a price ceiling, runtime budget, and explicit confirmation.
RunPod sends its deadline to the provider. Sesterce stores and displays the
deadline, but currently requires explicit termination. An ambiguous Sesterce
create must be checked manually before retrying; automated reconciliation is
RunPod-only.

Fleet workloads are detached SSH process groups. Their command, PID, state, exit
code, and local log references live in the private operational ledger. Fleet also
reads NVIDIA compute-process rows, so the Terminal can show which processes are
using each GPU. Host termination closes any workload records still marked active.
