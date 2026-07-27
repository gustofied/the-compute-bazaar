# Public Card Contracts

Date: 27 July 2026

## Decision

The article had become coupled to storage-oriented public audit payloads. The
GPU strip probed four legacy files, the Prime chart loaded all four products in
one payload with repeated benchmark histories, and the sandbox script consumed
one document containing rates, VM observations, workload runs, phases,
capacity methodology, and source ledgers.

Gold remains the complete product and audit layer. A new publication boundary
now derives compact, versioned card views from those public Gold products:

```text
market-overview.json
gpu-benchmark/{h100,h200,b200,b300}.json
prime-frontier/{h100,h200,b200,b300}.json
capacity/market-state.json
sandbox/{rates,workload}.json
```

The schema is `compute_bazaar_card_v1`. Each document declares its identity,
time window, status, unit, methodology, headline, series, range semantics,
coverage, sources, drilldown target, and card-specific data.

## Boundaries

- S3 Bronze, Silver, and Gold remain authoritative.
- DataFusion still calculates benchmarks and analytical products.
- The card layer performs selection and serialization, not new price math.
- Existing public audit payloads remain available.
- Article loaders prefer card views and fall back to legacy files during
  deployment overlap.
- Nested local proxy paths remain exact allowlist entries. Arbitrary S3 keys
  cannot be requested through the FastAPI snapshot route.
- Operator SQL and raw-reference preview endpoints are not part of the public
  card API.

## Compaction

The first implementation accidentally serialized history in both `series` and
`data`. Real S3-backed generation exposed the duplication. The final contract
stores each history once and reconstructs compatibility shapes only in browser
memory.

Measured uncompressed files from a real Gold export:

```text
market overview                 8 KiB
H100 benchmark                 16 KiB
other GPU benchmark families   12 KiB each
Prime H100                    264 KiB
Prime H200                    132 KiB
Prime B200                     64 KiB
Prime B300                    100 KiB
capacity market state         520 KiB
```

The first deployed overview inherited three private S3 manifest references
from the older market-run summary. They were not credentials and CloudFront
could not read those prefixes, but they violated the publication boundary.
The overview now selects an explicit compact run summary, and public market-run
serialization recursively removes private S3 references. Regression tests
cover both paths.

## Verification

```text
node --check compute-market.js
node --check compute-market-history.js
node --check prime-frontier-market.js
node --check sandbox-cost.js
uv run python -m compileall -q src
uv run python -m unittest tests.test_dashboard tests.test_sandbox_cost \
  tests.test_gpu_market_core tests.test_adamsioud
uv run gpu-prices export-gold-dashboard \
  --output-root /tmp/compute-bazaar-view-models-v2
```

The focused suite passed 79 tests. After the public-reference regression fix,
the complete repository suite passed 95 tests in 8.337 seconds. Browser
verification is recorded after the rollout checks.

## Next UI Work

The visual redesign should use these contracts rather than inspect Gold-shaped
documents. The first redesign unit is the GPU benchmark card. Prime depth,
capacity, VM rates, and sandbox workload should retain distinct visual
grammars because they measure different things.
