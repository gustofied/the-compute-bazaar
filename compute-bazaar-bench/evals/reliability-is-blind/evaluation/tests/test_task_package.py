from __future__ import annotations

from pathlib import Path
import tomllib
import unittest


EVAL_ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = EVAL_ROOT / "harbor"


class HarborTaskPackageTests(unittest.TestCase):
    def test_one_normal_harbor_agent_run_has_no_workflow_steps(self) -> None:
        task_text = (TASK_ROOT / "task.toml").read_text()
        task = tomllib.loads(task_text)

        self.assertNotIn("steps", task)
        self.assertNotIn("[[steps]]", task_text)
        self.assertEqual(task["task"]["name"], "gustofied/reliability-is-blind")
        self.assertEqual(
            task["artifacts"],
            [{"source": "/market-artifacts/state.json", "service": "market"}],
        )
        self.assertEqual(task["verifier"]["environment_mode"], "separate")
        self.assertEqual(task["verifier"]["environment"]["network_mode"], "no-network")

    def test_sidecar_and_verifier_use_exact_frozen_engine_copies(self) -> None:
        canonical = (
            EVAL_ROOT / "evaluation" / "reliability_is_blind" / "engine.py"
        ).read_bytes()
        sidecar = (
            TASK_ROOT / "environment" / "market-sidecar" / "market_engine.py"
        ).read_bytes()
        verifier = (TASK_ROOT / "tests" / "market_engine.py").read_bytes()

        self.assertEqual(sidecar, canonical)
        self.assertEqual(verifier, sidecar)

    def test_compose_keeps_the_market_out_of_the_agent_filesystem(self) -> None:
        compose = (TASK_ROOT / "environment" / "docker-compose.yaml").read_text()
        main_image = (TASK_ROOT / "environment" / "Dockerfile").read_text()

        for unsafe_key in ("volumes:", "ports:", "privileged:", "cap_add:"):
            self.assertNotIn(unsafe_key, compose)
        self.assertNotIn("market_engine.py", main_image)
        self.assertNotIn("market-sidecar", main_image)

    def test_instruction_is_the_minimal_broker_contract(self) -> None:
        lines = (TASK_ROOT / "instruction.md").read_text().splitlines()

        self.assertEqual(len(lines), 5)
        self.assertIn("100 compute deals", lines[0])
        self.assertIn("market status", lines[1])
        self.assertIn("four eligible suppliers", lines[2])
        self.assertIn("at or below 5%", lines[3])
        self.assertIn("market status", lines[4])


if __name__ == "__main__":
    unittest.main()
