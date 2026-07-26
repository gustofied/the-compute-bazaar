# Stage 1 System Quality Pass

## Objective

Treat the existing platform as one system before adding procurement,
execution, or another product layer:

```text
hourly observation
  -> immutable provider and catalog evidence
  -> normalized GPU, VM, sandbox, and workload data
  -> Curia/DataFusion gold products
  -> internal operator
  -> public-safe article payload
```

The review focused on integration, operational truth, lineage, and responsive
inspection rather than source-count expansion.

## What The Audit Found

The production pipeline already built both GPU gold and a substantial
sandbox/VM/workload gold product. The public article consumed both, but the
internal operator registered only the GPU manifest. This made the system look
smaller internally than it was and forced sandbox inspection back toward
payload or file-level debugging.

The public article had a second mismatch: local previews preferred the
checked-in fallback `sandbox-cost.json`, while production preferred the
CloudFront feed. A local page could therefore look stale even when the hourly
pipeline was current.

The hourly cadence was checked against retained S3 market-run manifests from
25 July 00:00 UTC through 26 July 10:00 UTC:

```text
expected hourly slots       35
observed hourly slots       35
missing slots                0
representative successes    24
representative warnings     11
representative errors        0
```

Several hours also contained explicit manual runs. They remain separate
immutable observations rather than overwriting scheduled history. Four
representative hours had a transient Clore failure and one had an Oracle GPU
catalog failure. Six warning runs had no source failure; those warnings came
from declared benchmark coverage or normalization quality rules rather than a
broken publication loop.

At the end of the audit, the current run had 17 of 18 configured sources,
1,927 gold GPU listings, 223 GPU index rows, four frontier benchmark values,
seven exact-shape VM offers, eleven reviewed managed-sandbox rates, and the
retained StarSling workload product. Oracle's public catalog returned repeated
502 responses and remained explicitly unavailable instead of being silently
reported as fresh.

The next scheduled 11:00 UTC run recovered without intervention: all 18 source
paths completed, gold contained 1,912 GPU listings and 224 index rows, and the
public payload advanced to the new generation. This confirmed both partial-run
isolation and normal recovery on the next observation cycle.

## Decisions

### One composed read-only operator catalog

The operator now composes the latest GPU and sandbox/VM gold manifests. It does
not merge the underlying product contracts or rewrite either manifest. The
composition supplies table refs and row counts to one bounded DataFusion
runner while keeping component manifest refs available for lineage.

Scratch SQL can read every table declared by those controlled gold manifests.
It is not limited to `fact_*` and `dim_*` names because workload tables and
future reviewed qualitative objects can also be legitimate gold products.
Writes, multiple statements, and external file readers remain rejected.

### Named comparison views, not frontend formulas

Two versioned queries were added:

```text
compute_price_cross_section:v0
sandbox_workload_costs:v0
```

The price cross-section keeps GPU dollars per GPU-hour, VM dollars per VM-hour,
and sandbox dollars per sandbox-hour explicit. It also retains requested shape,
price basis, observed time, methodology, and source URL. It is an inspection
view, not a composite index.

The workload view reads the materialized StarSling gold summary and exposes
measured runtime, estimated processor-and-memory cost, interquartile ranges,
completion, source run, and methodology. Neither calculation moved into
JavaScript.

### Component-aware lineage

GPU rows trace through GPU provider manifests. Sandbox rows trace through the
sandbox bronze, silver, and gold manifest chain without inventing GPU provider
runs. Cross-section rows can show both component chains. The selected gold
context now identifies the component and its exact manifest ref(s).

### Remote-first article preview

The AdamSioud article now tries the configured CloudFront publication feed
before its checked-in fallback in both production and local preview. The
fallback remains useful when offline, but it no longer silently hides a
healthy current feed during local review.

## Verification Notes

The live composed catalog registered 33 current gold tables: ten GPU tables and
twenty-three VM/sandbox/workload tables. Both new queries executed through
DataFusion against S3. The cross-section returned four GPU benchmark rows,
seven exact-shape VM rows, and eleven managed-sandbox rows. The workload query
returned all six current services.

Focused tests cover:

- composed GPU and sandbox manifests;
- availability of both new catalog queries;
- DataFusion execution against all three price layers;
- scratch SQL over a non-`fact_*` sandbox gold table;
- sandbox lineage and component manifest selection;
- continued rejection of writes, multiple statements, and external readers.

Final checks:

```text
complete unittest suite                 92 passed
focused Ruff checks                     passed
operator and article JavaScript syntax  passed
canonical sandbox evidence              valid
public sandbox payload                  current, no partial VM runs
live Stage 1 check                       ok
```

The local Stage 1 command skipped private AutoMQ connectivity and Windmill API
inspection because the laptop was outside the VPC tunnel and had no
`WINDMILL_BASE_URL` or token in that process. AutoMQ publishing and the
schedule were still evidenced by the successful market manifests and the
complete 35-of-35 hourly cadence audit.

Browser QA covered:

- operator at 1280 by 720 with four run/product summary cells, nine named
  queries, bounded tables, and no page overflow;
- operator at 390 by 844 with a horizontal query selector, collapsed 33-table
  allowlist, and no page overflow;
- sandbox workload row drill-down to the correct sandbox build manifest and
  bronze/silver refs;
- article at 390 by 844 for the GPU header, market pulse, VM/sandbox price
  card, workload cost card, relative price card, and occupancy section;
- horizontal tables remained inside explicit scrolling wrappers;
- keyboard chart inspection exposed an exact observation and kept its tooltip
  within the card;
- local article data resolved to the same current CloudFront generation as
  production, with no pending values.

## Maintenance

For the next system review:

1. Read the latest market-run, GPU gold, and sandbox gold manifests.
2. Check hourly slots separately from manual reruns.
3. Distinguish source failure from data-quality warning.
4. Run the two cross-product catalog queries through CLI and `/operator/`.
5. Confirm local and production article pages resolve the same publication
   timestamp.
6. Validate desktop and narrow viewports, row lineage, source links, and
   horizontal overflow.

Do not make the public article the data warehouse. Keep the lake as durable
memory, the composed operator as the full inspection surface, and the article
as a deliberate story.
