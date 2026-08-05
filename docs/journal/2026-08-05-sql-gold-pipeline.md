# SQL-Owned Gold Pipeline

## Why

The project had two correct packaged SQL models for the public GPU benchmark,
but most of the maintained GPU Gold tables were still authored as multiline
SQL strings inside Python. DataFusion executed them, yet the repository did not
make the intended ownership boundary obvious: Python should operate the lake;
SQL should define relational market products.

## Decision

The stable Gold transformations now live under
`src/the_compute_bazaar/sql/models/gold/`:

- normalized GPU listings;
- GPU product, provider, and region dimensions;
- floor-index values and constituents;
- frontier benchmark values and constituents;
- compute market state;
- Prime provider-balanced reference history;
- Prime benchmark-centered offer ladder.

Python still owns provider calls, variable Parquet source registration,
stateful history merging, Prime offer lifecycle comparison, validation,
storage, and manifests. These are pipeline and state mechanics rather than
relational table definitions.

Templates distinguish quoted literal values from tightly controlled SQL
fragments. Fragments are only used for source CTEs whose number varies with the
providers present in a market run and for the optional market-state source.

## Reproducibility

The Gold manifest now records the model ID, packaged path, and SHA-256 for every
SQL model executed in that generation. Prime model metadata is included only
when the corresponding output table was built. The methodology version remains
unchanged because this migration preserves the existing calculations and
published schemas.

## Verification

The local two-provider build and four repository tests pass. A built wheel was
inspected and contains the SQL catalog, all saved queries, and all eleven Gold
model files. The migrated Prime models were also executed read-only against the
live S3 Gold history: they returned 603 reference rows and 40 ladder rows across
H100, H200, B200, and B300.

The Windmill worker was rebuilt as
`compute-bazaar-windmill-worker:2026-08-05-sql-sandbox-v3` and recreated
successfully. Its packaged `fact_gpu_listings` model hash matched the local
source.

The first hourly generation after deployment completed successfully at 11:00
UTC as `gold-market-20260805T110000-5af0666f`. Its manifest contains all eleven
executed SQL models with their packaged paths and hashes. The surrounding
market run completed every provider, Gold, sandbox, and dashboard-export check
with status `ok`. This is the production proof that the recurring worker is
executing the packaged SQL-owned Gold pipeline.

The installed CLI was then exercised against that generation in both supported
Gold modes. The named `benchmark_values:v1` query returned the four frontier
families, and bounded scratch SQL returned a grouped listing view with its
read-only flag intact. The built wheel contains the catalog, eleven Gold model
files, eight cataloged Gold queries, and two lower-level Silver diagnostics.
