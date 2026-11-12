"""The cross-frontend recipe contract: the XFCE half (#226, #186).

shared/recipe/fixtures/compliance.json holds one set of choices per case and
the one recipe that every frontend must write for it. This test makes the
choices on the real SetupPage (filesystem, encryption, passphrase), gives the
window the selected leaf of the shared catalog fixture, the disk and the
identity page's values, and builds the recipe through
InstallerWindow.build_recipe, the method that the Install button calls. The
recipe is normalised with the fixture's table (shared/recipe/compliance.py)
and its bytes must be the expected recipe's.
"""

import importlib.util
import json
import os
import sys
import types

import gi

gi.require_version("Gtk", "3.0")
import pytest  # noqa: E402
from gi.repository import Gtk  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bootc_shared import branding  # noqa: E402

from tuna_installer_xfce import app, core, pages  # noqa: E402

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_spec = importlib.util.spec_from_file_location(
    "recipe_compliance", os.path.join(REPO, "shared", "recipe", "compliance.py"))
compliance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compliance)

FIXTURE = compliance.load()
with open(os.path.join(REPO, FIXTURE["catalog"]), encoding="utf-8") as _stream:
    CATALOG = core.Catalog(json.load(_stream))


def _text(value):
    return types.SimpleNamespace(get_text=lambda: value)


def xfce_recipe(case, monkeypatch, tmp_path):
    choices = case["choices"]
    machine = choices["machine"]
    leaf = CATALOG.find(choices["image"])
    assert leaf is not None

    branding_file = tmp_path / "branding.json"
    branding_file.write_text(json.dumps(FIXTURE["branding"]), encoding="utf-8")
    monkeypatch.setattr(core, "BRANDING", branding.resolve(
        branding_paths=[str(branding_file)], os_release_paths=[]))
    monkeypatch.setattr(core, "has_nvidia_gpu", lambda *a, **k: machine["has_nvidia"])
    monkeypatch.setattr(core, "offline_images", lambda *a, **k: list(machine["offline_images"]))

    source = types.SimpleNamespace(selection=lambda: {"leaf": leaf}, live=machine["is_live"])
    win = types.SimpleNamespace(pages={"source": source}, refresh_nav=lambda: None)
    win.selected_leaf = lambda: app.InstallerWindow.selected_leaf(win)
    win.layout_source = lambda: app.InstallerWindow.layout_source(win)
    win.needs_user_creation = lambda: app.InstallerWindow.needs_user_creation(win)
    win.wizard_recipe = lambda: app.InstallerWindow.wizard_recipe(win)

    # The setup page, as the person uses it.
    setup = pages.SetupPage(win)
    setup.on_enter()
    if setup.fs_combo.get_active_id() != choices["filesystem"]:
        assert setup.fs_combo.set_active_id(choices["filesystem"])
    enc = choices["encryption"]
    radio = next(r for r in setup.enc_radios if r.value == enc["type"])
    radio.set_active(True)
    setup.pass1.set_text(enc["passphrase"])
    setup.pass2.set_text(enc["passphrase"])

    account = choices["account"] or {"username": "", "fullname": "", "password": ""}
    keyboard = choices["keyboard"] or {}
    assert set(keyboard) <= {"layout"}, "the identity page offers layouts only"
    win.pages.update(
        setup=setup,
        destination=types.SimpleNamespace(selected_disk=lambda: {"path": choices["disk"]}),
        identity=types.SimpleNamespace(
            hostname=_text(choices["hostname"]), username=_text(account["username"]),
            fullname=_text(account["fullname"]), password=_text(account["password"]),
            region_choices=lambda: {"locale": choices["locale"],
                                    "keyboard_layout": keyboard.get("layout", ""),
                                    "timezone": choices["timezone"]}))
    monkeypatch.setattr(core, "account_groups", lambda path=None: list(core.DEFAULT_GROUPS))
    return app.InstallerWindow.build_recipe(win)


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["name"])
def test_xfce_writes_the_expected_recipe(case, monkeypatch, tmp_path):
    got = compliance.canonical(xfce_recipe(case, monkeypatch, tmp_path))
    assert got.decode() == compliance.canonical(case["recipe"]).decode()
