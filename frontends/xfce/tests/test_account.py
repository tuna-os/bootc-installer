"""The first account: its groups (#302) and its password (#295).

The groups are shared/account/groups.json: core.DEFAULT_GROUPS is that list,
read through bootc_shared.account, and the first test fails when the two
differ. The operator's
override is `user.groups` of <etc>/bootc-installer/recipe.json.
"""

import json
import os
import sys
import types

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import core, pages  # noqa: E402

GROUPS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared",
                           "account", "groups.json")
with open(GROUPS_FILE, encoding="utf-8") as _stream:
    SHARED = json.load(_stream)


def test_the_default_is_the_shared_list():
    assert list(core.DEFAULT_GROUPS) == SHARED["default_groups"]
    assert "sudo" in core.DEFAULT_GROUPS and "wheel" in core.DEFAULT_GROUPS


def test_the_operator_file_is_the_one_the_contract_names():
    override = SHARED["override"]
    assert override["key"] == ["user", "groups"]
    assert core.operator_recipe_path(in_flatpak=False) == "/etc/" + override["file"]
    assert core.operator_recipe_path(in_flatpak=True) == "/run/host/etc/" + override["file"]


@pytest.mark.parametrize("case", SHARED["cases"], ids=lambda case: case["name"])
def test_shared_cases(case, tmp_path):
    assert core.groups_from_operator_recipe(case["operator_recipe"]) == case["groups"]
    # The same answer through the file reader.
    path = tmp_path / "recipe.json"
    if case["operator_recipe"] is not None:
        path.write_text(json.dumps(case["operator_recipe"]))
    assert core.account_groups(str(path)) == case["groups"]


def test_a_file_that_does_not_parse_keeps_the_default(tmp_path):
    path = tmp_path / "recipe.json"
    path.write_text("{nope")
    assert core.account_groups(str(path)) == SHARED["default_groups"]


class _Win:
    def needs_user_creation(self):
        return True

    def refresh_nav(self):
        pass

    def selected_leaf(self):
        return None

    def layout_source(self):
        return None


def _identity(monkeypatch):
    monkeypatch.setattr(pages, "live_check", lambda on_result: types.SimpleNamespace(
        submit=lambda recipe: None))
    page = pages.IdentityPage(_Win())
    page.show_all()
    page.username.set_text("jo")
    return page


def test_the_password_is_asked_twice_and_next_waits_for_a_match(monkeypatch):
    page = _identity(monkeypatch)
    page.password.set_text("correct horse")
    assert not page.can_continue(), "one entry is not enough"
    assert not page.password_problem.get_visible(), "nothing typed in Confirm yet"
    page.password2.set_text("correct hors")
    assert not page.can_continue()
    assert page.password_problem.get_visible()
    page.password2.set_text("correct horse")
    assert page.can_continue()
    assert not page.password_problem.get_visible()


def test_an_empty_password_still_holds_next(monkeypatch):
    page = _identity(monkeypatch)
    assert page.passwords_match()
    assert not page.can_continue()


def test_the_password_entries_can_be_revealed(monkeypatch):
    page = _identity(monkeypatch)
    setup = pages.SetupPage(_Win())
    for entry in (page.password, page.password2, setup.pass1, setup.pass2):
        secondary = Gtk.EntryIconPosition.SECONDARY
        assert not entry.get_visibility()
        assert entry.get_icon_name(secondary) == "view-reveal-symbolic"
        assert entry.get_icon_activatable(secondary)
        pages.toggle_reveal(entry)
        assert entry.get_visibility()
        assert entry.get_icon_name(secondary) == "view-conceal-symbolic"
        pages.toggle_reveal(entry)
        assert not entry.get_visibility()
