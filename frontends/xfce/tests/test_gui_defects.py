"""What the first real installs looked like (tunaOS run 45639909696), and what
the pages show in its place. Each test drives the real widgets."""

import json
import os
import sys
import types

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import app, core, daemon, pages  # noqa: E402
from tuna_installer_xfce import locale as locale_checks  # noqa: E402


@pytest.fixture
def window():
    win = app.InstallerWindow(None)
    yield win
    win.destroy()


# ─── the disk ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("disk, title", [
    ({"vendor": "0x1af4", "model": "", "transport": "virtio", "path": "/dev/vda"},
     "VirtIO disk"),
    ({"vendor": "0x1AF4", "model": "", "transport": "", "path": "/dev/vda"}, "/dev/vda"),
    ({"vendor": "0x144d", "model": "Samsung 980", "transport": "nvme"}, "Samsung 980"),
    ({"vendor": "Mockware", "model": "Mock NVMe", "transport": "nvme"}, "Mockware Mock NVMe"),
    ({"vendor": "ATA", "model": "", "transport": "sata"}, "ATA"),
])
def test_a_disk_is_never_called_by_a_pci_id(disk, title):
    assert daemon.disk_title(disk) == title


def test_only_a_disk_that_is_too_small_is_listed_as_too_small(monkeypatch):
    def row(path, reason, eligible=False):
        return {"path": path, "title": path, "size_label": "1 GiB", "transport_label": "",
                "eligible": eligible, "fit": "", "excluded_reason": reason,
                "minimal_size_bytes": 20 << 30, "free_bytes": 0, "existing_data": {},
                "removable": False}
    monkeypatch.setattr(core, "backend", lambda: "daemon")
    monkeypatch.setattr(core, "daemon_disk_view", lambda: ([
        row("/dev/vda", "", True), row("/dev/sdb", "too_small"),
        row("/dev/loop0", "loop"), row("/dev/sr0", "optical")], None))
    page = pages.DestinationPage(types.SimpleNamespace())
    page.on_enter()
    text = " ".join(child.get_label() if hasattr(child, "get_label") else ""
                    for child in page.listbox.get_children())
    assert "/dev/sdb" in text
    assert "/dev/loop0" not in text and "/dev/sr0" not in text


# ─── language, keyboard, time zone ───────────────────────────────────────────

def test_a_time_zone_shows_its_city_and_keeps_its_name(monkeypatch):
    assert locale_checks.timezone_label("America/Argentina/Buenos_Aires") == (
        "Buenos Aires (America/Argentina)")
    assert locale_checks.timezone_label("UTC") == "UTC"
    monkeypatch.setattr(locale_checks, "available_timezones",
                        lambda: ["UTC", "America/New_York"])
    monkeypatch.setattr(locale_checks, "current_timezone", lambda: "UTC")
    monkeypatch.setattr(locale_checks, "apply_timezone", lambda _v: True)
    win = types.SimpleNamespace(region=pages.RegionState(), refresh_nav=lambda: None)
    page = pages.TimezonePage(win)
    assert page.selected() == "UTC"
    row = page.rows["America/New_York"]
    assert row.get_child().get_text() == "New York (America)"
    for needle in ("new york", "america/new_york"):
        page.search.set_text(needle)
        assert page._filter(row), needle
    page.listbox.select_row(row)
    assert win.region.timezone == "America/New_York"


def test_a_list_without_the_sessions_value_opens_on_keep(monkeypatch):
    monkeypatch.setattr(locale_checks, "available_languages", lambda: ["en_US.UTF-8"])
    monkeypatch.setattr(locale_checks, "current_language", lambda: "C.UTF-8")
    applied = []
    monkeypatch.setattr(locale_checks, "apply_language", lambda v: applied.append(v) or True)
    win = types.SimpleNamespace(region=pages.RegionState(), refresh_nav=lambda: None)
    page = pages.LanguagePage(win)
    assert page.listbox.get_selected_row() is page.rows[""]
    assert page.rows[""].get_child().get_text() == "Keep the image's setting"
    assert win.region.locale == "" and applied == []
    page.listbox.select_row(page.rows["en_US.UTF-8"])
    assert win.region.locale == "en_US.UTF-8"
    page.listbox.select_row(page.rows[""])
    assert win.region.locale == ""


def test_keyboard_layouts_have_the_names_of_xkb(tmp_path, monkeypatch):
    rules = tmp_path / "evdev.lst"
    rules.write_text("! model\n  pc104  Generic\n! layout\n  de              German\n"
                     "  custom  A user-defined layout\n! variant\n  nodeadkeys de: No\n")
    monkeypatch.setattr(locale_checks, "XKB_LISTS", (str(rules),))
    monkeypatch.setattr(locale_checks, "_names", {})
    assert locale_checks.keyboard_names() == {"de": "German"}
    assert locale_checks.keyboard_label("de") == "German"
    assert locale_checks.keyboard_label("xx") == "xx"


def test_c_is_no_language(monkeypatch):
    monkeypatch.setattr(locale_checks, "available_languages",
                        lambda: ["C.UTF-8", "POSIX", "de_DE.UTF-8"])
    monkeypatch.setattr(locale_checks, "current_language", lambda: "C.UTF-8")
    win = types.SimpleNamespace(region=pages.RegionState(), refresh_nav=lambda: None)
    page = pages.LanguagePage(win)
    assert list(page.rows) == ["", "de_DE.UTF-8"]
    assert page.listbox.get_selected_row() is page.rows[""]
    assert page.rows["de_DE.UTF-8"].get_child().get_text() == "Deutsch (DE)"


@pytest.mark.parametrize("page_class, offer, session, field", [
    (pages.LanguagePage, "available_languages", "current_language", "locale"),
    (pages.KeyboardPage, "available_keyboard_layouts", "current_keyboard_layout",
     "keyboard_layout"),
    (pages.TimezonePage, "available_timezones", "current_timezone", "timezone"),
])
@pytest.mark.parametrize("current", ["de_DE.UTF-8", "xx"])
def test_what_is_selected_is_what_is_sent(monkeypatch, page_class, offer, session, field,
                                          current):
    """The selected row and the recipe cannot differ: a passphrase is typed
    with the one and read with the other."""
    for name in ("apply_language", "apply_keyboard_layout", "apply_timezone"):
        monkeypatch.setattr(locale_checks, name, lambda _v: True)
    monkeypatch.setattr(locale_checks, offer, lambda: ["de_DE.UTF-8", "fr_FR.UTF-8"])
    monkeypatch.setattr(locale_checks, session, lambda: current)
    region = pages.RegionState()
    page = page_class(types.SimpleNamespace(region=region, refresh_nav=lambda: None))
    assert page.listbox.get_selected_row().value == getattr(region, field)
    page.listbox.select_row(page.rows["fr_FR.UTF-8"])
    assert getattr(region, field) == "fr_FR.UTF-8"


# ─── the window ──────────────────────────────────────────────────────────────

def test_the_window_is_centred_and_has_the_apps_icon(window):
    assert window.get_property("window-position") == Gtk.WindowPosition.CENTER
    assert window.get_icon_name() == app.APP_ID


def test_the_steps_are_named_and_only_the_shown_ones_count(window, monkeypatch):
    for name in ("network", "prerelease", "eula", "rst", "wipe"):
        monkeypatch.setattr(window.pages[name], "should_show", lambda: False)
    window._enter(app.PAGE_ORDER.index("timezone"))
    steps = window.shown_steps()
    assert "network" not in steps and "timezone" in steps
    assert window.step_label.get_text() == f"Step 4 of {len(steps)} · Time zone"
    assert window.trawl.n_steps == len(steps)
    window._enter(app.PAGE_ORDER.index("done"))
    assert not window.step_label.get_visible()


def test_a_button_that_waits_is_not_marked(window):
    window._enter(app.PAGE_ORDER.index("identity"))
    window.pages["identity"].username.set_text("")
    window.pages["identity"].can_continue = lambda: False
    window.refresh_nav()
    assert not window.next_btn.get_style_context().has_class("suggested-action")


def test_the_primary_button_is_marked(window):
    window._enter(app.PAGE_ORDER.index("language"))
    assert window.next_btn.get_style_context().has_class("suggested-action")
    assert window.get_default_widget() is window.next_btn
    # Enter starts no install.
    monkey = pages.ConfirmPage.on_enter
    pages.ConfirmPage.on_enter = lambda self: None
    try:
        window._enter(app.PAGE_ORDER.index("confirm"))
    finally:
        pages.ConfirmPage.on_enter = monkey
    assert window.get_default_widget() is None
    context = window.next_btn.get_style_context()
    assert context.has_class("destructive-action")
    assert not context.has_class("suggested-action")


@pytest.mark.parametrize("name", ["recovery", "handoff"])
def test_there_is_no_back_after_the_install(window, name):
    """Back on the recovery key page went to the progress page, which starts
    the install again."""
    window.index = app.PAGE_ORDER.index(name)
    window.refresh_nav()
    assert not window.back_btn.get_visible()


# ─── the confirm page asks the daemon first ──────────────────────────────────

class _Confirm:
    def __init__(self):
        self.pages = {"destination": types.SimpleNamespace(selected_disk=lambda: {
            "path": "/dev/vda", "title": "VirtIO disk", "size_label": "64 GiB"}),
            "source": types.SimpleNamespace(live_image="img")}

    def build_recipe(self):
        return {"disk": "/dev/vda", "filesystem": "xfs", "hostname": "box",
                "encryption": {"type": "none"}, "user": {"username": "u"}}

    def refresh_nav(self):
        pass


def _confirm(monkeypatch, problems):
    monkeypatch.setattr(core, "backend", lambda: "daemon")
    page = pages.ConfirmPage(_Confirm())
    page.refused_request = lambda recipe: problems
    page.refused_start = lambda fn: fn()
    monkeypatch.setattr(pages.GLib, "idle_add", lambda fn, *args: fn(*args))
    page.on_enter()
    return page


def test_what_the_daemon_refuses_holds_install(monkeypatch):
    page = _confirm(monkeypatch, ["An unencrypted install is not supported yet."])
    assert page.refused_label.get_text() == "An unencrypted install is not supported yet."
    assert not page.can_continue()
    page = _confirm(monkeypatch, [])
    assert page.can_continue()


def test_the_daemon_summary_has_no_row_that_does_not_apply(monkeypatch):
    text = _confirm(monkeypatch, []).summary_text()
    assert "Filesystem" not in text
    assert "Target disk: VirtIO disk (/dev/vda, 64 GiB)" in text
    assert "Language: The image's setting" in text


# ─── the install, and how it fails ───────────────────────────────────────────

def test_a_tick_of_the_bar_is_not_shown_as_json():
    win = types.SimpleNamespace(trawl=types.SimpleNamespace(set_fill=lambda _f: None))
    page = pages.ProgressPage(win)
    for event in ({"event": "step_started", "stepId": "validate_device", "stepIndex": 1,
                   "totalSteps": 10, "overallPct": 0},
                  {"event": "progress", "overallPct": 1},
                  {"event": "step_finished", "stepId": "validate_device"}):
        page.append_log(daemon.line_text(daemon.daemon_event_to_line(event)) + "\n")
    buf = page.logview.get_buffer()
    log = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    assert log == "[1/10] Checking your drive…\n"


def test_the_failure_page_is_a_sentence():
    done = pages.DonePage(types.SimpleNamespace())
    lines = [daemon.daemon_event_to_line(event, False) for event in (
        {"event": "step_started", "stepId": "validate_device", "stepIndex": 1,
         "totalSteps": 8},
        {"event": "failed", "stepId": "validate_device", "reason": "unsupported_config",
         "message": "an unencrypted install is not supported yet"})]
    assert not any("1970" in json.dumps(line) for line in lines)
    tail = "".join(daemon.line_text(line) + "\n" for line in lines)
    done.set_result(False, tail, error={"message": lines[-1]["message"],
                                        "disk_changed": lines[-1]["disk_changed"]})
    body = done.body.get_text()
    assert "An unencrypted install is not supported yet." in body
    assert core.BRANDING.text("done_failed_disk_unchanged") in body
    buf = done.details_view.get_buffer()
    log = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    assert "{" not in body + log
    assert "ERROR: an unencrypted install" in log
    assert not done.details.get_expanded()


def test_the_daemons_log_has_one_event_a_line():
    seen = []
    win = types.SimpleNamespace(_install_log=None, _log_tail=[])
    page = types.SimpleNamespace(append_log=seen.append)
    for _ in range(2):
        app.InstallerWindow._daemon_line(win, page, '{"type": "info"}')
    assert win._log_tail == ['{"type": "info"}\n'] * 2


@pytest.mark.parametrize("steps, changed", [
    (["validate_device"], False),
    (["validate_device", "partition"], None),
    (["validate_device", "partition", "luks"], True),
    (["validate_device", "partition", "luks", "cleanup"], True),
    (["validate_device", "cleanup"], False),
])
def test_the_page_claims_an_unchanged_disk_only_before_partitioning(steps, changed):
    """It said "Your disk was not changed" for each failure."""
    known = False
    for step in steps:
        known = daemon.disk_changed_after(step, known)
    assert known is changed
    assert daemon.daemon_event_to_line({"event": "failed"}, known)["disk_changed"] is changed


def test_a_handoff_id_is_not_shown():
    text = pages.HandoffPage.mode_text
    assert text("reboot", "default") == text("reboot", "")
    assert text("migrate", "The root is btrfs.").endswith("The root is btrfs.")


def test_every_page_has_a_name_for_the_step_line(window):
    assert all(page.get_accessible().get_name() for page in window.pages.values())


@pytest.mark.parametrize("count, selected", [(1, "/dev/sd0"), (2, None)])
def test_with_two_disks_no_disk_is_picked_for_the_person(monkeypatch, count, selected):
    rows = [{"path": f"/dev/sd{i}", "title": "Disk", "size_label": "1 TiB",
             "transport_label": "", "eligible": True, "fit": "enough_free_space",
             "excluded_reason": "", "minimal_size_bytes": 1, "free_bytes": 1,
             "existing_data": {}, "removable": False} for i in range(count)]
    monkeypatch.setattr(core, "backend", lambda: "daemon")
    monkeypatch.setattr(core, "daemon_disk_view", lambda: (rows, None))
    page = pages.DestinationPage(types.SimpleNamespace(refresh_nav=lambda: None))
    page.on_enter()
    assert (page.selected_disk() or {}).get("path") == selected
    assert page.can_continue() is (selected is not None)
