# Transactions

**Question: Can an agent turn messy compute-deal material into accurate work without losing the terms that control the transaction?**

Transactions follows one synthetic reserved-capacity opportunity through three pieces of work:

```text
buyer intent -> diligence room -> capacity agreement
normalize    -> organize       -> compare
```

| Task | Work | Deliverable |
| --- | --- | --- |
| [`normalize-buyer-mandate`](normalize-buyer-mandate/) | Reconcile a buyer's intake documents and open questions | Buyer mandate brief |
| [`draft-capacity-data-room-population-plan`](draft-capacity-data-room-population-plan/) | Decide what belongs in the room, who owns it, and when it should arrive | Data-room population plan |
| [`compare-capacity-agreement-against-term-sheet`](compare-capacity-agreement-against-term-sheet/) | Find where the draft agreement departs from the agreed terms | Agreement deviation report |

## Results

OpenCode 1.18.11 ran each model five times on each task. The comparison retained 43 scored documents: 15 from DeepSeek, 14 from GPT-5.6 Luna, and 14 from GLM 5.2.

| Model | Scored | Every requirement met | Checklist coverage | Intake | Diligence | Contracting |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 15/15 | 1/15 | 84.3% | 78.9% | 94.3% | 80.6% |
| GPT-5.6 Luna | 14/15 | 1/14 | 90.0% | 90.7% | 96.7% | 84.8% |
| GLM 5.2 | 14/15 | 0/14 | 92.4% | 87.1% | 96.6% | 94.0% |

| Model | Median agent / end-to-end time | Median input / cached / output tokens | Reported cost |
| --- | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 328.6s / 446.5s | 160.1k / 131.6k / 8.7k | - |
| GPT-5.6 Luna | 118.2s / 257.9s | 271.1k / 271.1k / 7.2k | - |
| GLM 5.2 | 243.9s / 371.5s | 151.5k / 126.9k / 11.6k | - |

Harbor did not report agent or Modal cost for these runs. Applying the final
checklist used $8.854735 across 129 GPT-5.4 judge batches; that cost was recorded
for the comparison as a whole and cannot be split reliably by model.

## What Happened

Diligence was the strongest task for every model, helped by a structured
evidence register and explicit operator instructions. Contracting separated the
models most clearly: GLM reached 94.0% checklist coverage, compared with 84.8%
for Luna and 80.6% for DeepSeek. Luna was fastest and strongest on buyer intake.

Only two of the 43 scored documents met every requirement. Document production
was a separate weakness: only one DOCX passed every quality check, and none of
the scored trajectories showed the agent rendering its finished document before
submission. High checklist coverage did not reliably produce a clean, usable
work product.

The same final checklist was applied to all 43 saved documents; the agents were
not rerun. One Luna attempt reached the one-hour timeout and one GLM attempt
ended on an upstream 504, so neither was scored. These are five unseeded attempts
per task across one linked synthetic transaction. They describe these
model-and-harness runs rather than a broad model ranking.

## How It Grades

Each task requires one named DOCX file. The grader first checks that the file exists and is a valid document. It then checks the work against the source material and the task's requirements. The main score is the share of checklist items passed. A complete pass requires every item to pass.

Document quality is reviewed separately so a factually strong answer does not receive extra credit merely for looking polished, and a well-designed document cannot hide missing work.

## Source

The task forms come from [Harvey's Legal Agent Benchmark](https://www.harvey.ai/blog/introducing-harveys-legal-agent-benchmark), but the matter itself is an original synthetic compute transaction.

| Compute task | Harvey task form |
| --- | --- |
| Buyer mandate | [Extract disorganized client-intake facts](https://hub.harborframework.com/tasks/punitarani/trusts-estates-private-client-extract-client-intake-facts-scenario-01/latest) |
| Data-room plan | [Draft sell-side data-room population plan](https://hub.harborframework.com/tasks/punitarani/corporate-ma-draft-data-room-population-plan-scenario-01/latest) |
| Agreement comparison | [Compare PPA against term sheet](https://hub.harborframework.com/tasks/punitarani/energy-natural-resources-compare-power-purchase-agreement-against-term-sheet/latest) |

Each adaptation keeps the source documents, requested deliverable, hidden issues, and detailed checks of the original task form while replacing the legal matter with compute-deal work across buyer intake, diligence, and contracting.
