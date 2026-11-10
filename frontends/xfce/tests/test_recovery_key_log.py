"""The recovery key does not reach the install log (#337).

fisherman prints the TPM recovery key in its output. This frontend wrote
each line of that output to ~/.local/state/tuna-installer/install.log, so
the key stayed in a file that a user attaches to a bug report. Each line
now goes through bootc_shared.redact before it reaches the file.

shared/progress/recovery-key-cases.json has the key, the redacted form of
the event and the single-line cases; recovery-key-transcript.ndjson is a
short install with one `recovery_key` event. KDE reads the same files.
"""

import json
import os
import pathlib

import gi
import pytest

gi.require_version("Gtk", "3.0")
from bootc_shared import redact  # noqa: E402
from gi.repository import GLib  # noqa: E402

from tuna_installer_xfce import app, core, pages  # noqa: E402

PROGRESS = pathlib.Path(__file__).resolve().parents[3] / "shared" / "progress"
SPEC = json.loads((PROGRESS / "recovery-key-cases.json").read_text(encoding="utf-8"))
KEY = SPEC["key"]
TRANSCRIPT = (PROGRESS / SPEC["transcript"]).read_text(encoding="utf-8").splitlines(keepends=True)


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return pathlib.Path(core.install_log_path())


def test_the_placeholder_is_the_shared_one():
    assert redact.REDACTED == SPEC["placeholder"]


def test_the_transcript_goes_to_the_file_without_the_key(log_file):
    log = core.open_install_log()
    for line in TRANSCRIPT:
        log.write(line)
    log.close()
    text = log_file.read_text(encoding="utf-8")
    assert KEY not in text
    want = "".join((SPEC["redacted_event"] + "\n") if '"recovery_key"' in line else line
                   for line in TRANSCRIPT)
    assert text == want, "each other line must be unchanged"
    assert os.stat(log_file).st_mode & 0o777 == 0o600


@pytest.mark.parametrize("case", SPEC["lines"], ids=lambda case: case["name"])
def test_each_line_case(case, log_file):
    log = core.open_install_log()
    if case["known_key"]:
        # The event came first: the writer knows the key from it.
        log.write(json.dumps({"type": "recovery_key", "key": KEY}) + "\n")
    written = log.write(case["line"] + "\n")
    log.close()
    assert written == case["redacted"] + "\n"
    assert log_file.read_text(encoding="utf-8").endswith(case["redacted"] + "\n")


def test_a_line_that_repeats_the_key_after_the_event_loses_it(log_file):
    log = core.open_install_log()
    log.write(TRANSCRIPT[3])
    log.write(f"[stderr] enrolled slot 1 with {KEY}.\n")
    log.write(f"Recovery key: {KEY}\n")
    log.close()
    assert KEY not in log_file.read_text(encoding="utf-8")


class _Channel:
    def __init__(self, lines):
        self.lines = list(lines)

    def read_line(self):
        # The window reads every complete line that is there, then stops
        # at the end of what the pipe has.
        if not self.lines:
            return GLib.IOStatus.EOF, "", 0, 0
        return GLib.IOStatus.NORMAL, self.lines.pop(0), 0, 0


class _Page:
    def __init__(self):
        self.seen = []

    def append_log(self, text):
        self.seen.append(text)


class _Window:
    """What InstallerWindow._on_output reads of the window."""

    _read_lines = app.InstallerWindow._read_lines

    def __init__(self):
        self._log_tail = []
        self._install_log = core.open_install_log()


def test_the_real_output_handler_keeps_the_key_out_of_the_file_and_the_tail(log_file):
    """InstallerWindow._on_output is the one place fisherman's lines enter
    the app. Drive it with the transcript, as the pipes would."""
    window, page, channel = _Window(), _Page(), _Channel(TRANSCRIPT)
    for _line in TRANSCRIPT:
        assert app.InstallerWindow._on_output(window, channel, GLib.IO_IN, page) is True
    window._install_log.close()
    assert KEY not in log_file.read_text(encoding="utf-8")
    assert SPEC["redacted_event"] in log_file.read_text(encoding="utf-8")
    # The tail is what a failed install shows on the result page.
    assert KEY not in "".join(window._log_tail)
    # The page still gets fisherman's line: it reads the key from the event
    # for the recovery-key panel.
    assert page.seen == TRANSCRIPT


def test_the_page_shows_the_key_on_the_panel_and_not_in_the_log_pane():
    page = pages.ProgressPage(type("Win", (), {"trawl": type("T", (), {
        "set_fill": lambda self, value: None})()})())
    for line in TRANSCRIPT:
        page.append_log(line)
    page.append_log(f"[stderr] enrolled slot 1 with {KEY}.\n")
    assert page.recovery_key() == KEY
    buf = page.logview.get_buffer()
    shown = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    assert KEY not in shown
    assert "Recovery key: " + SPEC["placeholder"] in shown


def test_no_code_writes_fishermans_output_to_a_file_but_the_redacting_log():
    """A second writer would bring the key back. The install log is opened
    in one function, and the window writes fisherman's lines only through
    the object that function returns."""
    package = pathlib.Path(core.__file__).parent
    source = (package / "app.py").read_text(encoding="utf-8")
    assert "self._install_log.write(text)" in source
    assert source.count("core.open_install_log()") == 1
    for module in package.glob("*.py"):
        text = module.read_text(encoding="utf-8")
        if module.name != "core.py":
            assert "install.log" not in text and "INSTALL_LOG_FILE_NAME" not in text, module.name
    assert isinstance(core.open_install_log.__doc__, str)
