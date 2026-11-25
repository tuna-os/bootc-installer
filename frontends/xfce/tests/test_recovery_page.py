# test_recovery_page.py - the recovery-key screen and its QR dialog
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The key moved off the done page onto its own screen
# (tuna-os/bootc-installer#446): the key label, the copy button, the QR
# dialog, and the acknowledgement gating Done. Nothing here writes the
# key anywhere but the label.

import json
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import core, pages  # noqa: E402

KEY = "mkta-rdcw-nnhu-fnbx-kwnv-oixz-ahhh-uahf"


def _recovery_event(key=KEY):
    """Exactly what fisherman writes: one JSON object, one line."""
    return json.dumps({"type": "recovery_key", "key": key,
                       "timestamp": "1970-01-01T00:00:00Z", "elapsed_ms": 0})


class _Win:
    """What the recovery page touches: pages, nav refresh, install mode."""

    class _Trawl:
        def set_fill(self, _f):
            pass

    def __init__(self, enc_type="tpm2-luks"):
        self.trawl = self._Trawl()
        self.install_mode = "erase"
        self.handoff_result = None
        self._enc_type = enc_type
        self.pages = {}

    def start_install(self, _page):
        pass

    def refresh_nav(self):
        pass


def _recovery_page(win=None, key=""):
    win = win or _Win()
    setup = types_setup(win._enc_type)
    progress = pages.ProgressPage(win)
    win.pages = {"setup": setup, "progress": progress}
    if key:
        progress.append_log(_recovery_event(key) + "\n")
    page = pages.RecoveryPage(win)
    page.show_all()
    page.on_enter()
    return page


def types_setup(enc_type):
    import types
    return types.SimpleNamespace(enc_type=lambda: enc_type)


def test_progress_page_picks_the_key_out_of_the_event():
    win = _Win()
    progress = pages.ProgressPage(win)
    assert progress.recovery_key() == ""
    progress.append_log(_recovery_event() + "\n")
    assert progress.recovery_key() == KEY


def test_recovery_page_shows_the_key_and_gates_done():
    page = _recovery_page(key=KEY)
    assert page.should_show() is True
    assert page.get_accessible().get_name() == "Recovery key"
    assert page.key_label.get_text() == KEY
    assert not page.can_continue(), "Done must wait for the acknowledgement"
    page.ack.set_active(True)
    assert page.can_continue(), "ticking the box releases Done"


def test_unencrypted_install_skips_the_page():
    win = _Win(enc_type="none")
    setup = types_setup("none")
    win.pages = {"setup": setup}
    page = pages.RecoveryPage(win)
    assert page.should_show() is False


def test_no_key_never_advances():
    page = _recovery_page(key="")
    assert page.key_label.get_text() == ""
    assert not page.can_continue()


def test_a_failed_install_has_no_key_to_show():
    page = _recovery_page(key="")
    assert page.key_label.get_text() == ""


def test_the_page_text_comes_from_the_branding_contract():
    page = _recovery_page(key=KEY)
    assert page.body.get_text() == core.BRANDING.text("recovery_key_body")
    assert page.ack.get_label() == core.BRANDING.text("recovery_key_ack")
    assert page.copy_btn.get_label() == \
        core.BRANDING.text("recovery_key_copy")
    for widget_text in (page.body.get_text(), page.ack.get_label()):
        assert "TunaOS" not in widget_text
        assert "Bluefin" not in widget_text


def test_the_key_is_selectable_so_it_can_be_copied_by_hand():
    page = _recovery_page(key=KEY)
    assert page.key_label.get_selectable()


def test_done_advances_only_after_the_ack():
    import pytest
    pytest.importorskip("qrcode")
    page = _recovery_page(key=KEY)
    assert page.qr_btn.get_visible(), "qrcode is installed here"
    assert page.next_label == "Done"


def test_qr_dialog_draws_the_matrix():
    import pytest
    qrcode = pytest.importorskip("qrcode")

    box = qrcode.QRCode(border=1)
    box.add_data(KEY)
    box.make()
    matrix = box.get_matrix()
    assert len(matrix) > 20
    assert any(any(line) for line in matrix)
    dialog = pages.RecoveryKeyDialog(None, KEY)
    assert dialog.area is not None
    dialog.destroy()


def test_a_plain_log_line_is_not_mistaken_for_a_key():
    win = _Win()
    progress = pages.ProgressPage(win)
    progress.append_log("Installing: Recovery key: hunter2\n")
    assert progress.recovery_key() == ""


def test_daemon_key_comes_from_make_recovery_key(monkeypatch):
    import types

    monkeypatch.setattr(core, "backend", lambda: "daemon")
    monkeypatch.setattr(core, "get_daemon", lambda: types.SimpleNamespace(
        make_recovery_key=lambda: KEY,
        enroll_recovery_key=lambda *a: {"slot": 1}))
    win = _Win()
    win.pages = {"setup": types_setup("tpm2-luks"),
                 "destination": types.SimpleNamespace(
                     selected_disk=lambda: {"path": "/dev/vda"})}
    page = pages.RecoveryPage(win)
    page.show_all()
    page.on_enter()
    assert page.key_label.get_text() == KEY
    assert page.can_continue() is False
    page.ack.set_active(True)
    assert page.on_leave() is True, "enrol before leaving"


def test_daemon_make_key_failure_blocks(monkeypatch):
    from tuna_installer_xfce import daemon as daemon_client

    monkeypatch.setattr(core, "backend", lambda: "daemon")

    def fail():
        raise daemon_client.DaemonError("no slots")

    monkeypatch.setattr(core, "get_daemon", fail)
    win = _Win()
    win.pages = {"setup": types_setup("tpm2-luks")}
    page = pages.RecoveryPage(win)
    page.show_all()
    page.on_enter()
    assert page.key_label.get_text() == ""
    assert not page.can_continue(), "spec: no key, do not continue"
    assert page.error_label.get_text()


def test_gtk_is_really_initialised():
    """Guards the guard: if Gtk could not init, every assertion above would
    pass vacuously on stub widgets."""
    assert Gtk.init_check([])[0]
