"""Deterministic market state machine for collective reliability incentives.

Scientific mechanics are adapted from "Reliability Is Blind: Collective
Incentives for Decentralized Computing Marketplaces without Individual
Behavior Information" and its CC BY 4.0 reference implementation at revision
98adffaa7931c74cdd749cde230b7e87c9d45d86.

The broker engine preserves the paper's four-source, individual-failure,
collective reward/slash, bounded-stake, and ruin mechanics. It deliberately
adds monotonic supplier IDs and keyed randomness so agent actions are replayable
and policies can be compared against the same latent supplier shocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import math
from typing import Iterable, Sequence


UPSTREAM_REVISION = "98adffaa7931c74cdd749cde230b7e87c9d45d86"
ENGINE_VERSION = "0.1.0"


class TerminalReason(StrEnum):
    """Why the market stopped accepting deals."""

    HORIZON_COMPLETED = "horizon_completed"
    INVALID_ACTION_LIMIT = "invalid_action_limit"


@dataclass(frozen=True, slots=True)
class MarketConfig:
    """Immutable parameters for one market rollout."""

    initial_supplier_count: int = 20
    supplier_cap: int = 20
    deal_size: int = 4
    horizon: int = 100
    initial_stake: float = 10.0
    slash_amount: float = 1.0
    target_failure_rate: float = 0.05
    failure_distribution_alpha: float = 0.1
    scheduled_arrival_interval: int | None = 500
    invalid_action_limit: int = 10
    randomness_version: str = "rib-keyed-v1"

    def __post_init__(self) -> None:
        integer_fields = {
            "initial_supplier_count": self.initial_supplier_count,
            "supplier_cap": self.supplier_cap,
            "deal_size": self.deal_size,
            "horizon": self.horizon,
            "invalid_action_limit": self.invalid_action_limit,
        }
        for name, value in integer_fields.items():
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
        if (
            self.scheduled_arrival_interval is not None
            and type(self.scheduled_arrival_interval) is not int
        ):
            raise TypeError("scheduled_arrival_interval must be an integer or None")

        numeric_fields = {
            "initial_stake": self.initial_stake,
            "slash_amount": self.slash_amount,
            "target_failure_rate": self.target_failure_rate,
            "failure_distribution_alpha": self.failure_distribution_alpha,
        }
        for name, value in numeric_fields.items():
            if type(value) not in {int, float}:
                raise TypeError(f"{name} must be a real number")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if type(self.randomness_version) is not str:
            raise TypeError("randomness_version must be a string")

        if self.deal_size <= 0:
            raise ValueError("deal_size must be positive")
        if self.initial_supplier_count < self.deal_size:
            raise ValueError("initial_supplier_count must cover one deal")
        if self.supplier_cap < self.initial_supplier_count:
            raise ValueError("supplier_cap cannot be below the initial pool")
        if self.horizon <= 0:
            raise ValueError("horizon must be positive")
        if self.initial_stake <= 0:
            raise ValueError("initial_stake must be positive")
        if self.slash_amount <= 0:
            raise ValueError("slash_amount must be positive")
        if self.initial_stake <= self.slash_amount:
            raise ValueError("initial_stake must exceed the ruin threshold")
        if self.slash_amount < self.minimum_stake:
            raise ValueError(
                "slash_amount must be at least the minimum stake so ruin is reachable"
            )
        if not 0 < self.target_failure_rate < 1:
            raise ValueError("target_failure_rate must be between zero and one")
        if self.failure_distribution_alpha <= 0:
            raise ValueError("failure_distribution_alpha must be positive")
        if (
            self.scheduled_arrival_interval is not None
            and self.scheduled_arrival_interval <= 0
        ):
            raise ValueError("scheduled_arrival_interval must be positive or None")
        if self.invalid_action_limit <= 0:
            raise ValueError("invalid_action_limit must be positive")
        if not self.randomness_version:
            raise ValueError("randomness_version cannot be empty")

    @property
    def reward_amount(self) -> float:
        """Paper calibration R = P * target / (1 - target)."""

        return (
            self.slash_amount
            * self.target_failure_rate
            / (1.0 - self.target_failure_rate)
        )

    @property
    def minimum_stake(self) -> float:
        """Lower Coll-SR reputation bound."""

        return self.initial_stake / 1000.0

    @property
    def maximum_stake(self) -> float:
        """Upper Coll-SR reputation bound."""

        return self.initial_stake

    @property
    def ruin_threshold(self) -> float:
        """The reproduction removes assets at post-update stake <= P."""

        return self.slash_amount

    @property
    def incomplete_reward(self) -> float:
        """Fail-closed score for an incomplete rollout."""

        return -self.slash_amount


@dataclass(frozen=True, slots=True)
class PublicSupplier:
    """Supplier state that the broker may observe."""

    supplier_id: int
    stake: float
    eligible: bool


@dataclass(frozen=True, slots=True)
class _PrivateSupplier:
    """Protected supplier truth for tests, baselines, and the verifier."""

    supplier_id: int
    failure_probability: float
    stake: float
    eligible: bool
    created_after_deal: int


@dataclass(frozen=True, slots=True)
class DealRecord:
    """Minimum public deal ledger entry."""

    deal_id: int
    supplier_ids: tuple[int, ...]
    delivered: bool


@dataclass(frozen=True, slots=True)
class Observation:
    """Complete public observation returned to a broker."""

    completed_deals: int
    horizon: int
    target_failure_rate: float
    invalid_actions: int
    invalid_action_limit: int
    suppliers: tuple[PublicSupplier, ...]
    history: tuple[DealRecord, ...]
    terminal: bool
    terminal_reason: TerminalReason | None

    @property
    def deals_remaining(self) -> int:
        return self.horizon - self.completed_deals


@dataclass(frozen=True, slots=True)
class StepResult:
    """Result of a state-changing action attempt."""

    accepted: bool
    observation: Observation
    deal: DealRecord | None = None
    broker_reward: float | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class MarketResult:
    """Deterministic rollout metrics used by the future verifier."""

    completion: int
    primary_reward: float
    completed_deals: int
    delivered_deals: int
    failed_deals: int
    delivery_rate: float
    failure_rate: float
    target_met: bool
    terminal_reason: str
    eligible_supplier_count: int
    supply_state: tuple[PublicSupplier, ...]


@dataclass(slots=True)
class _Supplier:
    supplier_id: int
    failure_probability: float
    stake: float
    eligible: bool
    created_after_deal: int
    times_selected: int = 0
    collective_failures: int = 0
    nominal_rewards: float = 0.0


def _keyed_uniform(
    *, version: str, seed: int, domain: str, coordinates: Sequence[int]
) -> float:
    """Return a stable U[0,1) value without process-global RNG state."""

    coordinate_text = ":".join(str(value) for value in coordinates)
    payload = f"{version}:{domain}:{seed}:{coordinate_text}".encode()
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


class MarketEngine:
    """Authoritative reset/observe/step state machine."""

    def __init__(self, config: MarketConfig | None = None) -> None:
        self.config = config or MarketConfig()
        self._seed: int | None = None
        self._suppliers: dict[int, _Supplier] = {}
        self._eligible_ids: set[int] = set()
        self._history: list[DealRecord] = []
        self._deal_rewards: list[float] = []
        self._next_supplier_id = 0
        self._invalid_actions = 0
        self._terminal_reason: TerminalReason | None = None
        self._initial_failure_probabilities: tuple[float, ...] | None = None

    @property
    def is_reset(self) -> bool:
        return self._seed is not None

    @property
    def terminal(self) -> bool:
        return self._terminal_reason is not None

    def reset(
        self,
        seed: int,
        *,
        failure_probabilities: Sequence[float] | None = None,
    ) -> Observation:
        """Reset to a seeded market.

        ``failure_probabilities`` is an explicit parity/test hook. The protected
        sidecar will call reset with only a seed.
        """

        if type(seed) is not int:
            raise TypeError("seed must be an integer")
        if failure_probabilities is not None:
            if len(failure_probabilities) != self.config.initial_supplier_count:
                raise ValueError(
                    "failure_probabilities must match initial_supplier_count"
                )
            if any(type(value) not in {int, float} for value in failure_probabilities):
                raise TypeError("failure probabilities must be real numbers")
            probabilities = tuple(float(value) for value in failure_probabilities)
            if any(
                not math.isfinite(value) or not 0.0 <= value <= 1.0
                for value in probabilities
            ):
                raise ValueError("failure probabilities must lie in [0, 1]")
            self._initial_failure_probabilities = probabilities
        else:
            self._initial_failure_probabilities = None

        self._seed = seed
        self._suppliers = {}
        self._eligible_ids = set()
        self._history = []
        self._deal_rewards = []
        self._next_supplier_id = 0
        self._invalid_actions = 0
        self._terminal_reason = None

        for _ in range(self.config.initial_supplier_count):
            self._add_supplier(created_after_deal=0)
        return self.observe()

    def observe(self) -> Observation:
        """Return public state without changing market state or randomness."""

        self._require_reset()
        suppliers = tuple(
            PublicSupplier(
                supplier_id=supplier.supplier_id,
                stake=supplier.stake,
                eligible=supplier.eligible,
            )
            for supplier in sorted(
                self._suppliers.values(), key=lambda value: value.supplier_id
            )
            if supplier.eligible
        )
        return Observation(
            completed_deals=len(self._history),
            horizon=self.config.horizon,
            target_failure_rate=self.config.target_failure_rate,
            invalid_actions=self._invalid_actions,
            invalid_action_limit=self.config.invalid_action_limit,
            suppliers=suppliers,
            history=tuple(self._history),
            terminal=self.terminal,
            terminal_reason=self._terminal_reason,
        )

    def _private_suppliers_for_qa(self) -> tuple[_PrivateSupplier, ...]:
        """Return protected truth for local QA policies.

        This internal helper is not part of the broker contract. The deployed
        sidecar must not expose it or share this Python object with the agent.
        """

        self._require_reset()
        return tuple(
            _PrivateSupplier(
                supplier_id=supplier.supplier_id,
                failure_probability=supplier.failure_probability,
                stake=supplier.stake,
                eligible=supplier.eligible,
                created_after_deal=supplier.created_after_deal,
            )
            for supplier in sorted(
                self._suppliers.values(), key=lambda value: value.supplier_id
            )
        )

    def step(self, supplier_ids: Iterable[int]) -> StepResult:
        """Resolve one valid four-supplier placement or reject it as a no-op."""

        self._require_reset()
        if self.terminal:
            return StepResult(
                accepted=False,
                observation=self.observe(),
                error="rollout is already terminal",
            )

        try:
            selected = tuple(supplier_ids)
        except TypeError:
            return self._reject("selection must be an iterable of supplier IDs")

        validation_error = self._validate_selection(selected)
        if validation_error is not None:
            return self._reject(validation_error)

        canonical_ids = tuple(sorted(selected))
        deal_id = len(self._history) + 1
        failed_ids = tuple(
            supplier_id
            for supplier_id in canonical_ids
            if self._supplier_fails(deal_id, supplier_id)
        )
        delivered = not failed_ids
        broker_reward = (
            self.config.reward_amount if delivered else -self.config.slash_amount
        )

        for supplier_id in canonical_ids:
            supplier = self._suppliers[supplier_id]
            supplier.times_selected += 1
            if delivered:
                supplier.stake = min(
                    supplier.stake + self.config.reward_amount,
                    self.config.maximum_stake,
                )
                supplier.nominal_rewards += self.config.reward_amount
            else:
                supplier.stake = max(
                    supplier.stake - self.config.slash_amount,
                    self.config.minimum_stake,
                )
                supplier.collective_failures += 1

        if not delivered:
            for supplier_id in canonical_ids:
                supplier = self._suppliers[supplier_id]
                if supplier.stake <= self.config.ruin_threshold:
                    supplier.eligible = False
                    self._eligible_ids.remove(supplier_id)

        record = DealRecord(
            deal_id=deal_id,
            supplier_ids=canonical_ids,
            delivered=delivered,
        )
        self._history.append(record)
        self._deal_rewards.append(broker_reward)

        self._apply_scheduled_arrival()
        self._replenish_actionable_pool()

        if len(self._history) == self.config.horizon:
            self._terminal_reason = TerminalReason.HORIZON_COMPLETED

        return StepResult(
            accepted=True,
            observation=self.observe(),
            deal=record,
            broker_reward=broker_reward,
        )

    def result(self) -> MarketResult:
        """Compute the primary reward and public terminal metrics.

        Calling this before the configured valid-deal horizon fails closed without mutating the
        market. Infrastructure failures are classified outside this engine.
        """

        observation = self.observe()
        completed = observation.completed_deals
        delivered = sum(record.delivered for record in self._history)
        failed = completed - delivered
        delivery_rate = delivered / completed if completed else 0.0
        failure_rate = failed / completed if completed else 0.0
        complete = self._terminal_reason is TerminalReason.HORIZON_COMPLETED
        primary_reward = (
            math.fsum(self._deal_rewards) / completed
            if complete
            else self.config.incomplete_reward
        )
        terminal_reason = (
            self._terminal_reason.value
            if self._terminal_reason is not None
            else "incomplete"
        )
        supply_state = tuple(
            PublicSupplier(
                supplier_id=supplier.supplier_id,
                stake=supplier.stake,
                eligible=supplier.eligible,
            )
            for supplier in sorted(
                self._suppliers.values(), key=lambda value: value.supplier_id
            )
        )
        return MarketResult(
            completion=int(complete),
            primary_reward=primary_reward,
            completed_deals=completed,
            delivered_deals=delivered,
            failed_deals=failed,
            delivery_rate=delivery_rate,
            failure_rate=failure_rate,
            target_met=complete and failure_rate <= self.config.target_failure_rate,
            terminal_reason=terminal_reason,
            eligible_supplier_count=len(self._eligible_ids),
            supply_state=supply_state,
        )

    def _validate_selection(self, selected: tuple[object, ...]) -> str | None:
        if len(selected) != self.config.deal_size:
            return f"selection must contain exactly {self.config.deal_size} IDs"
        if any(type(supplier_id) is not int for supplier_id in selected):
            return "supplier IDs must be integers"
        if len(set(selected)) != len(selected):
            return "supplier IDs must be distinct"
        if any(supplier_id not in self._eligible_ids for supplier_id in selected):
            return "selection contains an unknown or ineligible supplier"
        return None

    def _reject(self, error: str) -> StepResult:
        self._invalid_actions += 1
        if self._invalid_actions >= self.config.invalid_action_limit:
            self._terminal_reason = TerminalReason.INVALID_ACTION_LIMIT
        return StepResult(
            accepted=False,
            observation=self.observe(),
            error=error,
        )

    def _add_supplier(self, *, created_after_deal: int) -> _Supplier:
        supplier_id = self._next_supplier_id
        self._next_supplier_id += 1
        if self._initial_failure_probabilities is not None and supplier_id < len(
            self._initial_failure_probabilities
        ):
            failure_probability = self._initial_failure_probabilities[supplier_id]
        else:
            uniform = self._uniform("supplier-reliability", supplier_id)
            failure_probability = uniform ** (
                1.0 / self.config.failure_distribution_alpha
            )
        supplier = _Supplier(
            supplier_id=supplier_id,
            failure_probability=failure_probability,
            stake=self.config.initial_stake,
            eligible=True,
            created_after_deal=created_after_deal,
        )
        self._suppliers[supplier_id] = supplier
        self._eligible_ids.add(supplier_id)
        return supplier

    def _supplier_fails(self, deal_id: int, supplier_id: int) -> bool:
        supplier = self._suppliers[supplier_id]
        shock = self._uniform("supplier-shock", deal_id, supplier_id)
        return shock < supplier.failure_probability

    def _uniform(self, domain: str, *coordinates: int) -> float:
        assert self._seed is not None
        return _keyed_uniform(
            version=self.config.randomness_version,
            seed=self._seed,
            domain=domain,
            coordinates=coordinates,
        )

    def _apply_scheduled_arrival(self) -> None:
        interval = self.config.scheduled_arrival_interval
        completed = len(self._history)
        if (
            interval is not None
            and completed % interval == 0
            and len(self._eligible_ids) < self.config.supplier_cap
        ):
            self._add_supplier(created_after_deal=completed)

    def _replenish_actionable_pool(self) -> None:
        completed = len(self._history)
        while len(self._eligible_ids) < self.config.deal_size:
            self._add_supplier(created_after_deal=completed)

    def _require_reset(self) -> None:
        if not self.is_reset:
            raise RuntimeError("reset(seed) must be called before using the market")
