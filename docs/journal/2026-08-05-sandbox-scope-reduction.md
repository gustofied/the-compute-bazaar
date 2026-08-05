# Sandbox Scope Reduction

## Decision

The managed-sandbox work now has one active economic product: estimated cost of
the latest compatible StarSling HPC Sandbox Benchmark job. The fixed vendor
rate-card history and the GPU/VM/sandbox common-start chart have been retired
from the public surface.

## Why

The old `hourly-price-observations.json` contained 33 manually researched public
and archived quotes across 11 services. “Hourly” described the billing unit,
not a collection cadence. Treating those sparse quotes as a continuously moving
market series overstated the evidence.

The StarSling dataset is stronger for the narrower question because it measures
the same pinned software workload across compatible services. Its runs are
manually initiated upstream and irregular. Runtime is multiplied by the reviewed
processor-and-memory rate applicable to each service to estimate job cost.

## Changes

- Archived the 33 sandbox-price observations under `archive/sandbox-prices/`.
- Retained one documented cost input per benchmark service in
  `workload-cost-inputs.json`.
- Removed rate-card and common-start JSON from the public build contract.
- Removed the retired VM-capacity collectors and their CLI commands.
- Removed the unreachable legacy rate-card, utilization, VM, and cross-market
  branches from the active pipeline module.
- Removed the unused rate-card and relative-price public-view builders.
- Moved all six measured-workload Gold transformations from Python strings into
  the packaged SQL model registry.
- Removed the parallel `sandbox-cost query` interface; measured workload data
  is queried through the shared DataFusion operator catalog.
- Reduced the article to one “Measured Workload Cost” card.
- Reduced publication output to one latest-run cost image and page.
- Added explicit StarSling credit and source links to the public payload.

## Formula And Caveat

```text
estimated job cost = runtime seconds / 3600 * processor-and-memory hourly rate
```

The estimate excludes lifecycle and non-compute charges. It is not an invoice,
an executed price, or a live sandbox market index.

## Next Refresh

Run `uv run sandbox-cost refresh-benchmark --check`. If StarSling has published
a compatible run, review the source diff, then use `--update-evidence
--publish-operational`. Review service price pages separately before changing a
cost input.

## Verification

The reduced path was rebuilt from canonical evidence into a temporary local
Bronze/Silver/Gold estate. It produced 80 batch rows, 14 compatible run rows,
72 latest job rows, 720 latest phase rows, 60 phase summaries, and six service
summaries. The `workload-summary` query ran through DataFusion, the four
hermetic project tests passed, Ruff passed, and the built wheel retained every
packaged SQL model and saved query.
