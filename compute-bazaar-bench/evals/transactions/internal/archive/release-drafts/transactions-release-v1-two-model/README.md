# Transactions release v1

This release compares Mistral Small 2603 and GLM 5.2 on the three canonical Transactions tasks. Each model receives five attempts per task through OpenCode 1.18.11 in Modal, with no retries and the frozen GPT-5.4 release grader.

The protocol is frozen. The first spend gate is blocked, so no Oracle grading, model preflight, or official release job has started.

After funding, run the live gate first:

```bash
.venv/bin/python compute-bazaar-bench/evals/transactions/releases/transactions-release-v1/check_spend.py
```
