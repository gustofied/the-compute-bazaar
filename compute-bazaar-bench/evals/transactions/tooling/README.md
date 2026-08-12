# Tooling

Supporting code used to read Harbor jobs, compare agents, and review the
submitted documents. The environments and their graders remain entirely inside
the three task folders.

Build the normalized comparison consumed by Terminal:

```bash
.venv/bin/python compute-bazaar-bench/evals/transactions/tooling/build_comparison.py
```
