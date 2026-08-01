# Sandbox Source Audit

## Decision

The checked-in StarSling evidence is the reviewed fallback and reproducibility
record for the recurring sandbox benchmark. A source check found six new
compatible provider batches at upstream commit
`6da0dce9d1c37fa2d45517f63c02591292075d20`. They were promoted without
rewriting any prior observation.

The shape gate continued to reject source runs `29130741476`, `29346212440`,
`29365910084`, `29472826358`, and `29546060837` because they requested two
vCPUs rather than the maintained four-processor, 8 GiB, 40 GB comparison
shape. Rejected runs remain represented by commit-pinned source provenance;
they do not enter silver or gold.

## Canonical Record

The reviewed evidence now contains:

```text
source runs          11
calendar days         8
provider batches     62
complete jobs       353
phase rows         3,530
services              6
harness methods       10
latest run   30655876610
```

Repeated intraday runs remain separate. The latest source run contains 72
complete jobs and 720 aligned phase rows, so the current headline comparison
is unchanged in shape while the historical audit record grows.

## Refresh

Review upstream changes without modifying canonical evidence:

```sh
uv run sandbox-cost refresh-benchmark \
  --output-root /tmp/compute-bazaar-sandbox-review \
  --source-ref main \
  --check
```

After reviewing the immutable commit, matching shape, task signature, and
reported new rows, promote that exact commit with `--update-evidence`. Then run
`uv run sandbox-cost validate`, the focused sandbox tests, and a second
`refresh-benchmark --check`. The second check must report `changed: false`.

The public article is
`https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html`; the
`exemplars/compute-bazaar/` path is retained only as the operator workhouse.

## Draft Retirement

The old `external/AdamSioud/draft/` GPU price-tape page, CSV, JavaScript, and
vendored D3 copy were unlinked, marked `noindex`, and no longer participated in
the pipeline. They were removed after confirming that the maintained GPU data,
card renderer, source links, and publication behavior are all present in the
main Compute article and recurring Gold export. Git history remains the audit
record for the superseded draft.
