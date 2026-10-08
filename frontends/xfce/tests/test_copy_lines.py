"""Copy keys XFCE used to hardcode or drop (tests/unit/test_copy_coverage.py).

welcome_button, welcome_install_subtitle and progress_note were listed as
XFCE gaps: the Next button said "Next" on the welcome page, the live-system
row said "no download required", and the progress page had no warning at
all. Each is driven here through the real widget, not a string search.
"""

import os
import sys
import types

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import app, core, pages  # noqa: E402


class _Win:
    class _Trawl:
        def set_fill(self, _f):
            pass

    def __init__(self):
        self.trawl = self._Trawl()

    def start_install(self, _page):
        pass


class _Page:
    def can_continue(self):
        return True


def _nav_label(step):
    win = types.SimpleNamespace(
        pages={name: _Page() for name in app.PAGE_ORDER},
        index=app.PAGE_ORDER.index(step),
        back_btn=Gtk.Button(), next_btn=Gtk.Button(),
    )
    app.InstallerWindow.refresh_nav(win)
    return win.next_btn.get_label()


def test_welcome_forward_button_is_branded():
    assert _nav_label("welcome") == core.BRANDING.text("welcome_button")


def test_install_button_is_still_branded():
    assert _nav_label("confirm") == core.BRANDING.text("confirm_button")


def test_structural_steps_keep_next():
    assert _nav_label("source") == "Next"


def test_progress_note_is_shown():
    page = pages.ProgressPage(_Win())
    assert page.note.get_text() == core.BRANDING.text("progress_note")
    assert page.note.get_text(), "the neutral default must not be empty"
    assert not page.note.get_no_show_all()


def test_live_row_carries_the_install_subtitle(monkeypatch):
    monkeypatch.setattr(core, "live_iso_image", lambda: "ghcr.io/example/live:1")
    monkeypatch.setattr(core, "offline_stores", lambda: [])
    monkeypatch.setattr(core, "load_catalog", lambda: (None, None, []))
    page = pages.SourcePage(_Win())
    texts = []

    def walk(widget):
        if isinstance(widget, Gtk.Label):
            texts.append(widget.get_text())
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                walk(child)

    walk(page.listbox)
    assert any(core.BRANDING.text("welcome_install_subtitle") in t for t in texts), texts
    assert not any("no download required" in t for t in texts)
