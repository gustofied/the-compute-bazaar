# deal-room

`deal-room` is the first family in `compute-bazaar-bench`: static agent tasks
around messy private compute deals.

The basic task is to give an agent a closed deal room and score whether it can
turn the evidence into useful, reviewable deal work.

The first Harbor task is
[`assess-commercial-fit`](../evals/compute-bazaar-bench/deal-room-assess-commercial-fit/README.md).
It asks an agent to reconcile a buyer mandate with a private GPU offer, identify
the controlling gaps, and recommend whether to proceed, negotiate, pause, or
reject.

Outputs to evaluate:

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

1. One synthetic Harbor task with hidden ground truth.
2. Oracle and real-agent trace audit.
3. A small set of distinct Deal Room tasks over the same opportunity.
4. A versioned Harbor dataset and model/harness comparisons.
5. Verifiers/Prime environments and training only after the reward contract is
   stable.

Harbor source lives under
[`evals/compute-bazaar-bench`](../evals/compute-bazaar-bench/README.md).
