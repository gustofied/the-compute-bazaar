# Architecture

```text
Default
  provider APIs -> local runner -> Bronze -> Silver -> Gold -> public lake
                                                            -> GitHub Release

Market to Fleet
  source API -> Bronze -> silver.gpu_offers -> preflight -> allocation -> Fleet

Optional hosted deployment
  Windmill -> same market run -> AutoMQ event stream
                             -> S3 -> CloudFront
```

## Market data

The local runner reads providers and writes the same three layers used by the
hosted pipeline:

```text
Bronze  raw provider evidence
Silver  normalized market data
Gold    shared market models
```

A sanitized Silver and Gold copy is packaged as a checksummed ZIP on the
repository's `public-lake` GitHub Release. The CLI verifies and replaces its
local cache atomically, so DataFusion can query it without cloud credentials or
a database server.

Windmill, AutoMQ, S3, and CloudFront remain an optional hosted deployment.
Windmill schedules the same market run; AutoMQ receives an event copy; S3 keeps
the private lake and CloudFront can serve public outputs. The core run does not
require any of them.

The deployed public path uses one observation table:

```text
silver.offer_observations
  scheduled   hourly market record used by Gold
  interactive direct provider read
  preflight   provider read immediately before launch
```

The local or Windmill runner writes scheduled rows. Direct RunPod and Verda
reads and their launch checks are kept locally and unioned into
`silver.offer_observations`. `observation_purpose` says why a row exists.

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

## Public delivery

The public release contains only the files named in `index.json`. Every file and
the ZIP itself has a SHA-256 checksum. `compute-bazaar data sync` verifies the
archive before replacing the current cache. A repeated sync of the same run
downloads nothing.

AdamSioud uses checked-in dashboard snapshots. It does not contact S3 or
CloudFront at runtime, so the article remains available when the hosted pipeline
is stopped. New market data appears only after a local refresh, a GitHub release
publish, and an intentional snapshot update.

The public release is the portable history for users; it does not contain raw
evidence. Before retiring S3, `compute-bazaar data archive` mirrors the private
bucket into a content-addressed, checksummed local archive. Its `offline.env`
maps the original `s3://` references onto that mirror for replay without AWS.

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
