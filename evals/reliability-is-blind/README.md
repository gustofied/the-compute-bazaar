# Reliability Is Blind

**Question: Large compute deals are often negotiated through OTC desks and multi-party supply chains with limited shared visibility. Can an agent acting as a broker still meet the SLAs promised to buyers when failures are difficult to attribute?**

Based on [_Reliability Is Blind_](https://arxiv.org/abs/2503.19055) and its [reference implementation](https://github.com/RedChainLab/Reliability-Is-Blind-Collective-Incentives).

A rolling procurement game for data-center capacity. One rollout represents a broker’s book of compute deals, and each step represents one completed deal. The broker selects the assets that will fulfil it, and the environment resolves whether the deal ultimately met or breached its agreed SLA. The fixed reliability target applies across the broker’s book: a 5% target means no more than 5% of deals should end in an SLA breach.

I built and evaluated the game as a Harbor task. I then ran the same Harbor task through Verifiers for a training run with model X. Alongside evaluating the agent’s performance in the game, I study which supply the broker explores, how it responds to failures, when it returns to reliable routes, and when it stops using weak ones. A little behavioral analysis.

In the original simulation, observability in a decentralized compute marketplace is limited because assets remain independently owned and may operate through confidential execution. Several assets are matched to execute each task. These assets can include an application, dataset, model, and server. The marketplace knows which assets participated and whether the task succeeded, but cannot identify which asset, or combination of assets, caused a failure.

Rewards and penalties are calibrated to a reliability target. Across repeated tasks, failure-prone assets tend to lose their stake and eligibility, while reliable assets remain available.

Similarly, observability is limited in OTC compute markets, but for different reasons. Supply passes through brokers and resellers, while inventory owners, counterparties, facilities, cluster operators, network providers, and hardware providers may all be separate parties. The buyer may know that the deal failed to deliver without knowing where the fulfilment chain broke down.

In this environment, the paper’s automatic asset-selection rules become decisions made by the broker. For each new deal, the broker assembles a fulfilment route from the available supply. The broker is not asked to identify which asset failed. It must decide which route is most likely to deliver the next deal from incomplete outcome signals.

The original paper and code are by Henry Mont, Matthieu Bettinger, Sonia Ben Mokhtar, and Anthony Simonet-Boulogne and are licensed under [CC BY 4.0](https://github.com/RedChainLab/Reliability-Is-Blind-Collective-Incentives/blob/main/LICENSE).

## Environment

One Harbor trial runs one rollout. Each rollout contains a sequence of steps, and each step represents one complete compute deal. The deal’s delivery period is compressed into one final outcome: SLA met or SLA breached.

Each asset represents a capacity allocation offered through the market. It has a public stake, which serves as its reputation signal, and a hidden reliability. Any four eligible assets can be bundled to fulfil a deal in the first version.

1. A new compute deal arrives and requires four compute-capacity assets from the eligible supply pool.
2. The broker observes the eligible supply and each asset’s public stake, together with prior fulfilment routes and their collective outcomes.
3. The broker selects the four assets that will form the deal’s fulfilment route.
4. The environment resolves the deal as a successful or failed delivery.
5. The selected assets are collectively rewarded or penalized without revealing which asset caused a failure.
6. Their updated stakes, any removals, and scheduled arrivals determine the eligible supply presented to the broker before the next deal.

### Actions

The broker selects exactly four distinct eligible asset IDs. A valid selection advances the market by one deal; the broker cannot abstain.

Invalid, duplicate, or ineligible selections return an error without advancing the market or resolving a deal. Repeated invalid actions are limited.

Status and history queries are read-only and do not advance the market.

### How it grades

**Deal succeeds:**

- Each selected asset gains `+R` stake, up to the configured maximum.
- The broker receives `+R` reward.

**Deal fails:**

- Each selected asset loses `P` stake.
- Any asset that reaches the ruin threshold becomes ineligible.
- The broker receives `-P` reward.

The asset updates create the supply state for the next deal. The broker reward grades the decision it just made.

For a 5% SLA target, the paper’s calibration could be:

- Success: `+0.0526`
- Failure: `-1`

Across 100 deals, 95 successes and 5 failures produce roughly zero total reward. Doing better than the SLA gives positive reward; doing worse gives negative reward.

At rollout end:

- **Broker reward:** the mean reward across all deals. This is the Harbor reward and later the Verifiers/Prime RL training signal.
- **SLA result:** the overall delivery success rate and whether it met the agreed target.
- **Supply state:** the final public stakes and eligible supply pool.

## Building the environment

How I converted _Reliability Is Blind_ into a Harbor environment for compute deals:

- The paper assumes only two trustworthy facts: who was involved and whether the task worked. In this environment, that becomes the minimum deal ledger. Everything the broker believes about reliability must be inferred from repeated collective outcomes.
- The original uses fixed selection policies; the broker agent replaces them.
- The original is a batch Python simulation; ours needs `reset`, `observe`, and `step`.
- We add an SLA-calibrated broker reward, which the original does not have.
- We translate paper “tasks” into broker-facing “deals.”
- The original policies remain as baselines: Free, Coll-Stake, Coll-Rep, and Coll-SR.
- The first version follows the paper’s evaluated setting: non-adversarial individual asset failures across small and large supply pools. Combination failures are a planned extension.

## thinking:points

- Centralized cloud providers, aka hyperscalers, bundle infrastructure, monitoring, and SLA accountability. OTC compute breaks this apart across owners, operators, resellers, and infrastructure providers. That is partly why the broker is there: to pull the pieces back into one deal the buyer can trust. The question is whether an agent can help do that job, manage the reliability risk, and still meet the buyer’s SLA from incomplete market signals.
- The original paper’s mechanism is motivated by game theory: when individual behavior cannot be observed, rewarding or punishing the whole group can still promote reliable participation. Its simulations use automatic matching policies rather than an intelligent selector. This environment turns that matching decision into a sequential game by making the broker responsible for choosing each group of assets.
