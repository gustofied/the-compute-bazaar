from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from the_compute_bazaar.terminal.commands import (
    ErrorAction,
    ShellAction,
    SqlAction,
    resolve_command,
)
from the_compute_bazaar.terminal.server import TerminalLaunchMailbox
from the_compute_bazaar.terminal.shell import TerminalShell


class TerminalCommandTest(unittest.TestCase):
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
