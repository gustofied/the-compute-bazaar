# transactions

`transactions` evaluates professional work that moves an OTC or
reserved-compute transaction from initial intent toward executable paper.

```text
messy intent -> organized evidence process -> controlled transaction paper
analyze      -> draft                      -> review
```

| Task | Stage | Harvey adaptation |
| --- | --- | --- |
| [`normalize-buyer-mandate`](normalize-buyer-mandate/README.md) | Intake | [Extract disorganized client-intake facts](https://hub.harborframework.com/tasks/punitarani/trusts-estates-private-client-extract-client-intake-facts-scenario-01/latest) |
| [`draft-capacity-data-room-population-plan`](draft-capacity-data-room-population-plan/README.md) | Diligence | [Draft sell-side data-room population plan](https://hub.harborframework.com/tasks/punitarani/corporate-ma-draft-data-room-population-plan-scenario-01/latest) |
| [`compare-capacity-agreement-against-term-sheet`](compare-capacity-agreement-against-term-sheet/README.md) | Contracting | [Compare PPA against term sheet](https://hub.harborframework.com/tasks/punitarani/energy-natural-resources-compare-power-purchase-agreement-against-term-sheet/latest) |

> Can an agent perform the professional work required to advance a compute
> transaction accurately, with evidence, and without losing the deal's
> controlling terms?

## v1

The first local baseline ran Mistral Medium 3.5 five times on each task:
`15/15` valid deliverables and a `0.6840` equal-task semantic score. See the
[results and notes](results/transactions-v1-mistral-medium.md).

## Adaptation Approach

The initial tasks are methodological adaptations, not legal tasks with a few
nouns replaced. Each one should preserve the source task's document roles,
instruction shape, deliverable, planted-issue structure, and rubric granularity
while introducing an original synthetic compute matter. This synthetic matter
is inspired by the likes of ComputeDesk and Epilogue, as well as my reading and
understanding of compute deals.
