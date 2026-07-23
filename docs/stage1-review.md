# Stage 1 Review

The Compute Bazaar is now a Stage 1 GPU market-data platform: provider ingestion, event stream,
S3 bronze/silver/gold lake, Curia-authored market products, DataFusion methodology queries, and
dashboard snapshots.

Before this stage, the repo was a research workbench with useful scripts and good architecture
ideas. Now it has a connected platform loop:

```text
Provider APIs
  -> Windmill scheduled workers
  -> AutoMQ / Kafka event stream
  -> S3 bronze raw evidence
  -> S3 silver normalized offers
  -> Curia engine
  -> DataFusion SQL methodology queries
  -> S3 gold market objects
  -> dashboard / CLI / future API / agents
```

## What We Proved

Vast and Lium both ingest into the same market schema. The VPC-connected Windmill worker can pull
provider data, write raw evidence, normalize offers, publish AutoMQ events, build S3-backed market
tables, and feed the dashboard snapshot path.

The latest Stage 1 review boundary was:

```text
Vast run:  vast-20260617T230000-ffcb1688
Lium run:  windmill-lium-stage1-final-20260618
Gold run:  gold-stage1-review-20260618
```

That gold run produced:

```text
181 market listings
50 GPU products
2 providers
41 regions
28 price-index rows
126 index constituents
```

The important shift is that Compute Bazaar does not just show prices. It produces an explainable
compute price index from raw provider evidence.

## Layer Model

```text
bronze:
  raw provider evidence for audit and replay

silver:
  normalized offers, including edge cases and provider-specific messiness

gold/fact_gpu_listings:
  Curia-authored query-ready listing observations

gold/fact_price_index_values:
  published Curia-authored price outputs

gold/fact_price_index_constituents:
  explainability and audit trail for each index value

gold/dim_gpu_products, gold/dim_providers, gold/dim_regions:
  dimensions for product surfaces and queries
```

Consumers should mostly read gold. Silver remains useful for debugging and rebuilding gold when
methodology changes.

DataFusion is not the gold layer. It is the SQL engine Curia uses to compute, test, and reproduce
market methodology over Parquet/S3 inputs. Gold is the materialized product truth Curia writes after
that controlled computation.

## Findings

1. Gold/dashboard refresh now has a single `market-hourly` command and Windmill script. It has run
   from the VPC worker. The next risk is operational: observe the first scheduled cycles and confirm
   that every heartbeat writes provider manifests, gold tables, dashboard JSON, and a market-run
   manifest.

2. Lium ingestion now has pagination and deduping. We should still validate real provider behavior
   over multiple runs before treating it as complete-market coverage.

3. Failed Kafka publishing can leave raw/silver S3 objects without a success manifest. That is
   acceptable for dev evidence, but production needs failed-run manifests or reconciliation.

4. The dev Windmill worker is intentionally pragmatic: a baked EC2 Docker image. Before production,
   move toward a registry-built worker image, tighter IAM, and normal Windmill sandboxing.

## Next Milestone

Do not add another provider yet. The next milestone is to operate the platform heartbeat:

```text
market_hourly Windmill flow
1. ingest Vast
2. ingest Lium
3. build gold
4. export dashboard JSON
5. run stage1-check
6. write one market run manifest
```

The output is one top-level market run:

```json
{
  "market_run_id": "market-20260618T120000",
  "providers": ["vast", "lium"],
  "provider_runs": ["vast-...", "lium-..."],
  "gold_run_id": "gold-...",
  "dashboard_export_id": "dashboard-...",
  "listing_count": 181,
  "gpu_product_count": 50,
  "index_row_count": 28,
  "status": "success"
}
```

That manifest is the heartbeat: the thing a dashboard, API, CLI, or agent can inspect to know
whether the market is fresh.

## Index Direction

The compute index is one of the first real gold products. For Stage 1, keep it simple and honest:

```text
Compute Bazaar Live Price Index
Indicative, provider-observed plus published-rate context, refreshed hourly
```

The first index family can start as:

```text
index_family = gpu_live_price
gpu_product = h100 | a100 | rtx4090 | ...
region_group = global
measure = floor | median | p25 | p75
```

Each published value should retain its constituents:

```text
index_value_id
listing_id
provider_id
gpu_product_id
price_per_gpu_hour
included
exclusion_reason
source_run_id
raw_uri
normalization_version
methodology_version
```

That lets every product output answer:

```text
What run created this?
What raw evidence supports it?
What silver rows fed it?
What gold table exposed it?
What query/index methodology produced it?
```

That is what makes this market infrastructure, not just a dashboard.

## Roadmap

1. Observe the `market_hourly` Windmill schedule over multiple hourly cycles
2. Public-safe S3/CloudFront dashboard JSON
3. Market-run history charts over recent heartbeats
4. Richer index methodology: median, p25, p75, and exclusion policy versions
5. Provider coverage and field completeness scoring
6. MCP/API over Curia-authored gold tables and DataFusion-backed query tools
7. Historical time series, not just latest snapshots

The agent layer should come after stable gold tables. Agents should first answer grounded questions:

```text
What is the cheapest fresh H100?
How has A100 pricing moved this week?
Which provider is cheapest for secure A6000?
Which raw run supports this index value?
```

## Honest Read

Stage 1 is done enough to review.

The next turn is not more architecture. It is operating freshness:

```text
working manually -> scheduled hourly -> public-safe surface -> query/API layer
```

Once the gold/dashboard refresh is automatic, the platform starts feeling alive.
