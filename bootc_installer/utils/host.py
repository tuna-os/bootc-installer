"""One host execution layer for the GNOME frontend (#82).

Every command that the installer runs outside the fisherman pipeline goes
through `HostExecutor.run`. The executor chooses the argv for the scope of
the command and returns a `HostResult`; it never raises for a failed,
missing, timed-out or cancelled command.

Scopes:

- `Scope.LOCAL`: run in this process's environment. In a Flatpak, that is
  the sandbox.
- `Scope.HOST`: run on the host as the user. In a Flatpak, the argv gets
  `flatpak-spawn --host` in front; outside a Flatpak, it runs as is.
- `Scope.ELEVATED`: run on the host as root through `pkexec`, with
  `flatpak-spawn --host` in front in a Flatpak.

`run` waits for the command; `spawn` starts it and returns at once, for a
settings window or another app that keeps running.

The command is always an argv list. The executor never builds a shell
string. `command_exists` uses one constant `sh` script and gives the name as
a positional argument, so a name cannot change the script.

Timeouts in a Flatpak: on a timeout or a cancel, `run` kills the process
it started. In a Flatpak that is `flatpak-spawn`, and the command on the
host keeps running. So a command that must not stop halfway, or that ends
the session (reboot, poweroff, firmware setup), gets `timeout=None`.

This module does not import GTK. The fisherman launch path stays in
`fisherman_runner.py` and `fisherman_session.py`.
"""

from __future__ import annotations

import enum
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger("Installer::Host")

IN_FLATPAK = os.path.exists("/.flatpak-info")

# How often `run` looks at the cancel event while the command runs.
_POLL_SECONDS = 0.05

# The script for `command_exists`. The name is "$1", never part of the text.
_COMMAND_V = 'command -v -- "$1"'


class Scope(enum.Enum):
    LOCAL = "local"
    HOST = "host"
    ELEVATED = "elevated"


@dataclass(frozen=True)
class HostResult:
    """What a host command did.

    `returncode` is None when the command did not finish: it was not found,
    it timed out or it was cancelled. It is also None after `spawn`, which
    does not wait; then `started` says whether the process started.
    `missing_command` is True when the program to execute (the command, or
    `flatpak-spawn` in a Flatpak) does not exist on this side of the sandbox.
    """

    argv: tuple
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    missing_command: bool = False
    cancelled: bool = False
    started: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def describe(self) -> str:
        """One line for the log."""
        if self.missing_command:
            return f"{self.argv[0]}: command not found"
        if self.timed_out:
            return f"{' '.join(self.argv)}: timed out"
        if self.cancelled:
            return f"{' '.join(self.argv)}: cancelled"
        if self.started:
            return f"{' '.join(self.argv)}: started"
        detail = self.stderr.strip().splitlines()[-1:] or [""]
        return f"{' '.join(self.argv)}: exit {self.returncode} {detail[0]}".rstrip()


def build_argv(cmd, scope: Scope, *, in_flatpak: bool) -> list:
    """The argv that runs `cmd` in `scope`."""
    if isinstance(cmd, (str, bytes)):
        raise TypeError("host commands are argv lists, not shell strings")
    argv = [str(part) for part in cmd]
    if not argv:
        raise ValueError("empty host command")
    if not isinstance(scope, Scope):
        raise TypeError(f"unknown scope: {scope!r}")
    if scope is Scope.LOCAL:
        return argv
    if scope is Scope.ELEVATED:
        argv = ["pkexec"] + argv
    if in_flatpak:
        argv = ["flatpak-spawn", "--host"] + argv
    return argv


class HostExecutor:
    """Run argv commands natively or from a Flatpak, with typed results."""

    def __init__(self, *, in_flatpak: bool | None = None, popen=subprocess.Popen):
        self.in_flatpak = IN_FLATPAK if in_flatpak is None else in_flatpak
        self._popen = popen

    def argv(self, cmd, scope: Scope = Scope.HOST) -> list:
        return build_argv(cmd, scope, in_flatpak=self.in_flatpak)

    def run(
        self,
        cmd,
        *,
        scope: Scope = Scope.HOST,
        timeout: float | None = 10,
        cancel: threading.Event | None = None,
        input_text: str | None = None,
    ) -> HostResult:
        """Run `cmd` and wait for it, the timeout or the cancel event.

        The command gets no stdin unless `input_text` is given. On a timeout
        or a cancel, the process is killed and the result says which.
        """
        argv = self.argv(cmd, scope)
        key = tuple(argv)
        if cancel is not None and cancel.is_set():
            return HostResult(key, None, cancelled=True)
        try:
            proc = self._popen(
                argv,
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            return HostResult(key, None, missing_command=True)
        except OSError as error:
            return HostResult(key, None, stderr=str(error))

        deadline = None if timeout is None else time.monotonic() + timeout
        pending_input = input_text
        while True:
            wait = _POLL_SECONDS if cancel is not None else None
            if deadline is not None:
                left = max(0.0, deadline - time.monotonic())
                wait = left if wait is None else min(wait, left)
            try:
                out, err = proc.communicate(input=pending_input, timeout=wait)
                return HostResult(key, proc.returncode, out or "", err or "")
            except subprocess.TimeoutExpired:
                # communicate() wrote the input already; never send it twice.
                pending_input = None
            if cancel is not None and cancel.is_set():
                out, err = _kill(proc)
                return HostResult(key, None, out, err, cancelled=True)
            if deadline is not None and time.monotonic() >= deadline:
                out, err = _kill(proc)
                return HostResult(key, None, out, err, timed_out=True)

    def spawn(self, cmd, *, scope: Scope = Scope.HOST) -> HostResult:
        """Start `cmd` and do not wait for it.

        The process gets no stdin, its output goes nowhere, and it leads its
        own session, so it outlives a closed installer window. `started` is
        True when it started. In a Flatpak this only says that
        `flatpak-spawn` started: a command missing on the host is not seen.
        """
        argv = self.argv(cmd, scope)
        key = tuple(argv)
        try:
            self._popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            return HostResult(key, None, missing_command=True)
        except OSError as error:
            return HostResult(key, None, stderr=str(error))
        return HostResult(key, None, started=True)

    def command_exists(self, name: str, *, scope: Scope = Scope.HOST,
                       timeout: float | None = 3) -> HostResult:
        """Whether `name` is on the PATH of `scope`. `.ok` means found."""
        return self.run(["sh", "-c", _COMMAND_V, "sh", name], scope=scope, timeout=timeout)


def _kill(proc):
    proc.kill()
    try:
        out, err = proc.communicate(timeout=5)
    except (subprocess.TimeoutExpired, ValueError):
        out, err = "", ""
    return out or "", err or ""


_DEFAULT = None


def default_executor() -> HostExecutor:
    """The process-wide executor (native or Flatpak from /.flatpak-info)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = HostExecutor()
    return _DEFAULT
