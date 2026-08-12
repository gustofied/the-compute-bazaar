# Tooling

Supporting code used to run the same Harbor environment across fixed seeds,
compare agents, and inspect the results. The environment and its grader remain
entirely inside [`harbor/`](../harbor/).

Build the normalized comparison consumed by Terminal:

```bash
.venv/bin/python compute-bazaar-bench/evals/reliability-is-blind/tooling/build_comparison.py
```
