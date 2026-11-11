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

SHARED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared", "probe")
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
