# Sandbox Source Refresh: 5 August 2026

## Trigger

The scheduled `sandbox-cost-sources` workflow stopped at its review gate after
StarSling published three compatible Better Auth benchmark runs. This was the
intended behavior: new source observations must not silently change canonical
workload history.

## Source Audit

Reviewed source commit:

`398c60d74e0b29bcb2abfe61a8b8a6428185c00f`

New source runs:

- `30691551759`, generated 1 August 2026;
- `30730328892`, generated 2 August 2026;
- `30960125032`, generated 5 August 2026.

All three retain the accepted 4 vCPU, 8 GiB memory, 40 GiB disk shape, Better
Auth app commit, ten-task signature, six-service comparison, twelve upstream
replicates per service, and lifecycle exclusion. The upstream dataset schema is
still version 1. The only methodology-document change between the reviewed
commits explains the separate smoke workflow; it does not alter the published
benchmark calculation.

The upstream repository added providers and changed toolchain internals during
the same commit range. Those changes are not admitted merely because they exist:
the extractor selected only rows matching the pinned shape and workload
signature. Earlier 2-vCPU runs remain rejected in bronze.

## Promotion

The reviewed runs were promoted with:

```bash
uv run sandbox-cost refresh-benchmark \
  --output-root data/sandbox-cost \
  --source-ref 398c60d74e0b29bcb2abfe61a8b8a6428185c00f \
  --update-evidence
```

The canonical evidence now contains:

```text
14 compatible source runs over 11 calendar days
80 provider-batch summaries
569 complete individual jobs
5,690 retained phase samples
6 fixed service variants
```

Ten runs contain the complete six-service cohort. Four incomplete runs remain
available for audit and are excluded from the article's complete-cohort history.
Repeated intraday runs remain separate and no missing job is imputed.

## Verification

`uv run sandbox-cost validate` passed after promotion. A local Gold build wrote
`sandbox-cost-1d60c1560dbf059e` with fourteen run-history rows, eighty batch rows,
seventy-two latest jobs, and seven hundred twenty latest phase rows. The next
worker deployment and hourly market run must carry this evidence into the S3
Gold generation and public sandbox payload.
