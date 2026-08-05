# Stage 1 Review

The Compute Bazaar is now an operating Stage 1 compute market-data platform.
Its current boundary is observation, evidence, normalization, queryable market
products, and public explanation:

```text
GPU and VM source APIs
  + reviewed sandbox prices
  + public measured workload results
  -> Windmill hourly observation cycle
  -> AutoMQ event tape
  -> S3 bronze evidence
  -> S3 silver observations
  -> DataFusion SQL
  -> S3 gold products
  -> saved SQL / public article
```

It is not yet a procurement, RFQ, reservation, or settlement system. Those
future layers should consume the market memory built here rather than be mixed
into this stage.

## What Is Operating

The hourly Windmill run isolates source failures, retains immutable source and
generation manifests, publishes normalized events to AutoMQ, builds GPU and
sandbox/VM gold, exports public-safe JSON, and writes one top-level market-run
manifest.

The retained cadence audit from 25 July 00:00 UTC through 26 July 10:00 UTC
found all 35 expected hourly slots. Manual reruns remain additional immutable
observations. The 10:00 UTC run completed 17 of 18 configured GPU source paths;
Oracle's public GPU catalog returned repeated 502 responses, while gold and
publication still completed from the successful sources. The next scheduled
run at 11:00 UTC recovered and completed all 18 sources.

The current product generation contained:

```text
1,912 normalized gold GPU listings
224 GPU price-index rows
4 frontier benchmark values
868 current compute-market-state rows
7 exact-shape public VM offers
11 reviewed managed-sandbox rates
69 complete latest StarSling jobs
maintained Gold tables declared by component manifests
```

Counts vary by observation. The manifest, not this review document, is the
live authority.

## Data Model

Bronze is the evidence record:

- raw provider and catalog responses;
- retrieval timestamps, source URLs, and checksums;
- reviewed sandbox price evidence;
- commit-pinned public benchmark captures.

Silver is source-honest normalized observation data:

- GPU offers and compute-market-state observations;
- exact-shape VM offer and discovery history;
- managed-sandbox prices and timing semantics;
- StarSling runs, batches, replicates, and phases.

DataFusion executes named SQL over registered Parquet tables; Python handles
deterministic ingestion, execution, manifests, and publication. The Gold
manifest records which inputs and SQL models produced a market object.

Gold is the product memory:

- GPU listings, dimensions, indexes, benchmarks, and constituents;
- current and historical market-state observations;
- fixed-cohort VM rates and current offers;
- sandbox rate histories and current cross-sections;
- measured workload summaries, run history, and estimated resource cost;
- source-honest relative series used by the article.

Gold is not limited to numeric `fact_*` and `dim_*` tables. A future reviewed
request, RFQ, article, or qualitative market object can be gold when it has a
controlled schema, provenance, and promotion rule.

## Product Surfaces

### Query Layer

DataFusion executes the maintained SQL catalog over tables declared by the
latest Gold manifests. There is currently no public query server or operator
workbench; the future public interface will be designed after the repository
and publication contract are clean.

### Dashboard And Article

The AdamSioud article is the narrative surface. It reads sanitized JSON derived
from Gold; it does not calculate benchmark values in JavaScript or read private
lake paths.

The article intentionally shows only selected product views. It currently uses:

- H100/H200/B200/B300 observed benchmark history;
- market capacity and availability measures with source-specific denominators;
- exact-shape VM and managed-sandbox rate context;
- same-workload StarSling runtime and estimated resource cost;
- exploratory base-100 GPU/VM/sandbox movement with unlike raw units kept off
  one axis.

Local article previews now prefer the same CloudFront feed as production and
fall back to checked-in JSON only when the remote publication is unavailable.

## What The System Proves

The platform can answer:

```text
What did each source publish at this observation time?
How was the source normalized?
What current gold objects did the market run create?
What is the observed provider-floor benchmark for a frontier GPU?
Which constituents and exclusions support that value?
What does a fixed 4 vCPU / 8 GiB public VM cost across the maintained cohort?
What did the same public workload cost and how long did it run?
Which raw or reviewed evidence supports a displayed row?
```

That is more than an hourly dashboard. It is a retained, queryable compute
market memory with a public story on top.

## Honest Limitations

- GPU benchmark values are observed advertised provider-floor medians, not
  executed prices or settlement-grade marks.
- Published rate cards provide price context but do not prove immediate
  capacity.
- Some source GPU labels remain normalization debt. They are retained as
  warnings rather than guessed into frontier products.
- B200 and B300 still have thinner live offer coverage than H100 and H200.
- Managed-sandbox prices are reviewed rate-card observations. Rebuilding gold
  hourly does not mean every marketing page changed or was re-reviewed hourly.
- StarSling owns workload execution. Compute Bazaar polls compatible public
  results and launches no paid benchmark jobs.
- Availability, active-capacity share, and rental occupancy have different
  denominators. The system retains those distinctions and does not publish one
  synthetic utilization number.
- The current Windmill worker is pragmatic infrastructure. A registry-built
  image, tighter IAM, and production sandboxing remain deployment work.

## Current Next Work

The immediate work remains inside Stage 1:

1. keep observing hourly cadence and distinguish source failures from quality
   warnings;
2. reduce meaningful normalization debt without merging unlike GPU products;
3. keep saved queries, component lineage, and public payload contracts in sync
   as Gold evolves;
4. continue responsive and accessibility QA for the public article;
5. make releases reproducible and keep the maintenance journal current.

Only after this layer is consistently boring to operate should the project
move outward into agent sourcing, RFQs, procurement, or market execution.
