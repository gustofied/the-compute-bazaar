from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from the_compute_bazaar.terminal.commands import (
    LaunchPlanAction,
    ErrorAction,
    OffersAction,
    NavigateAction,
    QueryAction,
    ShellAction,
    SqlAction,
    resolve_command,
)
from the_compute_bazaar.terminal.eval_workspace import EvalWorkspace
from the_compute_bazaar.terminal.lifecycle import _resolve_evaluation_root
from the_compute_bazaar.terminal.server import TerminalLaunchMailbox
from the_compute_bazaar.terminal.shell import TerminalShell


class TerminalCommandTest(unittest.TestCase):
    def test_terminal_stays_available_without_an_eval_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bench_root = Path(directory)
            evaluation_root = bench_root / "jobs" / "reports"
            (bench_root / "viewer").mkdir()
            (bench_root / "viewer" / "app.py").touch()
            module = SimpleNamespace(create_app=lambda *_args, **_kwargs: None)

            with patch(
                "the_compute_bazaar.terminal.eval_workspace.importlib.import_module",
                return_value=module,
            ):
                workspace = EvalWorkspace.load(evaluation_root)

        self.assertFalse(workspace.available)

    def test_relative_evaluation_root_is_project_relative(self) -> None:
        project_root = Path("/tmp/project")

        resolved = _resolve_evaluation_root(
            Path("compute-bazaar-bench/jobs/reports"), project_root
        )

        self.assertEqual(
            resolved,
            Path("/tmp/project/compute-bazaar-bench/jobs/reports").resolve(),
        )

    def test_unknown_commands_require_the_native_shell_boundary(self) -> None:
        command = "harbor run -p task"

        self.assertIsInstance(resolve_command(command), ErrorAction)
        action = resolve_command(command, shell_fallback=True)

        self.assertEqual(action, ShellAction(command=command))

    def test_sql_remains_a_first_class_terminal_action(self) -> None:
        action = resolve_command(
            "select * from gold.fact_gpu_price_index",
            shell_fallback=True,
        )

        self.assertIsInstance(action, SqlAction)

    def test_cli_prefixed_listings_open_as_native_data(self) -> None:
        action = resolve_command(
            "compute-bazaar listings --gpu-model H100 --limit 20",
            shell_fallback=True,
        )

        self.assertIsInstance(action, SqlAction)
        assert isinstance(action, SqlAction)
        self.assertEqual(action.limit, 20)
        self.assertIn("from gold.fact_gpu_listings", action.sql)
        self.assertIn("'H100'", action.sql)
        self.assertEqual(action.perspective, {"plugin": "Datagrid", "settings": False})

    def test_short_market_commands_use_the_same_native_path(self) -> None:
        short = resolve_command("listings --gpu-model H100 --limit 20")
        prefixed = resolve_command(
            "compute-bazaar listings --gpu-model H100 --limit 20"
        )

        self.assertEqual(short, prefixed)

    def test_offers_use_the_native_data_workspace(self) -> None:
        action = resolve_command(
            "compute-bazaar offers list --provider runpod --gpu-model H100 --limit 20",
            shell_fallback=True,
        )

        self.assertEqual(
            action,
            OffersAction(provider="runpod", gpu_model="H100", limit=20),
        )

    def test_offer_inspection_preserves_the_offer_id(self) -> None:
        action = resolve_command("offers inspect verda:abc123")

        self.assertEqual(action, OffersAction(offer_id="verda:abc123"))

    def test_launch_plan_stays_a_native_non_shell_action(self) -> None:
        action = resolve_command(
            "compute-bazaar launch plan runpod:abc123 "
            "--name gpu-01 --image runpod/pytorch:latest --disk-gb 80",
            shell_fallback=True,
        )

        self.assertEqual(
            action,
            LaunchPlanAction(
                offer_id="runpod:abc123",
                name="gpu-01",
                image="runpod/pytorch:latest",
                disk_gb=80,
            ),
        )

    def test_launch_plan_accepts_shell_style_line_continuations(self) -> None:
        action = resolve_command(
            "launch plan runpod:abc123 \\\n"
            "  --name gpu-01 \\\n"
            "  --image runpod/pytorch:latest"
        )

        self.assertEqual(
            action,
            LaunchPlanAction(
                offer_id="runpod:abc123",
                name="gpu-01",
                image="runpod/pytorch:latest",
            ),
        )

    def test_launch_plan_requires_the_provider_qualified_offer_id(self) -> None:
        action = resolve_command("launch plan abc123")

        self.assertIsInstance(action, ErrorAction)
        assert isinstance(action, ErrorAction)
        self.assertIn("complete offer ID", action.message)

    def test_terminal_only_cli_flags_are_removed_from_native_queries(self) -> None:
        action = resolve_command(
            "compute-bazaar query gpu_price_index_history --terminal --limit 40"
        )

        self.assertEqual(
            action,
            QueryAction(query_id="gpu_price_index_history", limit=40),
        )

    def test_cli_chart_options_become_a_perspective_layout(self) -> None:
        action = resolve_command(
            'compute-bazaar sql "select observed_at, price from gold.example" '
            "--terminal --chart line --x observed_at --y price"
        )

        self.assertIsInstance(action, SqlAction)
        assert isinstance(action, SqlAction)
        self.assertEqual(action.sql, "select observed_at, price from gold.example")
        self.assertEqual(
            action.perspective,
            {
                "plugin": "Y Line",
                "group_by": ["observed_at"],
                "columns": ["price"],
                "settings": False,
            },
        )

    def test_external_commands_still_use_the_shell(self) -> None:
        action = resolve_command("harbor run -p task", shell_fallback=True)

        self.assertEqual(action, ShellAction(command="harbor run -p task"))

    def test_fleet_opens_the_workspace_and_operations_use_the_shell(self) -> None:
        self.assertEqual(resolve_command("fleet"), NavigateAction(href="/fleet"))
        self.assertEqual(
            resolve_command("fleet inspect runpod:pod-123", shell_fallback=True),
            ShellAction(command="compute-bazaar fleet inspect runpod:pod-123"),
        )

    def test_unknown_prefixed_commands_do_not_recurse_into_the_shell(self) -> None:
        action = resolve_command("compute-bazaar listngs", shell_fallback=True)

        self.assertIsInstance(action, ErrorAction)

    def test_runtime_launch_mailbox_retains_one_typed_action(self) -> None:
        mailbox = TerminalLaunchMailbox()
        action = SqlAction(
            sql="select * from gold.fact_gpu_price_index",
            limit=20,
            perspective={"plugin": "Y Line"},
        )

        published = mailbox.publish(action)

        self.assertEqual(mailbox.latest(), published)
        self.assertEqual(published["action"]["kind"], "sql")
        self.assertEqual(published["action"]["perspective"], {"plugin": "Y Line"})


class TerminalShellTest(unittest.TestCase):
    def test_shell_keeps_repository_state_between_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            resolved_directory = Path(directory).resolve()
            shell = TerminalShell(cwd=resolved_directory, shell="/bin/sh")
            try:
                shell.submit("printf 'first:%s\\n' \"$PWD\"")
                self._wait_for(shell, f"first:{resolved_directory}")
                shell.submit("cd / && printf 'second:%s\\n' \"$PWD\"")
                self._wait_for(shell, "second:/")
                shell.submit("printf 'third:%s\\n' \"$PWD\"")
                output = self._wait_for(shell, "third:/")
            finally:
                shell.close()

        self.assertIn("first:", output)
        self.assertIn("second:/", output)
        self.assertIn("third:/", output)

    @staticmethod
    def _wait_for(shell: TerminalShell, expected: str) -> str:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            output = str(shell.snapshot()["output"])
            if expected in output:
                return output
            time.sleep(0.02)
        raise AssertionError(f"PTY output did not contain {expected!r}: {output!r}")


if __name__ == "__main__":
    unittest.main()
