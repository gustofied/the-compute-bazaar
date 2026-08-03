from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from typing import Any

from tests import verify


TASK_ROOT = Path(__file__).resolve().parents[1]
SIDECAR_DIR = TASK_ROOT / "environment" / "market-sidecar"
CLI_PATH = TASK_ROOT / "environment" / "market_cli.py"
SNAPSHOT_PATH = SIDECAR_DIR / "snapshot.py"
SOLUTION_PATH = TASK_ROOT / "solution" / "solve.sh"


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _post_json(market_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{market_url}/v1",
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            parsed = json.loads(response.read(65_536))
    except urllib.error.HTTPError as exc:
        try:
            parsed = json.loads(exc.read(65_536))
        finally:
            exc.close()
    if not isinstance(parsed, dict):
        raise AssertionError("sidecar response must be a JSON object")
    return parsed


class SidecarIntegrationTests(unittest.TestCase):
    def test_public_cli_snapshot_and_offline_replay_share_one_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "state"
            artifact_dir = root / "artifacts"
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "market").symlink_to(CLI_PATH)
            port = _unused_port()
            market_url = f"http://127.0.0.1:{port}"
            environment = {
                **os.environ,
                "MARKET_STATE_DIR": str(state_dir),
                "MARKET_ARTIFACT_DIR": str(artifact_dir),
                "MARKET_SEED": "7",
                "MARKET_PORT": str(port),
                "MARKET_URL": market_url,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
            }
            process = subprocess.Popen(
                [sys.executable, str(SIDECAR_DIR / "server.py")],
                cwd=SIDECAR_DIR,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(
                            f"{market_url}/health", timeout=0.2
                        ) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.02)
                else:
                    stdout, stderr = process.communicate(timeout=1)
                    self.fail(f"sidecar did not start: {stdout}\n{stderr}")

                status = subprocess.run(
                    [sys.executable, str(CLI_PATH), "status", "--json"],
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                public_state = json.loads(status.stdout)
                self.assertEqual(len(public_state["suppliers"]), 20)
                self.assertNotIn("seed", public_state)
                self.assertNotIn("failure_probability", status.stdout)

                artifact_path = artifact_dir / "state.json"
                unauthorized = _post_json(
                    market_url,
                    {"action": "snapshot", "snapshot_token": "not-the-token"},
                )
                self.assertFalse(unauthorized["ok"])
                self.assertEqual(
                    unauthorized["error"], "snapshot authentication failed"
                )
                self.assertFalse(artifact_path.exists())

                oracle = subprocess.run(
                    ["sh", str(SOLUTION_PATH)],
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertIn("Completion: 1", oracle.stdout)
                self.assertIn("Reliability target met:", oracle.stdout)
                self.assertNotIn("SLA met", oracle.stdout)
                subprocess.run(
                    [sys.executable, str(SNAPSHOT_PATH)],
                    cwd=SIDECAR_DIR,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                )

                frozen_artifact = artifact_path.read_bytes()
                snapshot_token = (state_dir / "snapshot-token").read_text().strip()

                repeated_snapshot = _post_json(
                    market_url,
                    {"action": "snapshot", "snapshot_token": snapshot_token},
                )
                self.assertFalse(repeated_snapshot["ok"])
                self.assertEqual(
                    repeated_snapshot["error"], "market state is already finalized"
                )

                mutation = _post_json(
                    market_url,
                    {"action": "select", "supplier_ids": [0, 1, 2, 3]},
                )
                self.assertFalse(mutation["ok"])
                self.assertEqual(mutation["error"], "market state is finalized")
                self.assertEqual(artifact_path.read_bytes(), frozen_artifact)

                artifact, digest = verify.load_artifact(artifact_path)
                metrics, evidence = verify.verify_artifact(
                    artifact, artifact_sha256=digest
                )
                self.assertEqual(metrics["completion"], 1)
                self.assertEqual(metrics["completed_deals"], 100)
                self.assertEqual(evidence["replayed_deals"], 100)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()
