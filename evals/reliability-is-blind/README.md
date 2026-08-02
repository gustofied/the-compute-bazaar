# Reliability Is Blind

**Question: Large compute deals are often negotiated through OTC desks and multi-party supply chains with limited shared visibility. Can an agent acting as a broker still meet the SLA promised to the buyer when failures in the deal are difficult to attribute?**

Based on [_Reliability Is Blind_](https://arxiv.org/abs/2503.19055) and its [reference implementation](https://github.com/RedChainLab/Reliability-Is-Blind-Collective-Incentives).

A rolling procurement game for data-center capacity. Each round represents a compute deal with an agreed SLA. An agent acts as the compute broker, selecting assets from the available supply to fulfil the deal. Success rewards all selected assets; failure penalizes them without revealing which asset caused it. After each deal, the stake, reputation, and eligibility of each selected asset are updated, forming the supply state the broker sees before the next deal. The broker is scored on whether the deals it assembles meet their SLAs over time.

I built and evaluated the game as a task in Harbor. I then ran the same game with Verifiers for a training run with model X. Alongside the evaluation of the agents success in the game, I also study which supply the broker explores, how it responds to failures, when it returns to reliable routes, and when it stops using weak ones. A little behavioral analysis.

In the original simulation, observability in a decentralized compute marketplace is limited because assets remain independently owned and may operate through confidential execution. Several assets are matched to execute each task. These assets can include an application, dataset, model, and server. The marketplace knows which assets participated and whether the task succeeded, but cannot identify which asset, or combination of assets, caused a failure.

Similarly, observability is limited in OTC compute markets, but for different reasons. Supply passes through brokers and resellers, while inventory owners, counterparties, facilities, cluster operators, network providers, and hardware providers may all be separate parties. The buyer may know that capacity failed to deliver without knowing where the fulfilment chain broke.

In this environment, the paper’s automatic asset-selection rules become decisions made by the broker. The broker repeatedly assigns compute tasks across the available market, learning which assets and fulfilment routes can be trusted from incomplete outcome signals.

The goal is to inspect how an agent broker explores supply, responds to failures, returns to reliable routes, and stops using weak ones under limited observability.

The original paper and code are by Henry Mont, Matthieu Bettinger, Sonia Ben Mokhtar, and Anthony Simonet-Boulogne and are licensed under [CC BY 4.0](https://github.com/RedChainLab/Reliability-Is-Blind-Collective-Incentives/blob/main/LICENSE).

## Environment

Each episode contains a sequence of procurement rounds:

1. A compute task enters the market.
2. The broker observes the available supply, visible stake, reputation, and previous outcomes.
3. The broker selects a fulfilment route.
4. The environment resolves the task as a success or failure.
5. The market updates, but the root cause of a failure remains hidden.
