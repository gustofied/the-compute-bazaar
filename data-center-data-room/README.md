# Data Center Data Room

`data-center-data-room` is an early Compute Bazaar section for Prime-style evals and training
around messy private compute/data-center deal rooms.

The basic task: give an agent a deal room, then score whether it can turn the evidence into useful
deal work.

Initial outputs to evaluate:

- deal memo
- structured deal record
- missing-diligence checklist
- source citations
- next recommended action

Initial skills to score:

- extracting terms from messages, docs, spreadsheets, and quote sheets
- verifying capacity, power, network, SLA, pricing, and timing claims
- comparing terms against Compute Bazaar market evidence
- preserving private buyer/seller context
- updating deal state correctly

Build order:

1. Synthetic taskset with hidden ground truth.
2. Deterministic verifier and rubric.
3. Prime eval runs.
4. Prime training runs once the reward is stable.

Future implementation can live under this folder, for example as `env/`, once the Prime package
shape is clear.

