"""Cancel-on-exit and --autoinstall (app.py).

- terminate_process_group() SIGTERMs the wrapper's group, like GNOME's
  BootcProgress.terminate, and tolerates dead or missing pids.
- _load_autoinstall_recipe() reads a JSON object or returns None.
- parse_argv() splits --autoinstall/-a out before GTK sees the argv.
- The window without a running install closes normally (no dialog).
"""

import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import app  # noqa: E402


def test_terminate_kills_the_wrapper_group():
    pid, out, err = app.spawn_fisherman(["sleep", "30"])
    try:
        assert os.getpgid(pid) == pid
        app.terminate_process_group(pid)
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.05)
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


def test_terminate_tolerates_dead_and_missing_pids():
    app.terminate_process_group(None)
    app.terminate_process_group(0)
    app.terminate_process_group(2 ** 30)  # nothing lives here


def test_load_autoinstall_recipe(tmp_path):
    good = tmp_path / "recipe.json"
    good.write_text(json.dumps({"disk": "/dev/vda"}))
    assert app.InstallerWindow._load_autoinstall_recipe(str(good)) == {
        "disk": "/dev/vda"}
    missing = tmp_path / "absent.json"
    assert app.InstallerWindow._load_autoinstall_recipe(str(missing)) is None
    broken = tmp_path / "broken.json"
    broken.write_text("{nope")
    assert app.InstallerWindow._load_autoinstall_recipe(str(broken)) is None
    array = tmp_path / "array.json"
    array.write_text("[1, 2]")
    assert app.InstallerWindow._load_autoinstall_recipe(str(array)) is None


def test_parse_argv():
    auto, rest = app.parse_argv(["--autoinstall", "r.json", "--g-fatal-warnings"])
    assert auto == "r.json"
    assert rest == ["--g-fatal-warnings"]
    auto, rest = app.parse_argv(["-a", "r.json"])
    assert auto == "r.json" and rest == []
    auto, rest = app.parse_argv(["--autoinstall=r.json"])
    assert auto == "r.json" and rest == []
    auto, rest = app.parse_argv([])
    assert auto is None and rest == []


def test_window_without_install_closes_normally():
    win = app.InstallerWindow(None)
    try:
        assert not win._install_running()
        # No install running: the delete-event handler lets the close
        # through instead of raising the confirm dialog.
        assert win._on_delete() is False
        win.terminate_install()  # no install: must not raise
    finally:
        win.destroy()


def test_bad_autoinstall_falls_back_to_wizard():
    win = app.InstallerWindow(None)
    try:
        start = win.index
        assert win._start_autoinstall("/definitely/not/a/recipe.json") is False
        assert win.index == start
        assert win._autoinstall_pending is None
    finally:
        win.destroy()


# ─── the Cancel button and the cancelled page (#299) ────────────────────────

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from bootc_shared import validate as fisherman_validate  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

from tuna_installer_xfce import core, gates  # noqa: E402


def _window(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("TUNA_INSTALLER_DRY_RUN", raising=False)
    return app.InstallerWindow(None)


def _pump_until(condition, seconds=10):
    deadline = time.time() + seconds
    while not condition() and time.time() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)
    return condition()


def _running_install(win, argv=("sleep", "30")):
    """A wrapper under the window, watched the way start_install() does."""
    pid, out, err = app.spawn_fisherman(list(argv))
    for fd in (out, err):
        os.close(fd)
    win._install_pid = pid
    GLib.child_watch_add(pid, win._on_exit)
    return pid


def _group_members(pgid):
    """The live (not zombie) processes of process group `pgid`."""
    members = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as stream:
                fields = stream.read().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        state, group = fields[0], int(fields[2])
        if group == pgid and state not in ("Z", "X"):
            members.append(int(entry))
    return members


def _shows(win):
    return win.stack.get_visible_child_name()


def test_the_progress_page_has_a_visible_cancel_that_asks_the_window(monkeypatch, tmp_path):
    win = _window(monkeypatch, tmp_path)
    try:
        progress = win.pages["progress"]
        assert progress.cancel_btn.get_visible()
        assert progress.cancel_btn.get_label() == "Cancel"
        asked = []
        monkeypatch.setattr(win, "request_cancel", lambda: asked.append(True))
        progress.cancel_btn.clicked()
        assert asked == [True]
    finally:
        win.destroy()


def test_cancel_asks_first_and_no_keeps_the_install(monkeypatch, tmp_path):
    win = _window(monkeypatch, tmp_path)
    pid = _running_install(win)
    try:
        asked = []

        def decline():
            asked.append(True)
            return False

        assert win.request_cancel(confirm=decline) is False
        assert asked == [True], "the question was asked"
        os.kill(pid, 0)  # still running: raises if it is gone
        assert not win._cancel_requested
        assert _shows(win) != "done"
    finally:
        app.terminate_process_group(pid)
        _pump_until(lambda: win._install_pid is None)
        win.destroy()


def test_a_confirmed_cancel_kills_the_group_and_shows_the_cancelled_page(
        monkeypatch, tmp_path):
    win = _window(monkeypatch, tmp_path)
    # The wrapper's bash with a child, as the real install has: the whole
    # group goes, not only the wrapper.
    pid = _running_install(win, ("bash", "-c", "sleep 30; exit $?"))
    try:
        assert _pump_until(lambda: len(_group_members(pid)) == 2, seconds=5), \
            "the wrapper and its child are both in the group"
        assert win.request_cancel(confirm=lambda: True) is True
        assert _pump_until(lambda: _shows(win) == "done"), "no result page"
        done = win.pages["done"]
        assert done.result == "cancelled"
        assert done.headline.get_text() == core.BRANDING.text("done_cancelled_title")
        assert done.headline.get_text() != core.BRANDING.text("done_failed_title")
        assert not done.reboot_btn.get_visible()
        assert done.close_btn.get_visible()
        # Nothing of the group is left running: the wrapper's child went
        # with it. (A zombie that nobody has reaped yet is not running.)
        assert _pump_until(lambda: not _group_members(pid), seconds=5), _group_members(pid)
    finally:
        app.terminate_process_group(pid)
        win.destroy()


def test_the_default_question_is_the_dialog(monkeypatch, tmp_path):
    win = _window(monkeypatch, tmp_path)
    try:
        built = []

        class _Dialog:
            def __init__(self, parent, body_text=""):
                built.append(parent)

            def run(self):
                return Gtk.ResponseType.CANCEL

            def destroy(self):
                pass

        monkeypatch.setattr(gates, "ConfirmCancelDialog", _Dialog)
        assert win._confirm_cancel() is False
        assert built == [win]
    finally:
        win.destroy()


def test_the_cancel_dialog_builds_with_the_safe_answer_first():
    dialog = gates.ConfirmCancelDialog(None)
    try:
        assert dialog.keep_btn.get_label() == "Continue installing"
        assert dialog.stop_btn.get_label() == "Cancel installation"
        assert dialog.stop_btn.get_style_context().has_class("destructive-action")
    finally:
        dialog.destroy()


def test_nothing_is_asked_when_no_install_runs(monkeypatch, tmp_path):
    win = _window(monkeypatch, tmp_path)
    try:
        asked = []
        assert win.request_cancel(confirm=lambda: asked.append(True) or True) is False
        assert asked == []
    finally:
        win.destroy()


def _exit_status(code):
    return code << 8


def test_exit_130_is_a_cancel_not_a_failure(monkeypatch, tmp_path):
    win = _window(monkeypatch, tmp_path)
    try:
        win._on_exit(0, _exit_status(130))
        assert _shows(win) == "done"
        assert win.pages["done"].result == "cancelled"
        assert win.pages["done"].headline.get_text() == core.BRANDING.text(
            "done_cancelled_title")
    finally:
        win.destroy()


def test_a_failure_is_still_a_failure(monkeypatch, tmp_path):
    win = _window(monkeypatch, tmp_path)
    try:
        win._on_exit(0, _exit_status(1))
        assert win.pages["done"].result == "failed"
        assert win.pages["done"].headline.get_text() == core.BRANDING.text(
            "done_failed_title")
        # A signal nobody asked for is a failure too.
        win._on_exit(0, signal.SIGKILL)
        assert win.pages["done"].result == "failed"
    finally:
        win.destroy()


def test_exit_1_after_a_confirmed_cancel_is_a_failure(monkeypatch, tmp_path):
    # The decided rule (shared/progress/outcome-cases.json): fisherman
    # failed before the cancel reached it. A signal is still the cancel.
    win = _window(monkeypatch, tmp_path)
    try:
        win._cancel_requested = True
        win._on_exit(0, _exit_status(1))
        assert win.pages["done"].result == "failed"
        win._on_exit(0, signal.SIGTERM)
        assert win.pages["done"].result == "cancelled"
    finally:
        win.destroy()


def _reuse_case(name):
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared", "progress",
                        "source-reuse-cases.json")
    with open(path, encoding="utf-8") as fh:
        return next(c for c in json.load(fh)["cases"] if c["name"] == name)


def test_the_progress_page_shows_the_copy_and_the_question_says_so(monkeypatch, tmp_path):
    """#267: the copy of this computer's system runs before the first step.
    The page says what fisherman reports, the bar holds, and a cancel then
    leaves the disk as it was."""
    win = _window(monkeypatch, tmp_path)
    try:
        progress = win.pages["progress"]
        assert win.cancel_question_body() == ""
        for event in _reuse_case("the_cancel_question_during_the_copy")["events"]:
            progress.append_log(json.dumps(event))
        text = progress.reuselabel.get_text()
        assert core.BRANDING.text("progress_reuse_copying") in text
        assert "1.0 GiB" in text
        assert progress.bar.get_fraction() == 0.0
        body = win.cancel_question_body()
        assert body == core.BRANDING.text("progress_reuse_cancel")
        dialog = gates.ConfirmCancelDialog(None, body)
        try:
            assert dialog.body.get_text() == body
        finally:
            dialog.destroy()
        for event in _reuse_case("cancelled_copy")["events"][2:]:
            progress.append_log(json.dumps(event))
        assert core.BRANDING.text("progress_reuse_released_removed") in progress.reuselabel.get_text()
        assert win.cancel_question_body() == ""
    finally:
        win.destroy()


def test_the_progress_page_shows_every_source_reuse_case(monkeypatch, tmp_path):
    """shared/progress/source-reuse-cases.json: the lines of each case on
    the progress page, with their values, and the bar of each event."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared", "progress",
                        "source-reuse-cases.json")
    with open(path, encoding="utf-8") as fh:
        cases = json.load(fh)["cases"]
    for case in cases:
        win = _window(monkeypatch, tmp_path)
        try:
            progress = win.pages["progress"]
            for event, bar in zip(case["events"], case["bar"]):
                progress.append_log(json.dumps(event))
                assert abs(progress.bar.get_fraction() - bar) < 1e-6, case["name"]
            want = [core.BRANDING.text(line["key"]).replace("{value}", line["value"])
                    for line in case["lines"]]
            assert progress.reuselabel.get_text() == "\n".join(want), case["name"]
            assert progress.reuselabel.get_visible() == bool(want), case["name"]
            assert bool(win.cancel_question_body()) == case["copy_cancel"], case["name"]
        finally:
            win.destroy()


def test_success_after_a_late_cancel_is_success(monkeypatch, tmp_path):
    win = _window(monkeypatch, tmp_path)
    try:
        win._cancel_requested = True
        win._on_exit(0, _exit_status(0))
        assert win.pages["done"].result == "installed"
    finally:
        win.destroy()


def test_cancel_works_in_a_dry_run(monkeypatch, tmp_path):
    win = _window(monkeypatch, tmp_path)
    monkeypatch.setenv("TUNA_INSTALLER_DRY_RUN", "1")
    try:
        win._enter(app.PAGE_ORDER.index("progress"))
        assert win._dry_run_source
        assert win.request_cancel(confirm=lambda: True) is True
        assert win._dry_run_source is None
        assert win.pages["done"].result == "cancelled"
    finally:
        win.destroy()


def test_one_install_at_a_time(monkeypatch, tmp_path):
    win = _window(monkeypatch, tmp_path)
    pid = _running_install(win)
    spawned = []
    monkeypatch.setattr(app, "spawn_fisherman", lambda *a, **k: spawned.append(a))
    try:
        win.start_install(win.pages["progress"], recipe={"disk": "/dev/vda"})
        assert spawned == []
    finally:
        app.terminate_process_group(pid)
        _pump_until(lambda: win._install_pid is None)
        win.destroy()


# ─── --autoinstall validates before it starts ───────────────────────────────

def _recipe_file(tmp_path, recipe):
    path = tmp_path / "auto.json"
    path.write_text(json.dumps(recipe))
    return str(path)


def _autoinstall(monkeypatch, tmp_path, recipe, answer):
    """Run _start_autoinstall with `answer` standing in for fisherman
    validate. Returns (window, recipes handed to start_install, validate
    calls)."""
    win = _window(monkeypatch, tmp_path)
    started, calls = [], []

    def fake_run(command, checked, timeout=None):
        calls.append((command, checked))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(fisherman_validate, "run", fake_run)
    monkeypatch.setattr(win, "start_install",
                        lambda page, recipe=None: started.append(win._autoinstall_pending))
    win._start_autoinstall(_recipe_file(tmp_path, recipe))
    return win, started, calls


GOOD = {"disk": "/dev/vda", "filesystem": "xfs", "image": "registry.example/os:1"}


def test_autoinstall_asks_fisherman_about_the_whole_recipe(monkeypatch, tmp_path):
    win, started, calls = _autoinstall(
        monkeypatch, tmp_path, GOOD,
        {"protocol_version": 1, "valid": True, "errors": []})
    try:
        assert len(calls) == 1
        command, checked = calls[0]
        # The whole recipe, not --partial, unprivileged, on stdin.
        assert command == core.fisherman_command("validate-full")
        assert "--partial" not in command
        assert checked == GOOD
        assert started == [GOOD]
        assert _shows(win) == "progress"
    finally:
        win.destroy()


def test_autoinstall_refuses_a_recipe_fisherman_rejects(monkeypatch, tmp_path):
    bad = dict(GOOD, hostname="Not A Hostname")
    win, started, _calls = _autoinstall(
        monkeypatch, tmp_path, bad,
        {"protocol_version": 1, "valid": False, "errors": [
            {"field": "hostname", "code": "hostname_invalid",
             "message": "hostname \"Not A Hostname\" is not valid"}]})
    try:
        assert started == [], "nothing was started"
        assert win._autoinstall_pending is None
        assert _shows(win) == "done"
        done = win.pages["done"]
        assert done.result == "failed"
        shown = fisherman_validate.render(
            {"code": "hostname_invalid", "message": "hostname \"Not A Hostname\" is not valid"},
            core.BRANDING.text)
        assert shown and shown in done.body.get_text()
    finally:
        win.destroy()


def test_autoinstall_refuses_a_recipe_with_no_disk(monkeypatch, tmp_path):
    win, started, calls = _autoinstall(
        monkeypatch, tmp_path, {"image": "registry.example/os:1"},
        {"protocol_version": 1, "valid": True, "errors": []})
    try:
        assert started == [] and calls == []
        assert win.pages["done"].result == "failed"
        assert "no installation disk" in win.pages["done"].body.get_text()
    finally:
        win.destroy()


def test_autoinstall_starts_when_fisherman_cannot_be_asked(monkeypatch, tmp_path):
    """The install runs the same rules before it touches a disk."""
    win, started, _calls = _autoinstall(
        monkeypatch, tmp_path, GOOD, fisherman_validate.ValidateError("not found"))
    try:
        assert started == [GOOD]
    finally:
        win.destroy()


def test_an_invalid_answer_without_problems_still_refuses(monkeypatch, tmp_path):
    win, started, _calls = _autoinstall(
        monkeypatch, tmp_path, GOOD,
        {"protocol_version": 1, "valid": False, "errors": []})
    try:
        assert started == []
        assert "did not accept" in win.pages["done"].body.get_text()
    finally:
        win.destroy()
