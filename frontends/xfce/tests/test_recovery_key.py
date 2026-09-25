"""The recovery-key panel on the done page (#129).

For a tpm2-luks install fisherman generates a random LUKS passphrase and
emits it once, as a `recovery_key` event. It is the sole fallback: the TPM
unlocks the disk by itself, and if the TPM state changes that key is the
only way back in.

Before this the four non-GNOME frontends rendered it into the install log
and nothing else. The log scrolls, nothing pauses, and a user could reach
Done and reboot having never seen it.

These drive the real parser with a real event, not a seeded string, so a
regression in the parse is caught here rather than only in a capture.
"""

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
    return json.dumps({
        "type": "recovery_key",
        "key": key,
        "timestamp": "2026-01-01T00:00:00Z",
        "elapsed_ms": 1000,
    })


class _Win:
    """The two attributes the pages touch during these tests."""

    class _Trawl:
        def set_fill(self, _f):
            pass

    def __init__(self):
        self.trawl = self._Trawl()

    def start_install(self, _page):
        pass


def _pages():
    win = _Win()
    return pages.ProgressPage(win), pages.DonePage(win)


def test_progress_page_picks_the_key_out_of_the_event():
    progress, _done = _pages()
    assert progress.recovery_key() == ""
    progress.append_log(_recovery_event() + "\n")
    assert progress.recovery_key() == KEY


def test_done_page_shows_the_key_and_gates_reboot():
    progress, done = _pages()
    progress.append_log(_recovery_event() + "\n")

    done.set_result(True, "", progress.recovery_key())

    assert done.recovery_box.get_visible(), "the panel must be shown"
    assert done.recovery_key_label.get_text() == KEY
    assert not done.reboot_btn.get_sensitive(), \
        "reboot must wait for the acknowledgement"

    done.recovery_ack.set_active(True)
    assert done.reboot_btn.get_sensitive(), \
        "ticking the box must release reboot"


def test_no_key_means_no_panel_and_no_gate():
    """A non-TPM install must not be asked to tick a box about a key it
    was never given."""
    _progress, done = _pages()
    done.set_result(True, "", "")

    assert not done.recovery_box.get_visible()
    assert done.reboot_btn.get_sensitive()


def test_a_failed_install_shows_no_key():
    """Nothing was enrolled, so there is nothing to write down."""
    progress, done = _pages()
    progress.append_log(_recovery_event() + "\n")

    done.set_result(False, "some log tail", progress.recovery_key())

    assert not done.recovery_box.get_visible()


def test_the_panel_text_comes_from_the_branding_contract():
    """No product string and no hardcoded copy: shared/branding/README.md."""
    progress, done = _pages()
    progress.append_log(_recovery_event() + "\n")
    done.set_result(True, "", progress.recovery_key())

    assert done.recovery_body.get_text() == \
        core.BRANDING.text("recovery_key_body")
    assert done.recovery_ack.get_label() == \
        core.BRANDING.text("recovery_key_ack")
    assert done.recovery_copy_btn.get_label() == \
        core.BRANDING.text("recovery_key_copy")
    for widget_text in (done.recovery_body.get_text(),
                        done.recovery_ack.get_label()):
        assert "TunaOS" not in widget_text
        assert "Bluefin" not in widget_text


def test_the_key_is_selectable_so_it_can_be_copied_by_hand():
    """The copy button needs a clipboard; selecting the text does not."""
    progress, done = _pages()
    progress.append_log(_recovery_event() + "\n")
    done.set_result(True, "", progress.recovery_key())

    assert done.recovery_key_label.get_selectable()


def test_a_plain_log_line_is_not_mistaken_for_a_key():
    """The old mitigation rendered "Recovery key: ..." into the pane. That
    text must not be parsed back out as an event."""
    progress, _done = _pages()
    progress.append_log("Recovery key: not-a-real-event\n")
    assert progress.recovery_key() == ""


def test_gtk_is_really_initialised():
    """Guards the guard: if Gtk could not init, every assertion above would
    pass vacuously on stub widgets."""
    assert Gtk.init_check([])[0]
