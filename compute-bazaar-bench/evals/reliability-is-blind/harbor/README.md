# Reliability Is Blind

**Question: Can an agent acting as a compute broker decide which supply to place into a deal when it knows what delivered in the past, but not what caused each failure?**

Based on [_Reliability Is Blind_](https://arxiv.org/abs/2503.19055) and its [reference implementation](https://github.com/RedChainLab/Reliability-Is-Blind-Collective-Incentives).

A rolling brokerage game for private and OTC compute deal flow. One rollout
represents a broker's book of compute deals, and each step represents one
arranged deal. The broker chooses four compute suppliers from the supply
available at its desk. The environment reports whether the complete placement
delivered or failed, but not which supplier caused the failure. Each outcome
updates the public stake and eligibility of the selected suppliers, changing
the supply available for the next deal. The broker's target is to keep failed
deliveries at or below 5% across the book.

Private compute supply can pass through inventory owners, data centers,
operators, counterparties, brokers, and resellers. A placement may fail without
the broker knowing which part of that supply failed. This task isolates whether
an agent can form a useful trust map from those collective outcomes and use it
when placing the next deal.

## Environment

One Harbor trial is one rollout containing 100 deals. It starts with 20
recurring compute suppliers. Every supplier begins with the same public stake
and has a fixed hidden failure probability for the rollout. The first deal is
therefore blind; later decisions can use public stake and the history of which
supplier groups delivered or failed.

The broker must fill each deal with four distinct eligible suppliers. This
fixed group size preserves the paper's experimental structure. It is a
controlled environment assumption, not a claim that every real compute deal
uses four suppliers.

## Agent Contract

The agent uses three commands:

- `market status`
- `market history`
- `market select <supplier-id> <supplier-id> <supplier-id> <supplier-id>`

A valid selection resolves one deal. Status and history are read-only. Invalid,
duplicate, or ineligible selections do not draw an outcome. Ten invalid
selections terminate the rollout as an agent failure.

## Scoring

A delivered deal gives the broker `+0.0526315789`; a failed deal gives it `-1`.
The primary Harbor reward is the mean reward across the completed 100-deal
rollout. An incomplete rollout receives `-1`.

At the 5% delivery-failure target, 95 delivered deals and five failed deals
produce approximately zero reward. Fewer failures produce a positive reward;
more failures produce a negative reward. Delivery rate, target attainment,
completion, final supply state, and verifier integrity remain separate exact
metrics.

## Verification

The main container contains only the public market CLI. A protected sidecar
owns the seed, hidden supplier reliability, market state, and authoritative
ledger. After the agent finishes, Harbor collects a one-shot authenticated
snapshot. A separate no-network verifier replays all valid selections from the
recorded seed and fails closed on incomplete or tampered evidence.

The public reference solution follows the highest visible stake. It verifies
the environment and artifact path; it is not a hidden-information optimum or a
performance ceiling.

The original paper and code are by Henry Mont, Matthieu Bettinger, Sonia Ben
Mokhtar, and Anthony Simonet-Boulogne and are licensed under
[CC BY 4.0](https://github.com/RedChainLab/Reliability-Is-Blind-Collective-Incentives/blob/main/LICENSE).
