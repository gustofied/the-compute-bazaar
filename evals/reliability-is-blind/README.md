# Reliability Is Blind

**Question: Large compute deals are often negotiated through OTC desks and multi-party supply chains with limited shared visibility. Can an agent acting as a broker still meet the SLA promised to the buyer when failures in the deal are difficult to attribute?**

Based on [_Reliability Is Blind_](https://arxiv.org/abs/2503.19055) and its [reference implementation](https://github.com/RedChainLab/Reliability-Is-Blind-Collective-Incentives).

A rolling procurement game for data-center capacity. Each step represents a compute deal with an agreed SLA. An agent acts as the compute broker, selecting assets from the available supply to fulfil the deal. Success rewards all selected assets; failure penalizes them without revealing which asset caused it. After each deal, the stake, reputation, and eligibility of each selected asset are updated, forming the supply state the broker sees before the next deal. The broker is scored on whether the deals it assembles meet their SLAs over time.

I built and evaluated the game as a Harbor task. I then ran the same Harbor task through Verifiers for a training run with model X. Alongside evaluating the agent’s performance in the game, I study which supply the broker explores, how it responds to failures, when it returns to reliable routes, and when it stops using weak ones. A little behavioral analysis.

In the original simulation, observability in a decentralized compute marketplace is limited because assets remain independently owned and may operate through confidential execution. Several assets are matched to execute each task. These assets can include an application, dataset, model, and server. The marketplace knows which assets participated and whether the task succeeded, but cannot identify which asset, or combination of assets, caused a failure.

Rewards and penalties are calibrated to a reliability target. Across repeated tasks, failure-prone assets tend to lose their stake and eligibility, while reliable assets remain available.

Similarly, observability is limited in OTC compute markets, but for different reasons. Supply passes through brokers and resellers, while inventory owners, counterparties, facilities, cluster operators, network providers, and hardware providers may all be separate parties. The buyer may know that the deal failed to deliver without knowing where the fulfilment chain broke down.

In this environment, the paper’s automatic asset-selection rules become decisions made by the broker. For each new deal, the broker assembles a fulfilment route from the available supply. The broker is not asked to identify which asset failed. It must decide which route is most likely to deliver the next deal from incomplete outcome signals.

The original paper and code are by Henry Mont, Matthieu Bettinger, Sonia Ben Mokhtar, and Anthony Simonet-Boulogne and are licensed under [CC BY 4.0](https://github.com/RedChainLab/Reliability-Is-Blind-Collective-Incentives/blob/main/LICENSE).

## Environment

It is a rolling book of separate deals, with each outcome updating the supply state used for the next deal.

One Harbor trial runs one rollout. Each rollout contains a sequence of steps, and each step represents one compute deal:

1. A new compute deal arrives with the buyer’s requirements and an agreed SLA.
2. The broker observes the available supply, including visible stake, reputation, and eligibility, together with prior fulfilment routes and their collective outcomes.
3. The broker selects the assets that will form the deal’s fulfilment route.
4. The environment resolves the deal as a successful or failed delivery.
5. The selected assets are collectively rewarded or penalized without revealing which asset caused a failure.
6. Their updated stake, reputation, and eligibility form the supply state presented to the broker before the next deal.

### How it grades

**Deal succeeds:**

- Each selected asset gains `+R` stake.
- The broker receives `+R` reward.

**Deal fails:**

- Each selected asset’s stake changes by `-P`.
- The broker receives `-P` reward.

The asset updates create the supply state for the next deal. The broker reward grades the decision it just made.

For a 5% SLA target, the paper’s calibration could be:

- Success: `+0.0526`
- Failure: `-1`

Across 100 deals, 95 successes and 5 failures produce roughly zero total reward. Doing better than the SLA gives positive reward; doing worse gives negative reward.

At rollout end:

- **Broker reward:** the mean reward across all deals. This is the Harbor reward and later the Verifiers/Prime RL training signal.
- **SLA result:** the overall delivery success rate and whether it met the agreed target.
- **Supply state:** the final stake, reputation, and eligibility of the supply pool.

## Changes

To convert _Reliability Is Blind_ into a Harbor task:

- The original uses fixed selection policies; our agent replaces them.
- The original is a batch Python simulation; ours needs reset, observe, and step.
- We add an SLA-calibrated broker reward, which the original does not have.
- We translate paper “tasks” into broker-facing “deals.”
- The original policies remain as baselines: Free, Coll-Stake, Coll-Rep, and Coll-SR.
