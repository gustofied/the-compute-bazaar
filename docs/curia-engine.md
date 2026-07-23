# Curia Engine

Curia is the Compute Bazaar authoring layer for market truth.

It is not a separate database and it is not only DataFusion. Curia is the controlled engine that
decides which inputs are allowed, which methodology runs, which query or algorithm produced an
output, and what gets published into Gold.

```text
Provider connectors -> Bronze
Normalizers         -> Silver
Curia Engine        -> Gold
Dashboard/API/MCP   -> read Gold first
```

The rule is:

```text
Gold is not where data lands.
Gold is where Curia publishes its view of the market.
```

## Layer Roles

Bronze is raw evidence. It stores exact provider responses, provider documents, screenshots,
contracts, or other source-shaped artifacts.

Silver is standardized observation data. It is still close to the source, but uses common schemas
such as `silver/gpu_offers`.

Curia is the transformation and decision layer. It can use DataFusion SQL, Python transforms, scoring
algorithms, or later agent-assisted evidence workflows. The important property is that Curia outputs
are controlled, versioned, and tied to input manifests.

Gold is business-purpose market data. Gold tables should answer product questions:

- current market listings
- provider comparison
- benchmark/index values
- benchmark constituents and exclusions
- market-run summaries
- accepted provider/product/region labels

Workspace or evidence artifacts are messy investigation outputs. Agents can read S3 objects, inspect
raw evidence, grep files, and write notes there, but those notes are not Gold until Curia validates
and promotes them.

## DataFusion's Role

DataFusion is the SQL compute engine Curia uses over Parquet lake tables. It is perfect for:

- joins
- filters
- windows
- percentiles
- provider comparisons
- freshness calculations
- benchmark values
- constituents and exclusion rules

The current benchmark implementation follows this pattern:

```text
gold.fact_gpu_listings
  -> Curia runs named DataFusion SQL
  -> gold.fact_benchmark_values
  -> gold.fact_benchmark_constituents
  -> public dashboard JSON
```

The query definitions live in:

```text
src/the_compute_bazaar/prices/benchmark_queries.py
```

The materialized gold tables are the hourly published memory of those named queries. They are not the
deepest truth; the deepest truth is the raw evidence, silver observations, gold inputs, methodology
query, and manifest chain that can reproduce them.

The benchmark input set can include two kinds of provider observations:

- live marketplace offers from provider APIs such as Vast and Lium
- official published rate-card observations from providers such as Runpod, Lambda, Hyperstack,
  Nebius, Crusoe, Denvr, DigitalOcean, GMI Cloud, Massed Compute, TensorDock,
  Verda, VESSL, and Voltage Park

Curia keeps those source types legible. The advertised benchmark uses one
eligible floor per provider and publishes their median, while future and
committed rates remain evidence rather than constituents. Published rate cards
improve benchmark coverage, but they are not executable inventory. Live
procurement workflows should still confirm availability through live provider
APIs.

## Gold Contract

Every Curia-authored gold object should carry enough metadata to explain itself:

```text
input_market_run_id
input_provider_runs
input_silver_refs
engine_version
methodology_version
methodology_query_id
created_at
row_counts
warnings
```

For benchmark values, the product contract is:

```text
benchmark value
constituent rows
included/excluded flag
exclusion reason
methodology version
methodology query id
source run id
```

That is what separates market infrastructure from an ordinary dashboard.

## Agent Model

Agents should usually ask Gold first through Curia/API/MCP/DataFusion:

```text
What is the current H100 benchmark?
Show the H100 benchmark constituents.
Compare B200 provider coverage across recent runs.
```

When they need proof or debugging, agents can drill down into raw evidence:

```text
Which provider run supports this value?
Which raw provider payload contained this listing?
Why was this row normalized this way?
```

The promotion path should stay controlled:

```text
agent observation
  -> workspace artifact
  -> Curia validation / scoring / optional review
  -> Gold label or signal
```

The line to keep:

```text
DataFusion computes structured truth.
Agents investigate contextual truth.
Curia decides what becomes product truth.
Gold stores product truth.
```

## Operator Workbench

The local `/operator/` page is the first practical Curia workbench. It is intentionally small:
versioned DataFusion SQL from `queries/curia/`, a result table, row click-through, manifest context,
and preview buttons for allowed evidence refs. Python does not define these views. Python loads the
catalog, registers gold Parquet refs, executes SQL, and returns results.

It also includes a read-only scratch SQL console. Scratch SQL uses the same DataFusion runner as
cataloged SQL, but it is intentionally constrained: one `SELECT` or `WITH` statement, latest gold
`fact_*` and `dim_*` tables only, no writes, no external file reads, and a bounded limit. Scratch is
for exploration. Cataloged SQL is for methodology and product truth.

Each cataloged query has:

- `query_id`
- `version`
- `sql_path`
- `query_hash`
- `engine = datafusion`
- declared input gold tables

It should grow in this order:

1. versioned SQL views for benchmark values, constituents, listings, provider comparison, and table counts
2. row drill-down from Gold to Silver and Bronze evidence
3. run-to-run comparison
4. controlled promotion actions for labels, notes, and qualitative market objects
5. custom SQL only after the cataloged views are stable
