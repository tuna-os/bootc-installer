"""fisherman's wrapper starts in a process group of its own.

fisherman runs as root, so the wrapper is the only process of the install
this user can signal, and fisherman cancels when that parent dies
(tuna-os/fisherman#267). The shared contract is "kill your wrapper's
process group"; that is only safe if the group is not the installer's.
"""

import os
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import app  # noqa: E402


def test_wrapper_leads_its_own_process_group():
    pid, out, err = app.spawn_fisherman(["sleep", "30"])
    try:
        assert os.getpgid(pid) == pid
        assert os.getpgid(pid) != os.getpgrp()
        # Signalling that group reaches the wrapper and not this process.
        os.killpg(pid, signal.SIGTERM)
        _, status = os.waitpid(pid, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGTERM
    finally:
        for fd in (out, err):
            os.close(fd)
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass


def test_wrapper_output_still_reaches_the_pipes():
    pid, out, err = app.spawn_fisherman(
        ["sh", "-c", 'echo \'{"type":"info"}\'; echo oops >&2'])
    try:
        _, status = os.waitpid(pid, 0)
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
        assert os.read(out, 4096) == b'{"type":"info"}\n'
        assert os.read(err, 4096) == b"oops\n"
    finally:
        for fd in (out, err):
            os.close(fd)
