# Evaluation Viewer

The viewer keeps four things separate:

- **Tasks** are the authored evaluation packages.
- **Jobs** are Harbor execution records.
- **Tourneys** compare agents across the same tasks or market seeds.
- **Attempts** preserve the path back to each Harbor trial.

It reads three sources:

```text
evals/**/task.toml  authored tasks
jobs/*              Harbor jobs and trials
jobs/reports/*      optional analysis and notes
evals/**/*.comparison.json  normalized comparisons
```

The viewer also reads the former `jobs/raw/*` layout so preserved runs remain
available without rewriting their files.

Tasks appear before their first run. Harbor jobs appear as soon as they write
their standard files. Reports may add reviewed metrics and observations, but do
not determine whether a job exists.

Tourneys are opt in. Benchmark tooling converts their frozen jobs and
reports into a complete `evals/**/*.comparison.json` artifact. The artifact
declares the tasks, agents, metrics, denominators, attempts, and source records.
The viewer validates and renders that shared schema; it contains no
benchmark-specific score adapter. Ordinary job names never create a comparison.

Two or more raw Harbor jobs for the same task can also be selected for a direct,
temporary comparison. That view reports Harbor reward and does not infer a pass
rule.

Every tourney page shows:

1. the benchmark's declared primary metric;
2. supporting measures without blending them into the headline;
3. task-by-agent results;
4. planned, scored, invalid, and excluded denominators where available;
5. descriptive time and token telemetry; and
6. every attempt with a link to its trial record.

Transactions and Reliability Is Blind keep their own outcome definitions in
their generators. The viewer does not create one synthetic score across unlike
tasks.

Eval-specific reports live under:

```text
compute-bazaar-bench/jobs/reports/<task>/runs/<job>/
```

```bash
compute-bazaar terminal
```

Choose **Eval**.
