# Architecture

```text
provider APIs
  scheduled -> Windmill -> Bronze -> Silver Parquet -> Gold -> public lake
  direct -------------------------> private operations -> allocation -> Fleet

Silver Parquet + private operations -> silver.offer_observations
                                    -> DataFusion -> CLI / Terminal
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

All provider reads use one row contract and one DataFusion table:

```text
silver.offer_observations
  scheduled   hourly market record used by Gold
  interactive direct provider read
  preflight   provider read immediately before launch
```

Windmill writes scheduled rows to S3 each hour and publishes them to AutoMQ.
Direct reads and launch checks are written to the private local ledger when
they happen. DataFusion unions both stores as `silver.offer_observations`.
`observation_purpose` says why a row exists. `observation_resolution` and
`selection_resolution` say how precisely it identifies something a provider
can supply.

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
Eval contains the Harbor evaluation viewer, and Trade remains reserved for the
later execution system.

## Fleet

The launch path is:

```text
offer observation
  -> final provider check
  -> provider allocation
  -> Fleet machine
  -> Fleet observations and workloads
```

`silver.current_offers` is the latest direct observation for each provider
selection. `fleet.allocations` links a machine to the exact final-check row.
`gold.fact_market_to_fleet` compares the selected price with the nearest prior
GPU Price Index and the machine that was delivered. Private machine data stays
local.

SQL or an agent can find a candidate and prepare a launch plan. Creating a paid
machine still requires a price ceiling, runtime deadline, and explicit
confirmation.

Fleet workloads are detached SSH process groups. Their command, PID, state, exit
code, and local log references live in the private operational ledger. Fleet also
reads NVIDIA compute-process rows, so the Terminal can show which processes are
using each GPU. Host termination closes any workload records still marked active.
