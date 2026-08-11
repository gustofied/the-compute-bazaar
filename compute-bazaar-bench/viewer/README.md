# Evaluation Viewer

The viewer reads three sources:

```text
evals/**/task.toml  authored tasks
jobs/*              Harbor jobs and trials
jobs/reports/*      optional analysis and notes
```

The viewer also reads the former `jobs/raw/*` layout so preserved runs remain
available without rewriting their files.

Tasks appear before their first run. Harbor jobs appear as soon as they write
their standard job files. Reports add reviewed metrics and observations; they do
not determine whether a job exists.

Comparison charts are opt in. A file under
`evals/**/comparisons/*.comparison.json` names the result set and its source.
Ordinary Harbor jobs remain in the Jobs list.

Eval-specific reports live under:

```text
compute-bazaar-bench/jobs/reports/<task>/runs/<job>/
```

```bash
compute-bazaar terminal
```

Choose **Eval**.
