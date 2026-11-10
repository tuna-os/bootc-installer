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


def test_the_last_lines_are_read_when_the_exit_comes_first(tmp_path, monkeypatch):
    """fisherman writes its BootNext line and `complete` and exits at once.
    The child watch can run before the output watch has read them. The exit
    handler then reads what is left: the log file and the page get the end
    of the stream."""
    from gi.repository import GLib

    from tuna_installer_xfce import app

    read, write = os.pipe()
    os.write(write, b'{"type":"info","message":"BootNext set to Boot0001"}\n'
                    b'{"type":"complete","message":"Installation complete!","overall_pct":100}\n')
    os.close(write)
    channel = GLib.IOChannel.unix_new(read)
    channel.set_flags(GLib.IOFlags.NONBLOCK)

    class Page:
        def __init__(self):
            self.lines = []

        def append_log(self, text):
            self.lines.append(text)

    class Window:
        _read_lines = app.InstallerWindow._read_lines
        _on_exit = app.InstallerWindow._on_exit
        _closing = False
        _cancel_requested = False
        _log_tail = []

        def _show_result(self, ok, cancelled=False):
            self.result = (ok, cancelled)

    page, window = Page(), Window()
    window._install_log = open(tmp_path / "install.log", "w")  # noqa: SIM115
    window._install_channels = [(channel, page)]
    monkeypatch.setattr(GLib, "spawn_close_pid", lambda _pid: None)
    window._on_exit(1234, 0)
    assert [line.split('"')[3] for line in page.lines] == ["info", "complete"]
    assert window.result == (True, False)
    log = (tmp_path / "install.log").read_text()
    assert '"type":"complete"' in log
    assert log.rstrip().endswith("=== fisherman exited: ok ===")
