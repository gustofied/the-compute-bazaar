from __future__ import annotations

from dataclasses import asdict
import math
from pathlib import Path
import sys
import unittest

EVALUATOR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVALUATOR_ROOT))

from reliability_is_blind import MarketConfig, MarketEngine, TerminalReason  # noqa: E402
from reliability_is_blind.engine import _keyed_uniform  # noqa: E402


def config(**overrides: object) -> MarketConfig:
    values: dict[str, object] = {
        "initial_supplier_count": 4,
        "supplier_cap": 4,
        "deal_size": 4,
        "horizon": 100,
        "scheduled_arrival_interval": None,
    }
    values.update(overrides)
    return MarketConfig(**values)


class MarketConfigTests(unittest.TestCase):
    def test_paper_reward_calibration(self) -> None:
        market_config = MarketConfig()
        self.assertEqual(market_config.slash_amount, 1.0)
        self.assertAlmostEqual(market_config.reward_amount, 1 / 19)
        self.assertEqual(market_config.minimum_stake, 0.01)
        self.assertEqual(market_config.maximum_stake, 10.0)
        self.assertEqual(market_config.ruin_threshold, 1.0)

    def test_rejects_impossible_pool(self) -> None:
        with self.assertRaises(ValueError):
            MarketConfig(initial_supplier_count=3, deal_size=4)

    def test_rejects_non_finite_and_runtime_type_mismatches(self) -> None:
        with self.assertRaises(ValueError):
            MarketConfig(initial_stake=math.nan)
        with self.assertRaises(TypeError):
            MarketConfig(horizon=100.0)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            MarketConfig(invalid_action_limit=True)  # type: ignore[arg-type]

    def test_rejects_configuration_where_ruin_is_unreachable(self) -> None:
        with self.assertRaises(ValueError):
            MarketConfig(initial_stake=2000, slash_amount=1)


class MarketEngineTests(unittest.TestCase):
    def test_keyed_randomness_has_a_versioned_golden_vector(self) -> None:
        values = [
            _keyed_uniform(
                version="rib-keyed-v1",
                seed=7,
                domain="supplier-shock",
                coordinates=(1, supplier_id),
            )
            for supplier_id in range(4)
        ]
        self.assertEqual(
            values,
            [
                0.006723094288893364,
                0.8032579748742756,
                0.6242082120838789,
                0.9476987870720359,
            ],
        )

    def test_reset_observation_contains_no_hidden_reliability(self) -> None:
        engine = MarketEngine(config())
        observation = engine.reset(7, failure_probabilities=[0.1, 0.2, 0.3, 0.4])

        self.assertEqual(
            [item.supplier_id for item in observation.suppliers], [0, 1, 2, 3]
        )
        self.assertTrue(all(item.stake == 10 for item in observation.suppliers))
        self.assertEqual(observation.history, ())
        self.assertNotIn("failure_probability", repr(asdict(observation)))

    def test_reset_rejects_non_finite_test_probabilities(self) -> None:
        engine = MarketEngine(config())
        with self.assertRaises(ValueError):
            engine.reset(7, failure_probabilities=[0.1, 0.2, 0.3, math.nan])

    def test_success_rewards_broker_but_stake_stays_at_cap(self) -> None:
        engine = MarketEngine(config(horizon=1))
        engine.reset(7, failure_probabilities=[0, 0, 0, 0])

        step = engine.step([0, 1, 2, 3])

        self.assertTrue(step.accepted)
        self.assertTrue(step.deal and step.deal.delivered)
        self.assertAlmostEqual(step.broker_reward or 0.0, 1 / 19)
        self.assertTrue(all(item.stake == 10 for item in step.observation.suppliers))
        self.assertEqual(
            step.observation.terminal_reason, TerminalReason.HORIZON_COMPLETED
        )

    def test_one_hidden_failure_slashes_every_selected_supplier_once(self) -> None:
        engine = MarketEngine(config())
        engine.reset(7, failure_probabilities=[1, 0, 0, 0])

        step = engine.step([0, 1, 2, 3])

        self.assertTrue(step.accepted)
        self.assertFalse(step.deal and step.deal.delivered)
        self.assertEqual(step.broker_reward, -1)
        self.assertTrue(all(item.stake == 9 for item in step.observation.suppliers))
        self.assertEqual(
            asdict(step.deal),
            {
                "deal_id": 1,
                "supplier_ids": (0, 1, 2, 3),
                "delivered": False,
            },
        )

    def test_failure_then_success_matches_collective_stake_arithmetic(self) -> None:
        market_config = config(initial_supplier_count=8, supplier_cap=8)
        engine = MarketEngine(market_config)
        engine.reset(7, failure_probabilities=[0, 1, 0, 0, 0, 0, 0, 0])

        engine.step([0, 1, 2, 3])
        step = engine.step([0, 4, 5, 6])

        stakes = {item.supplier_id: item.stake for item in step.observation.suppliers}
        self.assertAlmostEqual(stakes[0], 9 + 1 / 19)
        self.assertEqual(stakes[1], 9)
        self.assertEqual(stakes[4], 10)

    def test_ninth_failure_ruins_sources_and_replenishes_with_unique_ids(self) -> None:
        engine = MarketEngine(config())
        engine.reset(7, failure_probabilities=[1, 1, 1, 1])

        for _ in range(9):
            step = engine.step([0, 1, 2, 3])

        self.assertEqual(
            [item.supplier_id for item in step.observation.suppliers], [4, 5, 6, 7]
        )
        self.assertTrue(all(item.stake == 10 for item in step.observation.suppliers))
        old_suppliers = engine._private_suppliers_for_qa()[:4]
        self.assertTrue(all(not item.eligible for item in old_suppliers))
        self.assertTrue(all(math.isclose(item.stake, 1) for item in old_suppliers))

    def test_invalid_action_changes_only_attempt_counter(self) -> None:
        engine = MarketEngine(config())
        before = engine.reset(19, failure_probabilities=[0.2] * 4)

        rejected = engine.step([0, 0, 1, 2])
        after = rejected.observation

        self.assertFalse(rejected.accepted)
        self.assertEqual(after.completed_deals, before.completed_deals)
        self.assertEqual(after.suppliers, before.suppliers)
        self.assertEqual(after.history, before.history)
        self.assertEqual(after.invalid_actions, 1)

    def test_invalid_action_does_not_change_next_deal_outcome(self) -> None:
        probabilities = [0.2, 0.3, 0.4, 0.5]
        direct = MarketEngine(config())
        delayed = MarketEngine(config())
        direct.reset(23, failure_probabilities=probabilities)
        delayed.reset(23, failure_probabilities=probabilities)

        delayed.step([0, 0, 1, 2])
        direct_step = direct.step([0, 1, 2, 3])
        delayed_step = delayed.step([0, 1, 2, 3])

        self.assertEqual(direct_step.deal, delayed_step.deal)
        self.assertEqual(
            direct_step.observation.suppliers, delayed_step.observation.suppliers
        )

    def test_selection_order_has_no_semantic_effect(self) -> None:
        probabilities = [0.2, 0.3, 0.4, 0.5]
        left = MarketEngine(config())
        right = MarketEngine(config())
        left.reset(29, failure_probabilities=probabilities)
        right.reset(29, failure_probabilities=probabilities)

        left_step = left.step([0, 1, 2, 3])
        right_step = right.step([3, 2, 1, 0])

        self.assertEqual(left_step.deal, right_step.deal)
        self.assertEqual(
            left_step.observation.suppliers, right_step.observation.suppliers
        )

    def test_tenth_invalid_action_terminates_and_fails_closed(self) -> None:
        engine = MarketEngine(config())
        engine.reset(31, failure_probabilities=[0] * 4)

        for _ in range(10):
            step = engine.step([0, 0, 1, 2])

        self.assertEqual(
            step.observation.terminal_reason, TerminalReason.INVALID_ACTION_LIMIT
        )
        result = engine.result()
        self.assertEqual(result.completion, 0)
        self.assertEqual(result.primary_reward, -1)
        self.assertEqual(result.completed_deals, 0)

    def test_incomplete_rollout_fails_closed(self) -> None:
        engine = MarketEngine(config())
        engine.reset(37, failure_probabilities=[0] * 4)
        engine.step([0, 1, 2, 3])

        result = engine.result()

        self.assertEqual(result.completion, 0)
        self.assertEqual(result.primary_reward, -1)
        self.assertEqual(result.terminal_reason, "incomplete")

    def test_exact_target_scores_zero_after_one_hundred_deals(self) -> None:
        engine = MarketEngine(
            config(initial_supplier_count=8, supplier_cap=8, horizon=100)
        )
        engine.reset(41, failure_probabilities=[1, 1, 1, 1, 0, 0, 0, 0])

        for _ in range(5):
            engine.step([0, 1, 2, 3])
        for _ in range(95):
            engine.step([4, 5, 6, 7])

        result = engine.result()
        self.assertEqual(result.completion, 1)
        self.assertEqual(result.failed_deals, 5)
        self.assertTrue(result.target_met)
        self.assertAlmostEqual(result.primary_reward, 0.0)

    def test_scheduled_arrival_respects_supplier_cap(self) -> None:
        market_config = config(
            initial_supplier_count=4,
            supplier_cap=5,
            horizon=2,
            scheduled_arrival_interval=1,
        )
        engine = MarketEngine(market_config)
        engine.reset(43, failure_probabilities=[0, 0, 0, 0])

        first = engine.step([0, 1, 2, 3])
        self.assertEqual(
            [item.supplier_id for item in first.observation.suppliers],
            [0, 1, 2, 3, 4],
        )

        second = engine.step([0, 1, 2, 3])
        self.assertEqual(len(second.observation.suppliers), 5)

    def test_scheduled_arrival_and_emergency_replenishment_share_unique_ids(
        self,
    ) -> None:
        market_config = config(
            initial_supplier_count=4,
            supplier_cap=5,
            initial_stake=2,
            horizon=1,
            scheduled_arrival_interval=1,
        )
        engine = MarketEngine(market_config)
        engine.reset(47, failure_probabilities=[1, 1, 1, 1])

        step = engine.step([0, 1, 2, 3])

        self.assertEqual(
            [item.supplier_id for item in step.observation.suppliers],
            [4, 5, 6, 7],
        )
        all_suppliers = engine._private_suppliers_for_qa()
        self.assertEqual([item.supplier_id for item in all_suppliers], list(range(8)))

    def test_replay_survives_invalid_actions_and_replenishment(self) -> None:
        market_config = config(initial_stake=2, horizon=3)
        left = MarketEngine(market_config)
        right = MarketEngine(market_config)
        left.reset(53, failure_probabilities=[1, 1, 1, 1])
        right.reset(53, failure_probabilities=[1, 1, 1, 1])

        left.step([0, 0, 1, 2])
        for engine in (left, right):
            engine.step([0, 1, 2, 3])
            engine.step([4, 5, 6, 7])
            engine.step([4, 5, 6, 7])

        self.assertEqual(left.observe().history, right.observe().history)
        self.assertEqual(
            left._private_suppliers_for_qa(),
            right._private_suppliers_for_qa(),
        )


if __name__ == "__main__":
    unittest.main()
