# Transactions v1: Mistral Medium 3.5

The first local `transactions` baseline ran five fresh attempts on each of the
three CB-2026-041 checkpoints with OpenCode 1.18.11, Mistral Medium 3.5, and a
frozen GPT-5.4 judge.

## Results

| Task | Valid | Mean semantic | Median | Range | All pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| `normalize-buyer-mandate` | 5/5 | 0.7857 | 0.7679 | 0.7321-0.8393 | 0/5 |
| `draft-capacity-data-room-population-plan` | 5/5 | 0.6792 | 0.6226 | 0.5283-0.9245 | 0/5 |
| `compare-capacity-agreement-against-term-sheet` | 5/5 | 0.5871 | 0.5806 | 0.5323-0.6613 | 0/5 |

Equal-task macro semantic score: `0.6840`. Pooled semantic criteria:
`582/855` (`0.6807`). Semantic scores exclude output integrity.

## What It Shows

- Mandate normalization was strongest, but every attempt missed the exact
  staged-ramp GPU-hour and cost calculation.
- The data-room plan was volatile. Agents repeatedly missed the site-option
  deadline and a concrete consent tracker.
- Agreement comparison was hardest. Exact arithmetic, measurable remedies,
  preserved negotiated terms, and open execution risks were common misses.
- Every required DOCX was valid, but none passed every criterion.

## Document Craft

| Task | Good | Mixed | Poor | Pages |
| --- | ---: | ---: | ---: | ---: |
| `normalize-buyer-mandate` | 5 | 0 | 0 | 4-8 |
| `draft-capacity-data-room-population-plan` | 2 | 0 | 3 | 12-27 |
| `compare-capacity-agreement-against-term-sheet` | 2 | 2 | 1 | 5-11 |

The highest-scoring data-room plan was also the least usable document: 27 pages
of wide matrices compressed into narrow, fragmented columns. Semantic reward
and document craft therefore remain separate. The page-level ratings are in the
[visual review](transactions-v1-mistral-medium.visual-review.json).

## Run Record

`transactions-v1-mistral-medium-002` is the sole scored job. An earlier
restricted-network preflight, `transactions-v1-mistral-medium-001`, stopped
before agent execution and is excluded.

The dated [commitment](../protocols/transactions-v1-mistral-medium.commitment.json)
predates the official Harbor lock and pins the exact task digests. It was not
Git-committed before execution, so this is a locally predeclared baseline, not a
Git-precommitted release. The post-run facts are in the
[run record](../protocols/transactions-v1-mistral-medium.run.json).

The five attempts per task had no controlled sampling seed. Each semantic
criterion received one frozen judge evaluation across three batches per
submission. The run measures observed rollout and judge variation on one
synthetic transaction, not independent matter performance or a broad model
ranking.

All 15 agents used `python-docx`; none rendered its output before submission.
Twelve recovered from at least one command or document-generation error. Agent
inference, 45 GPT-5.4 judge calls, and Modal compute were not dollar-reconciled.

The local report was produced with the tracked
[analyzer](../evaluator/analysis.py). Raw jobs, rendered pages, and detailed
reports remain local.
