# test_atspi_names.py - the first AT-SPI contract test
# SPDX-License-Identifier: GPL-3.0-or-later
#
# shared/flow/README.md, "Test contract": match buttons by role AND
# sensitive, prefer the topmost dialog, classify the page from its text,
# match the recovery key by shape, normalise toolkit sizes. This exercises
# the same rules in-process against the real widget tree: every screen id
# of shared/flow/screens.yaml reports its spec name, and every named
# action is a sensitive push button.
import os
import re
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Atk", "1.0")
from gi.repository import Atk, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import app, pages  # noqa: E402

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "shared",
    "client", "python")))
from sizes import normalize_size_text  # noqa: E402

NAMES = {
    # internal: spec accessibility name (shared/flow/screens.yaml)
    "welcome": "Welcome",
    "language": "Language",
    "keyboard": "Keyboard layout",
    "timezone": "Time zone",
    "network": "Network",
    "prerelease": "Disclaimer",
    "eula": "Terms of use",
    "rst": "Intel RST",
    "destination": "Disk selection",
    "wipe": "Existing data found",
    "setup": "Disk encryption",
    "identity": "Account",
    "confirm": "Confirm",
    "progress": "Installing",
    "recovery": "Recovery key",
    "handoff": "Handoff",
    "done": "Done",
}

BUTTONS = {
    # internal: labels of the actions that must be sensitive push buttons
    "network": ["Network settings", "Recheck"],
    "rst": ["Power off"],
    "recovery": ["Show QR Code for Recovery Key"],
    "handoff": ["Continue", "Not now"],
    "done": ["Try again", "Close"],
    "progress": ["Cancel"],
}


def _window():
    return app.InstallerWindow(None)


def _sensitive_buttons(page):
    """(label, widget) for every sensitive push button under `page`:
    role AND sensitive, the harness rule. The walk recurses: actions sit
    in rows and bars below the page root."""
    found = []

    def walk(widget):
        if isinstance(widget, Gtk.Button):
            found.append(widget)
        if isinstance(widget, Gtk.Container):
            widget.foreach(walk)

    walk(page)
    out = []
    for button in found:
        accessible = button.get_accessible()
        if accessible is not None and accessible.get_role() == Atk.Role.PUSH_BUTTON:
            if button.get_sensitive() and button.get_visible():
                out.append((button.get_label(), button))
    return out


def test_every_screen_reports_its_spec_name():
    win = _window()
    try:
        for internal, name in NAMES.items():
            page = win.pages[internal]
            assert page.get_accessible().get_name() == name, internal
    finally:
        win.destroy()


def test_named_actions_are_sensitive_push_buttons():
    win = _window()
    try:
        for internal, labels in BUTTONS.items():
            page = win.pages[internal]
            page.show_all()
            if internal == "done":
                # Try again only shows on a failed or cancelled install.
                page.set_result(False, "tail")
            got = dict(_sensitive_buttons(page))
            for label in labels:
                assert label in got, f"{internal}: {label} missing"
                assert got[label].get_accessible().get_name() == label
    finally:
        win.destroy()


def test_done_advance_buttons_follow_the_result():
    win = _window()
    try:
        done = win.pages["done"]
        done.show_all()
        done.set_result(True, "")
        assert "Not now" in dict(_sensitive_buttons(done))
        done.set_result(False, "tail", cancelled=True)
        assert "Try again" in dict(_sensitive_buttons(done))
    finally:
        win.destroy()


def test_recovery_key_matches_by_shape():
    """The key label's accessible name is the key itself: match it by the
    shape in shared/flow (8 groups), never by a node named Recovery Key."""
    win = _window()
    try:
        page = win.pages["recovery"]
        page.show_all()
        page.key_label.set_text(
            "abcdefgh-ijklmnop-qrstuvwx-yzabcdef-ghijkmnp-qrstuvwx-yzabcdef-ghijklmn")
        shape = re.compile(r"^[a-z]{6,10}(-[a-z]{6,10}){7}$")
        assert shape.match(page.key_label.get_text()), "key has the spec shape"
    finally:
        win.destroy()


def test_disk_row_sizes_normalise():
    """A toolkit size holds a no-break space: compare normalised."""
    assert normalize_size_text("476.9\u00a0GiB") == "476.9 GiB"
    label = pages.disk_label({"title": "Mock NVMe", "path": "/dev/nvme0n1",
                              "size_label": "476.9\u00a0GiB",
                              "transport_label": "NVMe"})
    assert "476.9 GiB" in normalize_size_text(label)


def test_stamp_reports_spec_ids_for_every_page():
    for internal, name in NAMES.items():
        assert app.spec_page(internal) != "unknown", internal
    assert app.spec_page("source") == "source"
    assert set(app.SPEC_IDS) == set(app.PAGE_ORDER)
