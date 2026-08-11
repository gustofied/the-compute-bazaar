# Transactions Results

Three models completed the same buyer-intake, diligence, and agreement-review tasks through OpenCode 1.18.11. Each model had five attempts per task.

## Results

| Model | Scored | Every requirement met | Checklist coverage | Average across tasks | Document quality | Median agent time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 15/15 | 1/15 | 721/855 (84.3%) | 84.6% | 0 / 10 / 5 | 328.6s |
| GPT-5.6 Luna | 14/15 | 1/14 | 722/802 (90.0%) | 90.8% | 1 / 6 / 7 | 118.2s |
| GLM 5.2 | 14/15 | 0/14 | 733/793 (92.4%) | 92.6% | 0 / 9 / 5 | 243.9s |

Document quality is shown as good / mixed / poor.

## By Task

| Model | Buyer mandate | Data-room plan | Agreement comparison |
| --- | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 78.9% | 94.3% | 80.6% |
| GPT-5.6 Luna | 90.7% | 96.7% | 84.8% |
| GLM 5.2 | 87.1% | 96.6% | 94.0% |

## What Happened

Diligence was the strongest task for every model. The structured evidence register and explicit operator instructions gave the agents a clearer path through the work.

The agreement comparison separated the models most clearly. GLM found 94.0% of the required work, compared with 84.8% for Luna and 80.6% for DeepSeek.

Only two of 43 scored documents met every requirement. Document production was a separate weakness: only one DOCX passed every quality check, 25 needed some layout work, and 17 had at least one critical presentation problem. None of the scored trajectories showed the agent rendering its finished document before submission.

## How To Read This

- **Checklist coverage** is the share of required items found in the submitted work.
- **Every requirement met** is deliberately strict: one missed item makes the attempt incomplete.
- **Document quality** is reviewed separately and does not change the checklist score.
- One Luna attempt reached the frozen one-hour timeout and one GLM attempt ended on an upstream 504. Neither attempt is scored.

During review, we corrected several checklist items and applied the same final checklist to all 43 saved documents. The agents were not rerun.

This is one linked synthetic transaction with five unseeded attempts per task. It describes these model-and-harness runs; it does not establish a broad model ranking or general compute-market competence.
