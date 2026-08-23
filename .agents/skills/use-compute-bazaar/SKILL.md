---
name: use-compute-bazaar
description: Use The Compute Bazaar CLI and running Terminal to inspect market data, open results, operate Fleet, or work with Eval. Use for Bazaar data, Terminal navigation, GPU offers, Fleet hosts, and market analysis.
---

# Use The Compute Bazaar

Work through the `compute-bazaar` CLI. The Terminal is a visible surface for the
same commands, not a separate system.

Inside this checkout, invoke it as `.venv/bin/compute-bazaar`. Do not use a
global installation from another checkout.

## Inspect and analyse

- Discover data with `compute-bazaar tables` and `compute-bazaar describe TABLE`.
- Query with bounded read-only SQL: `compute-bazaar sql "SELECT ..."`.
- Run a saved query with `compute-bazaar query QUERY_ID`.
- Add `--terminal` to a query or SQL command when the result should open in Data.
- Build a view from SQL with `--chart table|line|bar|area`, `--x COLUMN`,
  `--y COLUMN`, and optional `--series COLUMN`.
- For any other Perspective plugin or setting, pass its complete view config as
  JSON with `--perspective '{...}'`. Do not replace a requested Perspective view
  with a simpler chart.
- Chart SQL must return one row for each x/series pair. Aggregate repeated
  observations in SQL first; never let Perspective sum prices or rates by default.
- Honor the requested date range and chart type. Build a fresh SQL result when a
  saved view does not match instead of substituting a nearby view.
- Use Bazaar data before searching the web unless the user explicitly asks for
  outside research.

## Move the running Terminal

Use `compute-bazaar open data`, `fleet`, `eval`, or `terminal`.

Never run `compute-bazaar terminal` merely to change the visible workspace. That
command starts or focuses the app; `compute-bazaar open` controls the instance
that is already running.

Never stop or restart the running Terminal to display a result. `--terminal` and
`compute-bazaar open` hand work to the open instance.

## Access

Read access permits inspection, SELECT/WITH SQL, saved queries, and Terminal
navigation. Full access is required for edits, refreshes, publication, paid
provisioning, termination, and workload changes.

Use `compute-bazaar COMMAND --help` before guessing an unfamiliar command. Keep
responses in the Terminal short; put useful tabular or chart results in Data.
