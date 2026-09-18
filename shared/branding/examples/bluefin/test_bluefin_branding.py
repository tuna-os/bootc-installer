"""Bluefin's branding, pinned.

This test travels with the branding (projectbluefin/dakota-iso), not with
the installer: the installer must not know Bluefin exists. It needs the
shared resolver (shared/branding/branding.py) importable and, if
`jsonschema` is installed, validates against branding.schema.json.
"""

import importlib.util
import json
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SHARED = HERE.parents[1]
BRANDING = json.loads((HERE / "branding.json").read_text())


def _resolver():
    spec = importlib.util.spec_from_file_location("branding", SHARED / "branding.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((SHARED / "branding.schema.json").read_text())
    jsonschema.validate(BRANDING, schema)


def test_identity():
    b = _resolver().from_sources(BRANDING, None)
    assert b.name == "Bluefin"
    assert b.id == "bluefin"
    assert b.default_hostname == "bluefin"
    assert b.default_image == "ghcr.io/projectbluefin/dakota:latest"
    assert b.store_url == "https://store.projectbluefin.io"
    assert b.home_url == "https://projectbluefin.io"


def test_flavour_text():
    b = _resolver().from_sources(BRANDING, None)
    assert b.text("welcome_title") == "Welcome to Bluefin"
    assert b.text("confirm_button") == "Become Legend"
    assert b.text("confirm_subtitle") == '"Indeed." \u2014 Commander Zavala'
    assert "war with your old OS" in b.text("confirm_body")
    assert b.quote_for("pt_BR.UTF-8").endswith("Ayrton Senna")
    assert b.quote_for("en_US") == b.text("confirm_subtitle")
    assert b.text("store_label") == "Get Bluefin gear at store.projectbluefin.io"


def test_assets_and_gnome_extras_point_at_the_iso_paths():
    b = _resolver().from_sources(BRANDING, None)
    for key in ("welcome_image", "complete_image", "store_qr"):
        assert b.assets[key].startswith("/usr/share/bootc-installer/branding/"), key
    gnome = b.extensions["gnome"]
    assert gnome["video"].endswith("installer-video.webm")
    assert gnome["credits"].endswith("credits.json")
    assert gnome["tour_welcome_title"] == "Installing {name}"
    shipped = {p.name for p in (HERE / "assets").iterdir()}
    for path in list(b.assets.values()) + [gnome["video"], gnome["credits"]]:
        assert pathlib.Path(path).name in shipped, path
