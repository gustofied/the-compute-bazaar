# Evaluation Viewer

A private localhost viewer for Compute Bazaar evaluation jobs.

The viewer owns navigation, notes, metric cards, tables, and trial detail pages.
It does not know how a particular evaluation is scored. Evaluation analyzers adapt
their outputs into the typed contract in `schema.py`.

## Results

Store normalized reports under:

```text
compute-bazaar-bench/jobs/reports/<task>/runs/<job>/
```

A job can provide either:

- `view.json`: the generic `compute-bazaar.viewer.job.v1` presentation contract.
- `protocol.json` and `trials.json`: analyzer output handled by a presenter in
  `presenters.py`.

`notes.json` is written locally by the viewer. Raw Harbor jobs, protected truth,
and verifier behavior remain outside the viewer contract.

## Open

```bash
compute-bazaar terminal
```

Choose **Eval** from the terminal menu. The terminal only binds to localhost
because reports may contain private diagnostics.
