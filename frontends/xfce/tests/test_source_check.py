"""The confirm page's source check (#266) and this computer's bootc
storage (#267), through the shared reader (bootc_shared.source_check).

The probe output comes from BOOTC_INSTALLER_FAKE_PROBE, the seam every
frontend honours; with TUNA_INSTALLER_DRY_RUN the page reads it on the UI
thread, as the capture does.
"""

import json
import os
import sys
import types

import gi
import pytest

gi.require_version("Gtk", "3.0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import core, pages  # noqa: E402

SHARED = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "..", "shared", "probe")
IMAGE = "registry.example/os:1"


def _caps(name):
    with open(os.path.join(SHARED, "fixtures", "capabilities", name), encoding="utf-8") as fh:
        return json.load(fh)


def _store(name):
    with open(os.path.join(SHARED, "fixtures", "bootc-store", name), encoding="utf-8") as fh:
        return json.load(fh)


class _Win:
    def __init__(self, recipe):
        self.recipe = recipe
        self.refreshed = 0
        self.pages = {
            "destination": types.SimpleNamespace(
                selected_disk=lambda: {"path": "/dev/vdz", "title": "Disk"}),
            "source": types.SimpleNamespace(live_image=""),
        }

    def build_recipe(self):
        return dict(self.recipe)

    def refresh_nav(self):
        self.refreshed += 1


def _recipe(**extra):
    r = {"disk": "/dev/vdz", "filesystem": "btrfs", "encryption": {"type": "none"},
         "hostname": "box", "image": IMAGE}
    r.update(extra)
    return r


@pytest.fixture
def probe_file(tmp_path, monkeypatch):
    def write(caps, store=None):
        doc = {"protocol_version": 1, "capabilities": caps}
        if store is not None:
            doc["bootc_store"] = store
        path = tmp_path / "probe.json"
        path.write_text(json.dumps(doc))
        monkeypatch.setenv("BOOTC_INSTALLER_FAKE_PROBE", str(path))
        monkeypatch.setenv("TUNA_INSTALLER_DRY_RUN", "1")
        core._probe_cache.clear()
    yield write
    core._probe_cache.clear()


def _matching():
    caps = _caps("caps-matching-ostree-current.json")
    caps["source"]["ref"] = IMAGE
    caps["target"]["update_ref_from"] = "source"
    return caps


def test_ready_source_shows_the_defaults_and_allows_install(probe_file):
    probe_file(_matching(), _store("store-bootc-host-default.json"))
    page = pages.ConfirmPage(_Win(_recipe()))
    page.on_enter()
    text = page.source_label.get_text()
    assert core.BRANDING.text("source_check_ready") in text
    assert core.BRANDING.text("source_install_from").replace("{value}", IMAGE) in text
    assert core.BRANDING.text("source_check_default_filesystem").replace("{value}", "btrfs") in text
    # The live host's storage is listed as this computer's, never as a source.
    assert core.BRANDING.text("bootc_store_listed") in text
    assert core.BRANDING.text("bootc_store_kind_booted") in text
    assert page.can_continue()


def test_unified_storage_is_blocked(probe_file):
    probe_file(_matching())
    page = pages.ConfirmPage(_Win(_recipe(unifiedStorage=True)))
    page.on_enter()
    assert core.BRANDING.text("source_check_blocked") in page.source_label.get_text()
    assert not page.can_continue()


def test_a_reply_for_another_source_is_dropped(probe_file):
    probe_file(_caps("caps-matching-ostree-current.json"))
    page = pages.ConfirmPage(_Win(_recipe()))
    page.on_enter()
    assert page.source_label.get_text() == core.BRANDING.text("source_check_checking")
    assert page.can_continue()


def test_an_older_fisherman_is_not_a_green_check(probe_file, monkeypatch, tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"protocol_version": 1}))
    monkeypatch.setenv("BOOTC_INSTALLER_FAKE_PROBE", str(path))
    monkeypatch.setenv("TUNA_INSTALLER_DRY_RUN", "1")
    page = pages.ConfirmPage(_Win(_recipe()))
    page.on_enter()
    text = page.source_label.get_text()
    assert core.BRANDING.text("source_check_unsupported") in text
    assert core.BRANDING.text("source_check_ready") not in text
    assert page.can_continue()


def test_a_late_reply_of_an_older_visit_is_dropped(probe_file):
    probe_file(_matching())
    page = pages.ConfirmPage(_Win(_recipe()))
    page.on_enter()
    shown = page.source_label.get_text()
    req = {"source": IMAGE, "live_root": False, "target": "", "features": []}
    page._on_source(page.source_generation - 1, req, None)
    assert page.source_label.get_text() == shown


# The install source (#267): this computer's system from its bootc storage.
UPDATE_REF = "ghcr.io/example/os:stable"


class _ReuseWin(_Win):
    """A window whose build_recipe() applies the confirm page's source, as
    the real one does."""

    def wizard_recipe(self):
        return dict(self.recipe)

    def build_recipe(self):
        return self.pages["confirm"].apply_source(self.wizard_recipe())


class _FakeCheck:
    def __init__(self, on_result):
        self.on_result = on_result
        self.submitted = []

    def submit(self, recipe):
        self.submitted.append(recipe)


@pytest.fixture
def reuse_page(tmp_path, monkeypatch):
    def make(live=False, store="store-inaccessible.json"):
        caps = _caps("caps-matching-ostree-current.json")
        doc = {"protocol_version": 1, "capabilities": caps,
               "live": {"is_live": live}, "bootc_store": _store(store)}
        path = tmp_path / "probe.json"
        path.write_text(json.dumps(doc))
        monkeypatch.setenv("BOOTC_INSTALLER_FAKE_PROBE", str(path))
        monkeypatch.setenv("TUNA_INSTALLER_DRY_RUN", "1")
        core._probe_cache.clear()
        checks = []
        monkeypatch.setattr(pages, "live_check",
                            lambda cb: checks.append(_FakeCheck(cb)) or checks[-1])
        win = _ReuseWin(_recipe(image=UPDATE_REF, targetImgref=UPDATE_REF))
        page = pages.ConfirmPage(win)
        win.pages["confirm"] = page
        return page, win, checks
    yield make
    core._probe_cache.clear()


def test_this_computers_system_is_offered_but_never_the_default(reuse_page):
    page, win, _checks = reuse_page()
    page.on_enter()
    assert page.reuse_box.get_visible()
    assert page.reuse_download.get_active()
    assert page.reuse_local.get_label() == core.BRANDING.text("source_reuse_local")
    recipe = win.build_recipe()
    assert recipe["image"] == UPDATE_REF
    assert "sourceReuse" not in recipe


def test_picking_it_writes_source_reuse_and_keeps_the_update_reference(reuse_page):
    page, win, checks = reuse_page()
    page.on_enter()
    page.reuse_local.set_active(True)
    recipe = win.build_recipe()
    assert recipe["image"] == ""
    assert recipe["targetImgref"] == UPDATE_REF
    assert recipe["sourceReuse"] == {"store": "bootc", "digest": "sha256:" + "1" * 64,
                                     "platform": "x86_64"}
    assert "bootc_store_reuse" in recipe["experimental"]
    assert core.BRANDING.text("source_reuse_local_detail") in page.reuse_detail.get_text()
    summary = page.summary.get_text()
    assert core.BRANDING.text("source_reuse_install_from").replace("{value}", UPDATE_REF) in summary
    # fisherman's partial check gets the reuse fields, never the recipe's secrets.
    assert checks and checks[-1].submitted[-1]["sourceReuse"] == recipe["sourceReuse"]
    assert "encryption" not in checks[-1].submitted[-1]
    assert page.can_continue()
    # A copy needs no download.
    assert page.reuse_selected


def test_a_validate_code_shows_through_its_copy_line_and_holds_install(reuse_page):
    page, _win, checks = reuse_page()
    page.on_enter()
    page.reuse_local.set_active(True)
    checks[-1].on_result([{"code": "source_reuse_item_not_found", "field": "sourceReuse",
                           "message": "no deployment has the digest"}], None)
    assert page.reuse_problem.get_text() == core.BRANDING.text(
        "validate_source_reuse_item_not_found")
    assert not page.can_continue()
    page.reuse_download.set_active(True)
    assert page.can_continue()


def test_never_offered_on_live_media(reuse_page):
    page, win, _checks = reuse_page(live=True)
    page.on_enter()
    assert not page.reuse_box.get_visible()
    assert "sourceReuse" not in win.build_recipe()


def test_the_shared_reuse_cases():
    """Every case of shared/probe/source-reuse-cases.json through the reader
    that this frontend calls."""
    from bootc_shared import source_check
    with open(os.path.join(SHARED, "source-reuse-cases.json"), encoding="utf-8") as fh:
        cases = json.load(fh)["cases"]
    for case in cases:
        if case["probe_failed"]:
            probe = None
        else:
            probe = {"protocol_version": 1}
            if case["fixture"]:
                probe["bootc_store"] = _store(case["fixture"])
            if case["live"] is not None:
                probe["live"] = {"is_live": case["live"]}
        assert source_check.reuse_source(probe, case["update_ref"]) == case["expected"], \
            case["name"]
