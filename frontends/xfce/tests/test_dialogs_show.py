"""Each dialog shows what it asks before run(): the cancel question was an
empty box with no label and no buttons (walkthrough on headless sway, dev
c1da3d96)."""

import os
import sys

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import gates  # noqa: E402


def widgets(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from widgets(child)


@pytest.mark.parametrize("make", [
    lambda: gates.ConfirmCancelDialog(None),
    lambda: gates.ConfirmExitDialog(None),
])
def test_the_question_and_its_answers_show(make):
    dialog = make()
    try:
        shown = [w for w in widgets(dialog.get_content_area()) if w.get_visible()]
        assert any(isinstance(w, Gtk.Label) and w.get_text() for w in shown)
        assert sum(isinstance(w, Gtk.Button) for w in shown) >= 2
    finally:
        dialog.destroy()
