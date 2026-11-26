"""The screen reader on the first page (installer standard A6): XFCE has
no shortcut for it, so the welcome page offers it, applies it to the live
session at once, and carries a change to the installed system."""

import os
import subprocess
import sys
import types

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import app, core, pages  # noqa: E402


def _host(monkeypatch, value="false", rc=0):
    calls, spawned = [], []

    def run(argv, **_kwargs):
        calls.append(list(argv))
        out = value + "\n" if argv[:2] == ["gsettings", "get"] else ""
        return subprocess.CompletedProcess(argv, rc, out, "")

    monkeypatch.setattr(core, "host_run", run)
    monkeypatch.setattr(core, "host_spawn", lambda argv: spawned.append(list(argv)))
    return calls, spawned


KEY = ["org.gnome.desktop.a11y.applications", "screen-reader-enabled"]


def test_the_toggle_shows_the_sessions_setting(monkeypatch):
    _host(monkeypatch, "true")
    page = pages.WelcomePage(types.SimpleNamespace())
    assert page.reader.get_active()
    assert page.reader.get_use_underline()
    assert page.reader.get_accessible().get_name() == "Screen reader"
    assert page.accessibility_choice() is None


def test_turning_it_on_applies_it_now_and_carries_it(monkeypatch):
    calls, spawned = _host(monkeypatch, "false")
    page = pages.WelcomePage(types.SimpleNamespace())
    page.reader.set_active(True)
    assert ["gsettings", "set", *KEY, "true"] in calls
    assert spawned == [["orca", "--replace"]]
    assert page.accessibility_choice() == {"screenReader": True}
    page.reader.set_active(False)
    assert ["gsettings", "set", *KEY, "false"] in calls
    assert spawned[-1] == ["orca", "--quit"]
    assert page.accessibility_choice() is None, "back to the session's value: nothing sent"


def test_a_setting_that_cannot_be_written_says_so(monkeypatch):
    _host(monkeypatch, "false", rc=1)
    page = pages.WelcomePage(types.SimpleNamespace())
    page.reader.set_active(True)
    assert page.reader_problem.get_text()


def test_an_unreadable_setting_is_off(monkeypatch):
    def fail(*_a, **_k):
        raise OSError("no gsettings")

    monkeypatch.setattr(core, "host_run", fail)
    assert core.screen_reader_enabled() is False
    assert core.set_screen_reader(True) is False


def test_the_choice_reaches_configure_target(monkeypatch):
    _host(monkeypatch, "false")
    sent = {}
    win = app.InstallerWindow(None)
    try:
        win.pages["welcome"].reader.set_active(True)
        fake = types.SimpleNamespace(
            configure_target=lambda **kw: sent.update(kw),
            install=lambda config: iter([{"event": "complete"}]))
        monkeypatch.setattr(core, "get_daemon", lambda: fake)
        monkeypatch.setattr(app.GLib, "idle_add", lambda fn, *a: None)
        monkeypatch.setattr(app.threading, "Thread",
                            lambda target, daemon: types.SimpleNamespace(start=target))
        monkeypatch.setattr(win, "daemon_config", lambda recipe: {})
        monkeypatch.setattr(win, "_finish_daemon_install", lambda *a: None)
        monkeypatch.setattr(win, "_new_install_log", lambda: __import__("io").StringIO())
        progress = types.SimpleNamespace(append_log=lambda *_a: None)
        win._start_daemon_install(progress, {"hostname": "box"})
    finally:
        win.destroy()
    assert sent.get("accessibility") == {"screenReader": True}
