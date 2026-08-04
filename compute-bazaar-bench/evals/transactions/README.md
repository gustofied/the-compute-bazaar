# transactions

`transactions` evaluates professional work that moves an OTC or
reserved-compute transaction from initial intent toward executable paper.

```text
compute-bazaar-bench/                 benchmark suite
`-- evals/
    `-- transactions/                 domain
        |-- normalize-buyer-mandate/
        |-- draft-capacity-data-room-population-plan/
        `-- compare-capacity-agreement-against-term-sheet/
```

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

## Adaptation Approach

The initial tasks are methodological adaptations, not legal tasks with a few
nouns replaced. Each one should preserve the source task's document roles,
instruction shape, deliverable, planted-issue structure, and rubric granularity
while introducing an original synthetic compute matter.

The source tasks should be pulled from
[Harvey LAB](https://github.com/harveyai/harvey-labs) at a pinned commit. The
[Harbor conversion](https://hub.harborframework.com/datasets/punitarani/harvey-labs/latest)
is the packaging and RewardKit reference. Upstream changes should be adopted
deliberately through versioned updates rather than synchronized automatically.

## Later Direction

These tasks freeze one transaction at three useful points. Later environments
can make the same deal state interactive: counterparties reply, terms move,
evidence arrives, inventory changes, and the agent must decide whether to ask,
update, escalate, negotiate, pause, or walk away.
