# Transactions adjudication replay

Gate 1 prepares a corrected verifier for the 43 retained Transactions outputs. It does not rerun an agent or change the original Harbor jobs.

- `verifier-v2/` contains the corrected verifier packages and criterion-to-source ledgers.
- `visible-surface-equivalence.json` proves the instruction, matter, tools, output contract, and deterministic integrity checks are unchanged.
- `adjudication-replay-001.commitment.json` freezes the 43 source artifacts and their original scores.
- `adjudication-replay-001.modal-amendment.json` records Adam's pre-execution instruction to replace the Gate 1 Docker runtime with Modal.
- `replay.py` validates the frozen inputs and runs corrected verifiers in Modal sandboxes.
- `analyze_replay.py` keeps original and amended scores adjacent without rewriting Harbor history.

The two score labels are:

- **Original frozen Harbor score (verifier v1)**
- **Amended adjudicated score (verifier v2 replay; preserved outputs; no agent rerun)**

Validate Gate 1 without inference:

```bash
uv run python compute-bazaar-bench/evals/transactions/adjudication/replay.py --validate-only
```

Run the no-inference Modal preflight:

```bash
/Users/adams/.local/share/uv/tools/harbor/bin/python compute-bazaar-bench/evals/transactions/adjudication/replay.py --modal-preflight --preflight-id modal-preflight-004
```

Record the live OpenRouter reserve check without calling the judge:

```bash
/Users/adams/.local/share/uv/tools/harbor/bin/python compute-bazaar-bench/evals/transactions/adjudication/replay.py --balance-check
```

Gate 2 is deliberately guarded because the initial attempt makes 129 expected GPT-5.4 judge calls:

```bash
/Users/adams/.local/share/uv/tools/harbor/bin/python compute-bazaar-bench/evals/transactions/adjudication/replay.py --execute --backend modal --acknowledge-paid-judge
```

If the process stops between records, keep the attempt directory and resume it. Final record checkpoints are reused; an interrupted in-flight record blocks automatic replay for manual review.

```bash
/Users/adams/.local/share/uv/tools/harbor/bin/python compute-bazaar-bench/evals/transactions/adjudication/replay.py --execute --backend modal --acknowledge-paid-judge --resume-attempt
```

If an infrastructure grade fails, preserve `attempt-001` and retry only its failed records:

```bash
/Users/adams/.local/share/uv/tools/harbor/bin/python compute-bazaar-bench/evals/transactions/adjudication/replay.py --execute --backend modal --acknowledge-paid-judge --attempt-id attempt-002 --retry-from compute-bazaar-bench/jobs/adjudications/transactions-comparison-v1-adjudication-replay-001/attempt-001/adjudication-run.json
```

Build the v1/v2 comparison after a complete replay:

```bash
/Users/adams/.local/share/uv/tools/harbor/bin/python compute-bazaar-bench/evals/transactions/adjudication/analyze_replay.py
```
