"""The image page: what is selected at the start, what a row says, and the
filter (#289); and where the account flag comes from on live media (#288).

The page used to activate the first radio of a list sorted by leaf name, so
Next installed an image the branding never named. Rows showed the leaf's
name, which is a channel: "Stable" fifteen times in the bundled catalog.
"""

import json
import os
import sys
import types

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import app, core, pages  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared",
                       "catalog", "fixtures", "catalog.json")
with open(FIXTURE, encoding="utf-8") as _stream:
    RAW = json.load(_stream)


class _Win:
    def __init__(self):
        self.refreshed = 0

    def refresh_nav(self):
        self.refreshed += 1


def _page(monkeypatch, raw=RAW, branding_default="", live=False, live_image="",
          offline=()):
    monkeypatch.setattr(core, "is_live", lambda: live)
    monkeypatch.setattr(core, "live_image", lambda: live_image)
    monkeypatch.setattr(core, "offline_images", lambda: set(offline))
    monkeypatch.setattr(core, "load_catalog", lambda: core.Catalog(raw))
    monkeypatch.setattr(core, "BRANDING", types.SimpleNamespace(
        default_image=branding_default, text=core.BRANDING.text))
    win = _Win()
    return pages.SourcePage(win), win


def _selected(page):
    leaf = (page.selection() or {}).get("leaf")
    return leaf.imgref if leaf else None


def test_the_catalog_default_is_selected(monkeypatch):
    page, _ = _page(monkeypatch)
    assert _selected(page) == RAW["default_image"]
    assert page.can_continue()


def test_the_branding_default_wins_over_the_catalogs(monkeypatch):
    page, _ = _page(monkeypatch, branding_default="registry.example/os/atlas:beta")
    assert _selected(page) == "registry.example/os/atlas:beta"


def test_no_default_selects_nothing_and_holds_next(monkeypatch):
    raw = {key: value for key, value in RAW.items() if key != "default_image"}
    page, win = _page(monkeypatch, raw=raw,
                      branding_default="registry.example/os/not-in-the-catalog:1")
    assert page.radios, "the catalog rows are there"
    assert page.selection() is None
    assert not page.can_continue()
    assert page.choose.get_visible()
    # Choosing a row releases Next and refreshes the window's buttons.
    page.radios[0].set_active(True)
    assert page.can_continue()
    assert win.refreshed >= 1
    assert not page.choose.get_visible()


def test_rows_say_the_product_and_the_channel(monkeypatch):
    page, _ = _page(monkeypatch)
    labels = [radio.get_label() for radio in page.radios]
    assert "Atlas › Stable" in labels
    assert "Atlas › Atlas DX › Latest" in labels
    # The breadcrumb is unique where the leaf name is not.
    assert len(set(labels)) == len(labels)
    assert "Stable" not in labels


def test_the_filter_hides_rows_that_do_not_match(monkeypatch):
    page, _ = _page(monkeypatch)
    page.show_all()
    page.search.set_text("boreal")
    page._on_search(page.search)
    shown = [text for box, text in page._rows if box.get_visible()]
    assert len(shown) == 1 and "boreal" in shown[0]
    # The image reference matches too, and an empty filter shows every row.
    page.search.set_text("OS/DRIFT:KIOSK")
    page._on_search(page.search)
    assert [box.get_visible() for box, _ in page._rows].count(True) == 1
    page.search.set_text("")
    page._on_search(page.search)
    assert all(box.get_visible() for box, _ in page._rows)


def test_live_media_starts_on_install_this_system(monkeypatch):
    page, _ = _page(monkeypatch, live=True,
                    live_image="registry.example/os/boreal:latest")
    assert page.selection() == {"live": True}
    assert page.can_continue()


def _needs_user(page):
    win = types.SimpleNamespace(pages={"source": page})
    return app.InstallerWindow.needs_user_creation(win)


def test_live_media_reads_the_flag_of_the_running_image(monkeypatch):
    # Boreal sets needs_user_creation false: no account page on its ISO.
    page, _ = _page(monkeypatch, live=True,
                    live_image="registry.example/os/boreal:latest")
    assert _needs_user(page) is False
    # A running image the catalog does not have needs an account.
    page, _ = _page(monkeypatch, live=True,
                    live_image="registry.example/os/not-in-the-catalog:1")
    assert _needs_user(page) is True


def test_the_selected_leaf_decides_the_account(monkeypatch):
    page, _ = _page(monkeypatch)
    assert _needs_user(page) is True          # Atlas Stable: unset, so an account
    for radio in page.radios:
        if radio.payload.get("leaf").imgref == "registry.example/os/atlas:beta":
            radio.set_active(True)
    assert _needs_user(page) is False


class _IdentityWin:
    def __init__(self, leaf):
        self.leaf = leaf

    def needs_user_creation(self):
        return True

    def refresh_nav(self):
        pass

    def selected_leaf(self):
        return self.leaf


def test_the_hostname_is_seeded_from_the_selected_image(monkeypatch):
    monkeypatch.setattr(pages, "live_check", lambda on_result: types.SimpleNamespace(
        submit=lambda recipe: None))
    catalog = core.Catalog(RAW)
    win = _IdentityWin(catalog.find("registry.example/os/atlas:stable"))
    page = pages.IdentityPage(win)
    page.on_enter()
    assert page.hostname.get_text() == "atlas"
    # Another image, and the person typed nothing: its hostname applies.
    win.leaf = catalog.find("registry.example/os/boreal:latest")
    page.on_enter()
    assert page.hostname.get_text() == "boreal"
    # An image with no default_hostname reads the branding's.
    win.leaf = catalog.find("registry.example/os/cirrus:1")
    page.on_enter()
    assert page.hostname.get_text() == core.BRANDING.default_hostname
    # What the person typed stays.
    page.hostname.set_text("mine")
    win.leaf = catalog.find("registry.example/os/atlas:stable")
    page.on_enter()
    assert page.hostname.get_text() == "mine"
