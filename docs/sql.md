# SQL

DataFusion SQL is the structured transformation and query layer over the
Compute Bazaar lake.

```text
provider connectors -> bronze -> silver -> SQL models -> gold
                                             |
                                             -> saved queries
```

Python calls providers, preserves source payloads, registers Parquet inputs,
runs SQL, writes outputs, and records manifests. Market calculations belong in
SQL when they can be expressed relationally.

## Layout

```text
src/the_compute_bazaar/sql/
  models/
    gold/
      fact_gpu_listings.sql
      dim_gpu_products.sql
      dim_providers.sql
      dim_regions.sql
      fact_price_index_values.sql
      fact_index_constituents.sql
      benchmark_values.sql
      benchmark_constituents.sql
      fact_compute_market_state.sql
      prime_offer_reference_history.sql
      prime_offer_ladder.sql
      sandbox_workload_batch_history.sql
      sandbox_workload_run_history.sql
      sandbox_workload_latest_replicates.sql
      sandbox_workload_latest_phases.sql
      sandbox_workload_phase_summary.sql
      sandbox_workload_service_summary.sql
  queries/
    silver_offer_summary.sql
    silver_price_index.sql
    benchmark_values.sql
    benchmark_constituents.sql
    frontier_listings.sql
    provider_comparison.sql
    compute_market_state.sql
    prime_offer_history.sql
    prime_offer_levels.sql
    benchmark_job_costs.sql
  catalog.json
```

Models materialize maintained tables. Saved queries answer reusable questions
over those tables without writing new data.

The two `silver_*` queries are lower-level diagnostics used by `benchmark`,
`latest-index`, and the Stage 1 checks. They are packaged SQL too, but they are
not Gold models and do not materialize tables.

The hourly pipeline loads its maintained relational Gold transformations from
these SQL files. Python still owns provider I/O, variable source registration,
stateful history merging, Prime offer lifecycle comparison, Parquet writes,
validation, and manifests. Those are pipeline mechanics; the table
calculations are DataFusion SQL.

## Reproducibility

The Gold manifest records each executed SQL model's:

- model ID;
- methodology version;
- packaged SQL path;
- SHA-256 hash.

Together with input manifests and output table references, this identifies the
calculation that produced a published benchmark generation.

## Saved Queries

There are three intended query modes:

1. reviewed, named SQL over Gold tables declared by the latest Gold manifest;
2. bounded, read-only `SELECT` or `WITH` statements over those same tables;
3. explicit inspection of a Silver or Gold Parquet reference.

Gold is the default product surface. Silver remains available when a user or
agent needs normalized source detail, methodology development, or debugging.

The old ingestion-oriented `gpu-prices` command router and local operator
service have been removed. A future public interface should expose only these
read-only query modes rather than reintroducing provider ingestion and pipeline
administration as user commands. Useful exploratory SQL can be reviewed and
added to `sql/queries/` and `catalog.json`. Saving a query does not materialize
its result; a result becomes Gold only through a maintained model.
