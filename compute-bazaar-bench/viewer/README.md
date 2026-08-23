# Evaluation Viewer

The Eval viewer puts Harbor tasks, jobs, and reports in one place.

- **Tasks** are evals ready to run.
- **Jobs** are completed or running Harbor jobs.
- **Tourneys** are saved comparisons across the same tasks or matched market
  seeds.
- **Attempts** link back to each Harbor trial.

The viewer reads:

```text
evals/**/task.toml             tasks
jobs/*                         jobs and trials
jobs/reports/*                 reviewed metrics and notes
evals/**/*.comparison.json     Tourneys
```

A task appears before its first run. A job appears as soon as Harbor writes its
files. Reports can add reviewed metrics and notes. Older runs under
`jobs/raw/*` remain readable.

Tourneys must be created explicitly. Their comparison file names the tasks,
agent setups, metrics, attempts, and source jobs. The viewer checks that file
and displays it. Job names never create a Tourney, and unrelated benchmarks are
never folded into one score.

Each Tourney shows its main metric, supporting measures, results by task and
agent, run counts, time and token use, and links to every attempt. You can also
select two Harbor jobs from the same task for a quick reward comparison.

Reviewed reports live under:

```text
compute-bazaar-bench/jobs/reports/<task>/runs/<job>/
```

Open the Terminal and choose **Eval**:

```bash
compute-bazaar terminal
```
