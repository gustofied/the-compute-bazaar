# Reliability Is Blind

**Question: Can an agent acting as a compute broker decide which supply to place into a deal when it knows what delivered in the past, but not what caused each failure?**

Based on [_Reliability Is Blind_](https://arxiv.org/abs/2503.19055) and its [reference implementation](https://github.com/RedChainLab/Reliability-Is-Blind-Collective-Incentives).

A rolling brokerage game for private and OTC compute deal flow. One rollout represents a broker’s book of compute deals, and each step represents one arranged deal. The broker chooses four compute suppliers from the supply available at its desk. The environment reports whether the complete placement delivered or failed, but not which supplier caused the failure. Each outcome updates the public stake and eligibility of the selected suppliers, changing the supply available for the next deal. The broker’s target is to keep failed deliveries at or below 5% across the book.

I am building and evaluating the game as a Harbor task. Alongside evaluating the agent’s performance in the game, I study which suppliers the broker places into deals, how it responds to failures, when it returns to suppliers that delivered, and when it stops placing weak ones. A little behavioral analysis.

In the original simulation, observability in a decentralized compute marketplace is limited because assets remain independently owned and may operate through confidential execution. Several assets are matched to execute each task. These assets can include an application, dataset, model, and server. The marketplace knows which assets participated and whether the task succeeded, but cannot identify which asset, or combination of assets, caused a failure.

Similarly, observability is limited in OTC compute markets, but for different reasons. Supply passes through brokers and resellers, while inventory owners, counterparties, facilities, cluster operators, network providers, and hardware providers may all be separate parties. Many may also be new entrants to the compute market, connected through novel or untested supply routes. The buyer may know that the deal failed to deliver without knowing which part of the supply failed.

The original paper and code are by Henry Mont, Matthieu Bettinger, Sonia Ben Mokhtar, and Anthony Simonet-Boulogne and are licensed under [CC BY 4.0](https://github.com/RedChainLab/Reliability-Is-Blind-Collective-Incentives/blob/main/LICENSE).

## Environment

One Harbor trial is one rollout. Each rollout starts with 20 recurring compute suppliers and contains 100 steps. Each step represents one arranged compute deal and one broker decision. The deal’s delivery period is compressed into a single outcome: the complete placement delivered or failed.

Each rollout is generated from a recorded seed. With the same environment version, configuration, and sequence of valid selections, the market trajectory can be replayed exactly.

Each paper asset becomes a recurring compute supplier in the game. For example, it may represent capacity from a specific provider and cluster accessed through a particular counterparty. Selecting a supplier creates a capacity allocation for that deal. Every supplier receives a unique ID that is never reused and keeps a fixed hidden failure probability while it remains in the rollout. Each supplier also has a public stake, which acts as the game’s visible reputation score, and an eligibility status that changes with outcomes. Any four eligible suppliers can fulfil a deal.

To preserve the paper’s experimental structure, each simulated deal requires four capacity allocations. Real OTC transactions may involve one provider or several, with quantities and compatibility determined by the deal. The fixed group size is a controlled environment assumption rather than a claim about all compute transactions.

For example, a buyer may require 2,048 GPUs, fulfilled through four 512-GPU allocations. The placement succeeds only if all four allocations are delivered according to the simulated acceptance criteria.

1. A buyer request enters the desk. The broker must fill it with four blocks of capacity from the eligible supply.
2. The broker sees the eligible compute suppliers and each supplier’s public stake. It can also see which suppliers participated in past deals and whether those deals delivered or failed.
3. The broker selects four suppliers, each contributing one block of capacity to the placement.
4. The environment resolves the deal as a successful or failed delivery.
5. The selected suppliers are collectively rewarded or penalized without revealing which supplier caused a failure.
6. Their updated stakes and any removals determine the eligible supply for the next deal. If fewer than four suppliers remain, the market adds replacements.

The deal ledger records a unique deal ID, the four selected supplier IDs, and the collective outcome. Individual failure events and root causes remain hidden.

### How the broker plays

The first deal is effectively blind. Every supplier begins with the same public stake and no delivery history, so the broker has no reason to prefer one placement over another.

The same compute suppliers recur across the broker’s book. Each supplier has a fixed hidden reliability, while its result in any particular deal remains uncertain. Every completed deal updates public stake and gives the broker another piece of evidence for its private trust map.

```text
Deal 1: A B C D → failure
Deal 2: A B C E → success
Deal 3: A B C E → success
Deal 4: A B C D → failure
```

A, B, and C appear in both the delivered and failed deals. E appears only in delivered deals, while D appears only in failures. This does not prove that D caused either failure, but it gives the broker a reason to be cautious. Across more deals, the broker can compare placements and gradually decide which suppliers to keep using, which to test again, and which to stop placing.

Real OTC desks make similar judgments, but they cannot usually hold everything else constant. Requirements, timing, availability, and reliability can all change between deals. Fixed supplier reliability and one-supplier substitutions are simulation assumptions that make this process measurable.

### Actions

The broker selects exactly four distinct eligible supplier IDs. A valid selection resolves one deal and advances the rollout by one step. The broker cannot abstain.

Invalid, duplicate, or ineligible selections return an error without advancing the market or drawing a delivery outcome. After 10 invalid selections, the rollout ends as an agent failure and receives the minimum Harbor reward of `-1`.

Status and history queries are read-only. They do not draw an outcome or change the market state.

### How it grades

**Deal succeeds:**

- Each selected supplier gains `+R` stake, up to the configured maximum.
- The broker receives `+R` reward.

**Deal fails:**

- Each selected supplier loses `P` stake.
- Any supplier that reaches the ruin threshold becomes ineligible.
- The broker receives `-P` reward.

The supplier updates create the supply state for the next deal. The broker reward grades the decision it just made.

Post-deal stake is bounded between `S0 / 1000` and `S0`, and a supplier is removed when its post-deal stake is at or below `P`. The market immediately adds suppliers if fewer than four remain. New suppliers enter with stake `S0` and their own fixed hidden failure probability.

For a 5% delivery-failure target with `P = 1`, the paper’s calibration gives `R = 0.05 / 0.95`:

- Success: `+0.0526`
- Failure: `-1`

Across 100 deals, 95 delivered deals and 5 failed deals produce roughly zero total reward. Keeping failures below 5% gives positive reward; exceeding 5% gives negative reward.

At rollout end:

- **Broker reward:** the mean reward across all deals. This is the Harbor reward and later the Verifiers/Prime RL training signal.
- **Reliability result:** the overall deal delivery rate and whether failed deliveries stayed at or below 5%.
- **Supply state:** the final public stakes and eligible supply pool.

## Building the environment

How I am converting _Reliability Is Blind_ into a Harbor environment for compute deals:

- The paper assumes only two trustworthy facts: who was involved and whether the task worked. In this environment, that becomes the minimum deal ledger. Everything the broker believes about reliability must be inferred from repeated collective outcomes.
- The broker environment keeps the bounded collective stake updates and ruin/removal rules used by Coll-SR, while the broker replaces its automatic stake-weighted selector.
- The original is a batch Python simulation; ours needs `reset`, `observe`, and `step`.
- We expose the paper's calibrated task reward and penalty as the broker's rollout reward.
- We translate paper “tasks” into broker-facing “deals.”
- The broker evaluation uses 20 compute suppliers and 100 deals so every step remains a real broker decision. The paper’s default simulation runs for 10,000 tasks, with a reported large-pool configuration running for 30,000; those batch runs are not substituted for agent decisions.
- The environment follows the paper’s non-adversarial individual-failure setting. The broker evaluation starts each rollout with 20 suppliers; separate parity checks can retain the paper’s other pool sizes. Combination failures are a planned extension.

## thinking:points

- Centralized cloud providers, especially hyperscalers, give buyers a single interface for provisioning, monitoring, support, and contractual service commitments. Private and OTC AI compute can expose a more fragmented delivery chain spanning hardware owners, data center operators, network and power providers, resellers, and cloud operators. A broker can reduce this coordination burden by aggregating supply, standardizing terms, matching demand to recurring supply, and tracking which placements actually deliver. The question in this environment is whether an agent can select and manage recurring supply while maintaining delivery reliability when failures are difficult to attribute.
- A lot of a broker’s edge is the private trust map built across repeated deals: who really controls the supply, which providers and data centers deliver, which counterparties change terms, and which supply routes keep becoming problematic. Some of this lives in CRMs, spreadsheets, messages, and diligence files, but much of it remains tacit knowledge. This environment perhaps tries to isolate whether an agent can form a minimal version of that trust map from incomplete delivery outcomes and use it when placing the next deal.
- The original paper’s mechanism is motivated by game theory: when individual behavior cannot be observed, rewarding or punishing the whole group can still promote reliable participation. Its simulations use automatic matching policies rather than an intelligent selector. This environment turns that matching decision into a sequential game by making the broker responsible for choosing the suppliers for each deal.
