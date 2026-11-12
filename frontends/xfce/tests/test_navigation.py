"""Where the wizard's buttons show, and what the confirm and done pages say.

The CI walkthrough showed Back on the welcome page (nothing behind it),
during the install (which cannot be backed out of) and on the done page
(the end). The other frontends hide it on all three, and the done page
offers Close and Restart now instead.
"""

import os
import sys
import types

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import app, core, pages  # noqa: E402


class _Page:
    def can_continue(self):
        return True


def _nav(step):
    win = types.SimpleNamespace(
        pages={name: _Page() for name in app.PAGE_ORDER},
        index=app.PAGE_ORDER.index(step),
        back_btn=Gtk.Button(), next_btn=Gtk.Button(), nav=Gtk.Box(),
    )
    app.InstallerWindow.refresh_nav(win)
    return win


def test_no_back_on_welcome():
    win = _nav("welcome")
    assert not win.back_btn.get_visible()
    assert win.next_btn.get_visible()


def test_back_on_the_steps_in_between():
    for step in ("source", "destination", "setup", "identity", "confirm"):
        win = _nav(step)
        assert win.back_btn.get_visible(), step
        assert win.back_btn.get_sensitive(), step


def test_no_nav_bar_while_installing_or_when_done():
    for step in ("progress", "done"):
        win = _nav(step)
        assert not win.back_btn.get_visible(), step
        assert not win.next_btn.get_visible(), step
        assert not win.nav.get_visible(), step


class _Win:
    class _Trawl:
        def set_fill(self, _f):
            pass

    def __init__(self):
        self.trawl = self._Trawl()


def test_done_page_says_installed_and_offers_close_and_restart():
    done = pages.DonePage(_Win())
    done.set_result(True, "")
    assert core.BRANDING.text("done_title") in done.headline.get_text()
    body = done.body.get_text()
    assert body.startswith(core.BRANDING.text("done_subtitle"))
    # Installed, restart required, and how the first start is checked;
    # never a verified start (#269).
    assert core.BRANDING.text("done_verification") in body
    assert "verified" not in body.lower()
    assert done.close_btn.get_label() == "Close"
    assert done.reboot_btn.get_label() == core.BRANDING.text("done_restart")
    assert done.reboot_btn.get_sensitive()


def test_failed_install_offers_close_but_not_restart():
    done = pages.DonePage(_Win())
    done.show_all()
    done.set_result(False, "tail")
    assert done.close_btn.get_visible()
    assert not done.reboot_btn.get_visible()


class _ConfirmWin:
    """What ConfirmPage.on_enter reads from the window."""

    def __init__(self):
        self.pages = {
            "destination": types.SimpleNamespace(
                selected_disk=lambda: {"path": "/dev/vdz", "title": "Disk"}),
            "source": types.SimpleNamespace(live_image=""),
        }

    def build_recipe(self):
        return {"disk": "/dev/vdz", "filesystem": "btrfs",
                "encryption": {"type": "none"}, "hostname": "box",
                "image": "registry.example/os:1"}


def test_confirm_summary_rows_and_erase_warning_name_the_disk():
    confirm = pages.ConfirmPage(_ConfirmWin())
    confirm.on_enter()
    text = confirm.summary.get_text()
    for row in ("Target disk:", "Filesystem:", "Encryption:", "Hostname:", "Image:"):
        assert row in text, row
    assert "/dev/vdz" in text and "registry.example/os:1" in text
    assert confirm.warn_text.get_text() == core.BRANDING.text(
        "confirm_warning", disk="/dev/vdz")


def test_done_page_shows_the_receipt_cases():
    """shared/progress/receipt-cases.json: the lines of each case on the
    done page, the install id with them (#269)."""
    import json as _json

    from bootc_shared import progress as pp
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                        "shared", "progress", "receipt-cases.json")
    with open(path, encoding="utf-8") as fh:
        cases = _json.load(fh)["cases"]
    for case in cases:
        state = pp.new_progress_state()
        for event in case["events"]:
            pp.apply_progress_event(_json.dumps(event), state)
        done = pages.DonePage(_Win())
        done.set_result(True, "", receipt=state["receipt"])
        body = done.body.get_text()
        for line in case["done_lines"]:
            assert core.BRANDING.text(line["key"]).replace("{value}", line["value"]) in body, \
                case["name"]
        assert "verified" not in body.lower()


def test_failed_page_says_whether_the_disk_changed_and_the_cleanup():
    """shared/progress/error-cases.json (tuna-os/fisherman#449): the failure
    page says whether the disk was changed, and when the cleanup failed or
    timed out, above the log tail. An older fisherman's event adds no line."""
    import json as _json

    from bootc_shared import progress as pp
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                        "shared", "progress", "error-cases.json")
    with open(path, encoding="utf-8") as fh:
        cases = _json.load(fh)["cases"]
    every = {"done_failed_disk_unchanged", "done_failed_disk_changed",
             "done_failed_cleanup_failed", "done_failed_cleanup_timed_out"}
    for case in cases:
        state = pp.new_progress_state()
        for event in case["events"]:
            pp.apply_progress_event(_json.dumps(event), state)
        done = pages.DonePage(_Win())
        done.set_result(False, "the tail", error=state["error"])
        body = done.body.get_text()
        want = [core.BRANDING.text(key) for key in case["lines"]]
        assert body.split("\n\n")[:len(want)] == want, case["name"]
        for key in every - set(case["lines"]):
            assert core.BRANDING.text(key) not in body, (case["name"], key)
        assert "the tail" in body


def test_the_progress_page_hands_its_error_to_the_done_page():
    win = app.InstallerWindow.__new__(app.InstallerWindow)
    error = {"message": "m", "code": "unknown", "field": "", "step_id": "",
             "disk_changed": False, "cleanup": {"status": "ok", "message": ""}}
    seen = {}
    win._log_tail = ["tail\n"]
    win.pages = {
        "progress": types.SimpleNamespace(recovery_key=lambda: "", receipt=lambda: None,
                                          error=lambda: error),
        "done": types.SimpleNamespace(set_result=lambda *a, **kw: seen.update(kw)),
    }
    win._enter = lambda index: None
    app.InstallerWindow._show_result(win, False)
    assert seen["error"] is error
