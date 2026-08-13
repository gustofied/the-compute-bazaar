from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from the_compute_bazaar.analysis_store import AnalysisStore
from the_compute_bazaar.terminal.agents import (
    AgentSession,
    _agent_environment,
    _terminal_prompt,
)
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
from the_compute_bazaar.terminal.server import (
    TerminalLaunchMailbox,
    _validated_external_url,
)
from the_compute_bazaar.terminal.shell import TerminalShell


class TerminalCommandTest(unittest.TestCase):
    def test_agent_receives_the_terminal_data_contract(self) -> None:
        prompt = _terminal_prompt(
            "Show me the latest H200 price.", access="full"
        )

        self.assertIn("compute-bazaar tables", prompt)
        self.assertIn("compute-bazaar describe TABLE", prompt)
        self.assertIn("compute-bazaar query QUERY_ID --terminal", prompt)
        self.assertIn('compute-bazaar sql "SQL" --terminal', prompt)
        self.assertIn("ACP is the only Terminal integration", prompt)
        self.assertIn("Do not use MCP or GUI automation", prompt)
        self.assertIn("Bazaar checkout", prompt)
        self.assertNotIn("repo shell", prompt)
        self.assertTrue(prompt.endswith("Show me the latest H200 price."))
        self.assertEqual(_terminal_prompt("/login", access="read"), "/login")

    def test_read_agent_does_not_receive_shell_instructions(self) -> None:
        prompt = _terminal_prompt("Read the market.", access="read")

        self.assertIn("This turn has Read access", prompt)
        self.assertIn("ask the user to switch the Agent", prompt)
        self.assertIn("to Full access", prompt)
        self.assertNotIn("compute-bazaar tables", prompt)

    def test_agent_can_find_the_current_compute_bazaar_command(self) -> None:
        executable_dir = str(Path(sys.executable).parent)
        with patch.dict(
            os.environ,
            {
                "COMPUTE_BAZAAR_TERMINAL_NATIVE_TOKEN": "native-secret",
                "COMPUTE_BAZAAR_TERMINAL_CONTROL_TOKEN": "control-secret",
                "COMPUTE_BAZAAR_TERMINAL_PORT": "8767",
                "COMPUTE_BAZAAR_TERMINAL_READY_FILE": "/tmp/terminal-ready.json",
                "COMPUTE_BAZAAR_LAKE_ROOT": "/tmp/lake",
            },
        ):
            environment = _agent_environment()

        self.assertEqual(environment["PATH"].split(":", 1)[0], executable_dir)
        self.assertFalse(
            any(key.startswith("COMPUTE_BAZAAR_TERMINAL_") for key in environment)
        )
        self.assertEqual(environment["COMPUTE_BAZAAR_LAKE_ROOT"], "/tmp/lake")
        self.assertEqual(
            json.loads(environment["CODEX_CONFIG"]),
            {
                "model": "gpt-5.6-terra",
                "model_reasoning_effort": "medium",
            },
        )

    def test_agent_session_does_not_forward_mcp(self) -> None:
        session = AgentSession(
            cwd=Path("/repo"),
            executable=Path("/repo/terminal/node_modules/.bin/acpx"),
            agent_command="/repo/terminal/node_modules/.bin/codex-acp",
        )

        self.assertEqual(
            session._command(),
            [
                "/repo/terminal/node_modules/.bin/acpx",
                "--agent",
                "/repo/terminal/node_modules/.bin/codex-acp",
                "--cwd",
                "/repo",
                "--mcp-config",
                "/repo/terminal/acp.json",
            ],
        )

    def test_agent_client_has_no_mcp_servers(self) -> None:
        config = json.loads(
            (Path(__file__).parents[1] / "terminal" / "acp.json").read_text()
        )

        self.assertEqual(config, {"mcpServers": []})

    def test_agent_session_reads_raw_acp_updates(self) -> None:
        session = AgentSession(
            cwd=Path("/tmp"),
            executable=Path("/bin/false"),
            agent_command="codex-acp",
        )

        session._accept(
            {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "Hello"},
                    }
                },
            }
        )
        session._accept(
            {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": " there"},
                    }
                },
            }
        )

        self.assertEqual(len(session.events), 1)
        self.assertEqual(session.events[0]["text"], "Hello there")

    def test_agent_tool_updates_replace_the_existing_row(self) -> None:
        session = AgentSession(
            cwd=Path("/tmp"),
            executable=Path("/bin/false"),
            agent_command="codex-acp",
        )

        for update, status in (
            ("tool_call", "pending"),
            ("tool_call_update", "completed"),
        ):
            session._accept(
                {
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": update,
                            "toolCallId": "call-1",
                            "title": "Read file",
                            "status": status,
                        }
                    },
                }
            )

        self.assertEqual(len(session.events), 1)
        self.assertEqual(session.events[0]["status"], "completed")

    def test_slow_agent_listener_is_resynchronized_with_a_snapshot(self) -> None:
        session = AgentSession(
            cwd=Path("/tmp"),
            executable=Path("/bin/false"),
            agent_command="codex-acp",
        )
        queue = session.subscribe()

        for index in range(257):
            session._emit({"kind": "notice", "text": str(index)})

        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(queue.get_nowait(), session.snapshot())

    def test_agent_session_reads_normalized_text_events(self) -> None:
        session = AgentSession(
            cwd=Path("/tmp"),
            executable=Path("/bin/false"),
            agent_command="codex-acp",
        )

        session._accept({"type": "text_delta", "text": "Ready"})

        self.assertEqual(session.events[0]["text"], "Ready")

    def test_saved_analysis_tracks_fleet_and_uses_explicit_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AnalysisStore(Path(directory))
            model, blueprint = store.save_analysis(
                title="Fleet temperature",
                description="",
                markdown="# Fleet temperature\n\nGPU temperature by host.",
                sql="select * from fleet.telemetry",
                default_limit=100,
                viewer="perspective",
                viewer_config={"plugin": "Datagrid"},
            )
            stored = json.loads(
                (store.blueprints_root / f"{blueprint.blueprint_id}.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(model.tables, ("fleet.telemetry",))
        self.assertEqual(blueprint.viewer, "perspective")
        self.assertEqual(blueprint.viewer_config, {"plugin": "Datagrid"})
        self.assertEqual(
            blueprint.markdown,
            "# Fleet temperature\n\nGPU temperature by host.",
        )
        self.assertNotIn("perspective", stored)

    def test_external_links_are_https_without_embedded_credentials(self) -> None:
        url = "https://hub.harborframework.com/tasks/gustofied/task/latest"

        self.assertEqual(_validated_external_url(url), url)
        for invalid in (
            "http://example.com",
            "https://user:secret@example.com",
            "/relative/path",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(HTTPException):
                _validated_external_url(invalid)

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


class AgentProcessTest(unittest.IsolatedAsyncioTestCase):
    async def test_agent_session_crosses_the_process_boundary(self) -> None:
        fake_acpx = """
import json
import sys

if "prompt" in sys.argv:
    updates = (
        {
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "ACP ready"},
                }
            },
        },
        {
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "call-1",
                    "title": "Read market data",
                    "status": "pending",
                }
            },
        },
        {
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call-1",
                    "title": "Read market data",
                    "status": "completed",
                }
            },
        },
    )
    for update in updates:
        print(json.dumps(update), flush=True)
"""
        session = AgentSession(
            cwd=Path("/tmp"),
            executable=Path(sys.executable),
            agent_command="fake-acp-agent",
        )

        with patch.object(
            session,
            "_command",
            return_value=[sys.executable, "-c", fake_acpx],
        ):
            session.start("Read the market.", access="read")
            assert session._task is not None
            await session._task

        self.assertEqual(session.state, "idle")
        self.assertEqual(
            [(event["kind"], event.get("status")) for event in session.events],
            [
                ("message", None),
                ("message", None),
                ("tool", "completed"),
            ],
        )
        self.assertEqual(session.events[1]["text"], "ACP ready")


class TerminalShellTest(unittest.TestCase):
    def test_shell_can_open_without_submitting_a_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = TerminalShell(cwd=Path(directory), shell="/bin/sh")
            try:
                shell.open(columns=80, rows=20)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and not shell.snapshot()["active"]:
                    time.sleep(0.01)
                self.assertTrue(shell.snapshot()["active"])
            finally:
                shell.close()

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
