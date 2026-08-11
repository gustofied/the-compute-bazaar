from __future__ import annotations

import ast
import hashlib
import json
import operator
from pathlib import Path
import sys
import unittest

TOOLING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLING_ROOT))

from reliability_is_blind.engine import (  # noqa: E402
    UPSTREAM_REVISION,
    MarketConfig,
    MarketEngine,
    _keyed_uniform,
)


UPSTREAM_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "upstream-98adffaa"
PINNED_REVISION = "98adffaa7931c74cdd749cde230b7e87c9d45d86"
EXPECTED_UPSTREAM_BLOBS = {
    "LICENSE": "da6ab6cc8f333d7e89a99812866df8f24374d47c",
    "coll_SR.py": "eb753a1dfcdb40feae0f6e86d859443e4a7dd4e8",
    "marketplace.py": "3d1cc291517424e75151c382a4dc5ee0568ca084",
    "run_marketplace.py": "7fa1cf1fa0cffce7c85a704ac13cf30707b9bb67",
}
EXPECTED_AUTHORS = [
    "Henry Mont",
    "Matthieu Bettinger",
    "Sonia Ben Mokhtar",
    "Anthony Simonet-Boulogne",
]


def _numeric_constants(path: Path) -> dict[str, float]:
    """Read upstream numeric assignments without importing its plotting stack."""

    binary_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
    }
    values: dict[str, float] = {}

    def evaluate(node: ast.expr) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in binary_operators:
            return binary_operators[type(node.op)](
                evaluate(node.left), evaluate(node.right)
            )
        raise ValueError(f"unsupported numeric expression: {ast.dump(node)}")

    for statement in ast.parse(path.read_text()).body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            try:
                values[statement.targets[0].id] = evaluate(statement.value)
            except (KeyError, ValueError):
                pass
    return values


class PinnedUpstreamParityTests(unittest.TestCase):
    def test_fixture_provenance_and_integrity(self) -> None:
        provenance = json.loads((UPSTREAM_FIXTURE / "PROVENANCE.json").read_text())

        self.assertEqual(provenance["source_revision"], PINNED_REVISION)
        self.assertEqual(
            provenance["source_repository"],
            "https://github.com/RedChainLab/Reliability-Is-Blind-Collective-Incentives",
        )
        self.assertEqual(provenance["authors"], EXPECTED_AUTHORS)
        self.assertEqual(provenance["license"]["spdx"], "CC-BY-4.0")
        self.assertEqual(
            provenance["license"]["url"],
            "https://creativecommons.org/licenses/by/4.0/",
        )

        fixture_files = provenance["files"]
        self.assertEqual(
            {
                name: metadata["upstream_git_blob"]
                for name, metadata in fixture_files.items()
            },
            EXPECTED_UPSTREAM_BLOBS,
        )
        for name, metadata in fixture_files.items():
            digest = hashlib.sha256((UPSTREAM_FIXTURE / name).read_bytes()).hexdigest()
            self.assertEqual(digest, metadata["fixture_sha256"], name)

        license_text = (UPSTREAM_FIXTURE / provenance["license"]["file"]).read_text()
        self.assertIn(
            "Creative Commons Attribution 4.0 International Public License",
            license_text,
        )
        notice = (UPSTREAM_FIXTURE / "NOTICE.md").read_text()
        self.assertIn(PINNED_REVISION, notice)
        for author in EXPECTED_AUTHORS:
            self.assertIn(author, notice)

    def test_paper_transition_constants_and_distribution_match(self) -> None:
        self.assertEqual(UPSTREAM_REVISION, PINNED_REVISION)

        coll_sr_source = (UPSTREAM_FIXTURE / "coll_SR.py").read_text()
        runner_source = (UPSTREAM_FIXTURE / "run_marketplace.py").read_text()
        constants = _numeric_constants(UPSTREAM_FIXTURE / "marketplace.py")

        # Source fingerprints make the independently calculated expectations below
        # fail if the pinned reproduction changes its Coll-SR equations.
        self.assertIn("asset.stake -= SLASH_AMOUNT", coll_sr_source)
        self.assertIn("asset.stake += REWARD_AMOUNT", coll_sr_source)
        self.assertIn(
            "asset.stake = max(min(asset.stake, MAX_REPUTATION), MIN_REPUTATION)",
            coll_sr_source,
        )
        self.assertIn(
            "to_remove = [asset for asset in assets if asset.stake <= SLASH_AMOUNT]",
            coll_sr_source,
        )
        self.assertIn("powerlaw.rvs(ALPHA, size=N_FAIL_SAMPLES)", runner_source)
        self.assertIn("FaultySet([asset], asset.failure_rate)", coll_sr_source)
        self.assertEqual(constants["NEW_ASSET_FAULTY_COMBOS"], 0)

        config = MarketConfig()
        self.assertEqual(config.deal_size, constants["N_MIN_ASSETS_TASK"])
        self.assertEqual(config.deal_size, constants["N_MAX_ASSETS_TASK"])
        self.assertEqual(config.initial_stake, constants["S0"])
        self.assertEqual(config.slash_amount, constants["SLASH_AMOUNT"])
        self.assertEqual(
            config.target_failure_rate, constants["TARGET_TASK_FAILURE_RATE"]
        )
        self.assertAlmostEqual(config.reward_amount, constants["REWARD_AMOUNT"])
        self.assertEqual(config.minimum_stake, constants["MIN_REPUTATION"])
        self.assertEqual(config.maximum_stake, constants["MAX_REPUTATION"])
        self.assertEqual(
            config.scheduled_arrival_interval, int(constants["NEW_ASSET_INTERVAL"])
        )
        self.assertEqual(config.failure_distribution_alpha, constants["ALPHA"])

        # scipy.stats.powerlaw(alpha) uses inverse CDF q ** (1 / alpha).
        # The port replaces upstream sampling with deterministic keyed uniforms,
        # but retains that same distribution exactly.
        engine = MarketEngine(
            MarketConfig(
                initial_supplier_count=4,
                supplier_cap=4,
                horizon=1,
                scheduled_arrival_interval=None,
            )
        )
        engine.reset(73)
        for supplier in engine._private_suppliers_for_qa():
            quantile = _keyed_uniform(
                version=engine.config.randomness_version,
                seed=73,
                domain="supplier-reliability",
                coordinates=(supplier.supplier_id,),
            )
            self.assertAlmostEqual(
                supplier.failure_probability,
                quantile ** (1.0 / constants["ALPHA"]),
            )

        # One certain individual failure must collectively slash every participant
        # once; the next delivered placement must apply the bounded paper reward.
        transition = MarketEngine(
            MarketConfig(
                initial_supplier_count=8,
                supplier_cap=8,
                horizon=2,
                scheduled_arrival_interval=None,
            )
        )
        transition.reset(79, failure_probabilities=[0, 1, 0, 0, 0, 0, 0, 0])
        failed = transition.step([0, 1, 2, 3])
        failed_stake = max(
            min(
                constants["S0"] - constants["SLASH_AMOUNT"],
                constants["MAX_REPUTATION"],
            ),
            constants["MIN_REPUTATION"],
        )
        self.assertFalse(failed.deal and failed.deal.delivered)
        self.assertTrue(
            all(
                supplier.stake == failed_stake
                for supplier in failed.observation.suppliers[:4]
            )
        )

        delivered = transition.step([0, 4, 5, 6])
        expected_recovered_stake = max(
            min(
                failed_stake + constants["REWARD_AMOUNT"],
                constants["MAX_REPUTATION"],
            ),
            constants["MIN_REPUTATION"],
        )
        stakes = {
            supplier.supplier_id: supplier.stake
            for supplier in delivered.observation.suppliers
        }
        self.assertTrue(delivered.deal and delivered.deal.delivered)
        self.assertAlmostEqual(stakes[0], expected_recovered_stake)


if __name__ == "__main__":
    unittest.main()
