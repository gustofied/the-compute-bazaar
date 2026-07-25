# Public Workload and Capacity Sources

## Decision

Compute Bazaar will poll the public StarSling benchmark repository once per
day. It will not dispatch provider-funded benchmark runs.

The daily poll and hourly market heartbeat have different meanings:

```text
daily StarSling poll
  -> discover newly committed compatible workload evidence
  -> immutable bronze retrieval
  -> content-addressed workload silver generation

hourly market heartbeat
  -> observe live provider prices and capacity
  -> rebuild DataFusion gold
  -> publish the latest public-safe projection
```

Polling an unchanged StarSling commit must not create a new runtime
observation. The source refresh still records retrieval provenance, but the
silver generation ID is derived from content. Workload history changes only
after upstream publishes a new compatible run.

The discarded design maintained an owned StarSling fork, provider credentials,
a GitHub Actions dispatch token, and a Windmill switch for paid benchmark
execution. That machinery was technically sound but unnecessary for the
current article. It added credentials and cost without creating better source
honesty. The Windmill script and bootstrap now contain only the public source
poll.

## Capacity Source Audit

### Akash

The public Akash Console API reports active, available, pending, and total
capacity for each online provider:

```text
CPU                 millicores
GPU                 GPU units
memory              bytes
ephemeral storage   bytes
persistent storage  bytes
total storage       bytes
```

Akash operations documentation describes active inventory as resources
consumed by deployments. Silver therefore records six aggregate Akash
active-capacity rows with explicit units, online-provider scope, source URL,
and numerator and denominator definitions. These rows are never pooled across
resource units.

Akash is broad inside the Akash provider network. It is not a global cloud
fleet denominator and must not be presented as one.

### Prime Intellect

The initial audit incorrectly described Prime as lacking any denominator. The
installed Prime CLI was then inspected directly. `prime availability list`
enumerates returned GPU configurations and exposes `stock_status`; its JSON
`total_count` is the count after CLI filtering and optional grouping.

Silver now records:

```text
available configurations / all returned configurations
```

for each upstream provider and GPU product. This is a valid configuration
availability ratio. It is not a physical GPU-unit or rented-fleet ratio.
Prime's upstream provider remains in `provider`, while
`source_connector=prime_intellect` records the aggregation surface.

The local Prime CLI context returned an authorization error during the live
check on 26 July 2026, so the implementation was verified against the installed
CLI source, official response contract, and focused fixtures. Production Prime
collection still requires an availability-read API key.

### Clore

An unauthenticated live request to `https://api.clore.ai/v1/marketplace`
returned HTTP 200 and 2,090 public servers on 26 July 2026. The official Clore
API reference nevertheless marks the marketplace `auth` header mandatory.
The recurring connector remains credential-gated rather than depending on
undocumented unauthenticated behavior.

Clore's `rented` boolean supports a server-weighted on-demand occupancy series.
It does not include active spot orders in that numerator.

## Storage and Publication

Provider responses remain immutable bronze evidence. The normalized capacity
rows are written to:

```text
silver/compute_market_state
```

DataFusion materializes:

```text
gold.fact_compute_market_state
gold.fact_compute_market_state_history
```

The public `market-state.json` keeps the current cross-section and only
aggregate history for CPU, GPU, memory, and storage. Model-level and
configuration-level history remains in gold.

## Verification

Focused tests:

```sh
uv run --with pytest pytest \
  tests/test_windmill_bootstrap.py \
  tests/test_gpu_market_core.py -q
```

Result at implementation time:

```text
50 passed
```

## Production Release

The worker was rebuilt and only the Windmill worker service was recreated:

```text
image   compute-bazaar-windmill-worker:2026-07-26-capacity-source-v1
digest  sha256:121def069bea594a570f37542ba5cbe9a07fc6088e1c831964b158988d4b327f
```

Windmill server, Postgres, AutoMQ, and all volumes remained running.

The first source-only poll exposed a missing S3-region boundary in the
Windmill script environment. PyArrow attempted a multipart upload through the
wrong S3 endpoint and received a permanent redirect. The script now sets both
`AWS_REGION` and `AWS_DEFAULT_REGION` explicitly for its subprocess. The rerun
succeeded:

```text
schedule       f/compute-bazaar/sandbox_benchmark_daily_schedule
cron           0 30 6 * * *
enabled        true
source commit  c7c9abf328430e2b5a01b0a4f57863c0fdd87641
changed        false
new batches    0
generation     sandbox-workload-6f1a818f65624fdd
```

The production market heartbeat then completed every provider, Kafka, gold,
VM, sandbox, and dashboard stage:

```text
market run  market-20260725T231000-eafac7f4
gold run    gold-market-20260725T231000-eafac7f4
status      success
```

Akash produced 13 market-state rows: seven model-level GPU availability rows
and six aggregate capacity rows. DataFusion returned the aggregate rows from
`fact_compute_market_state`, and the public CloudFront payload exposed the
same current cross-section:

```text
https://d3n0n6h709c83f.cloudfront.net/market-state.json
```

The first published aggregate points were:

```text
CPU active share                 20.96%
GPU active share                 32.08%
memory active share              14.76%
ephemeral-storage active share    3.49%
persistent-storage active share   4.16%
total-storage active share        3.82%
```

These are Akash-network capacity measures with different units. They are not a
single pooled utilization index.

Final verification:

```text
90 tests passed
public sandbox/VM freshness check: ok
partial VM source runs: none
public aggregate GPU history points: 11
public CPU/memory/storage history points: 1 each
```
