"""One native-only PTY shared by the Terminal workspaces."""

from __future__ import annotations

import codecs
import errno
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
from pathlib import Path
from threading import Condition, Lock, Thread
from typing import Any


MAX_COMMAND_LENGTH = 20_000
MAX_OUTPUT_CHARS = 2_000_000


class TerminalShellError(RuntimeError):
    """Raised when the local PTY cannot accept an operation."""


class TerminalShell:
    """Keep one interactive login shell alive across page navigation."""

    def __init__(self, *, cwd: Path, shell: str | None = None) -> None:
        self.cwd = cwd.resolve()
        self.shell = shell or os.environ.get("SHELL") or "/bin/zsh"
        self._condition = Condition(Lock())
        self._process: subprocess.Popen[bytes] | None = None
        self._master_fd: int | None = None
        self._output = ""
        self._base_cursor = 0
        self._state_version = 0
        self._exit_code: int | None = None

    def submit(self, command: str, *, columns: int = 120, rows: int = 32) -> None:
        command = command.strip()
        if not command:
            raise TerminalShellError("Shell command is empty")
        if len(command) > MAX_COMMAND_LENGTH:
            raise TerminalShellError("Shell command is too long")
        if "\x00" in command:
            raise TerminalShellError("Shell command contains a null byte")
        with self._condition:
            if not self._active_locked():
                self._start_locked(columns=columns, rows=rows)
            assert self._master_fd is not None
            try:
                os.write(self._master_fd, f"{command}\n".encode())
            except OSError as exc:
                raise TerminalShellError("Shell input is unavailable") from exc

    def open(self, *, columns: int = 120, rows: int = 32) -> None:
        """Start the shared shell without submitting a command."""
        with self._condition:
            if not self._active_locked():
                self._start_locked(columns=columns, rows=rows)

    def interrupt(self) -> None:
        with self._condition:
            pid = self._process.pid if self._active_locked() else None
        if pid is None:
            return
        try:
            os.killpg(pid, signal.SIGINT)
        except ProcessLookupError:
            return

    def resize(self, *, columns: int, rows: int) -> None:
        columns = max(20, min(columns, 500))
        rows = max(4, min(rows, 200))
        with self._condition:
            master_fd = self._master_fd
            if master_fd is None:
                return
            self._resize_fd(master_fd, columns=columns, rows=rows)

    def clear(self) -> None:
        with self._condition:
            self._base_cursor += len(self._output)
            self._output = ""
            self._state_version += 1
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            pid = self._process.pid if self._active_locked() else None
        if pid is not None:
            try:
                os.killpg(pid, signal.SIGHUP)
            except ProcessLookupError:
                pass

    def snapshot(self, *, cursor: int | None = None) -> dict[str, Any]:
        with self._condition:
            active = self._active_locked()
            end_cursor = self._base_cursor + len(self._output)
            reset = cursor is None or cursor < self._base_cursor or cursor > end_cursor
            start = 0 if reset else cursor - self._base_cursor
            return {
                "type": "snapshot",
                "active": active,
                "command_ready": active,
                "cwd": str(self.cwd),
                "pid": self._process.pid if active and self._process else None,
                "exit_code": None if active else self._exit_code,
                "cursor": end_cursor,
                "state_version": self._state_version,
                "reset": reset,
                "output": self._output[start:],
            }

    def wait_for_change(
        self,
        *,
        cursor: int,
        state_version: int,
        timeout: float = 0.5,
    ) -> dict[str, Any] | None:
        with self._condition:
            current_cursor = self._base_cursor + len(self._output)
            if current_cursor == cursor and self._state_version == state_version:
                self._condition.wait(timeout)
                current_cursor = self._base_cursor + len(self._output)
            if current_cursor == cursor and self._state_version == state_version:
                return None
        return self.snapshot(cursor=cursor)

    def _start_locked(self, *, columns: int, rows: int) -> None:
        master_fd, slave_fd = pty.openpty()
        environment = os.environ.copy()
        environment.update(
            {
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "COMPUTE_BAZAAR_TERMINAL": "1",
            }
        )
        try:
            process = subprocess.Popen(
                [self.shell, "-l", "-i"],
                cwd=self.cwd,
                env=environment,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            os.close(slave_fd)
        self._process = process
        self._master_fd = master_fd
        self._exit_code = None
        self._resize_fd(master_fd, columns=columns, rows=rows)
        self._state_version += 1
        Thread(
            target=self._read_output,
            args=(process, master_fd),
            name="compute-bazaar-terminal-pty",
            daemon=True,
        ).start()

    def _read_output(
        self,
        process: subprocess.Popen[bytes],
        master_fd: int,
    ) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            try:
                payload = os.read(master_fd, 65_536)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                payload = b""
            if not payload:
                break
            self._append(decoder.decode(payload))
        self._append(decoder.decode(b"", final=True))
        exit_code = process.wait()
        try:
            os.close(master_fd)
        except OSError:
            pass
        with self._condition:
            if self._process is process:
                self._process = None
                self._master_fd = None
                self._exit_code = exit_code
                self._state_version += 1
                self._condition.notify_all()

    def _append(self, value: str) -> None:
        if not value:
            return
        with self._condition:
            self._output += value
            overflow = len(self._output) - MAX_OUTPUT_CHARS
            if overflow > 0:
                self._output = self._output[overflow:]
                self._base_cursor += overflow
            self._condition.notify_all()

    def _active_locked(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @staticmethod
    def _resize_fd(fd: int, *, columns: int, rows: int) -> None:
        size = struct.pack("HHHH", rows, columns, 0, 0)
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
        except OSError:
            return
