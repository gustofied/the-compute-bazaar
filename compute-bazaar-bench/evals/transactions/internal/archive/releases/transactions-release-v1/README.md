# Transactions release v1

This release adds a fresh Mistral Small 2603 Harbor run to the release-grader results already available for preserved DeepSeek, GPT-5.6 Luna, and GLM outputs. The table labels the two execution origins rather than presenting them as identical runs.

Mistral receives five attempts on each canonical Transactions task through OpenCode 1.18.11 in Modal. Oracle, route preflight, and official work run serially with no retries and live balance gates between stages.

Oracle `-002` rechecks only the two corrected private reference documents. The unchanged agreement-comparison task keeps its 62/62 pass from Oracle `-001`.

Run the entry gate before any paid work:

```bash
.venv/bin/python compute-bazaar-bench/evals/transactions/releases/transactions-release-v1/check_spend.py --stage entry
```
