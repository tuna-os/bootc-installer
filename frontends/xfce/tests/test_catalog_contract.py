"""What this frontend does with the shared catalog reader.

shared/catalog/fixtures/catalog.json is a small catalog that uses each rule
of shared/catalog/README.md, and expected.json holds the answers. The
reader is bootc_shared.catalog, which GNOME also uses; the test of the
reader itself is tests/unit/test_shared_python_catalog.py at the repository
root. This file is the XFCE half: the view that the pages read
(core.Catalog, core.ImageLeaf), the bundled catalog, and the recipe that
this frontend writes for each leaf on each machine.
"""

import json
import os

import pytest

from tuna_installer_xfce import core

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared",
                        "catalog", "fixtures")
CATALOG_FILE = os.path.join(FIXTURES, "catalog.json")

with open(CATALOG_FILE, encoding="utf-8") as _stream:
    RAW = json.load(_stream)
with open(os.path.join(FIXTURES, "expected.json"), encoding="utf-8") as _stream:
    EXPECTED = json.load(_stream)

# A missing key and these values mean the same thing to fisherman.
EMPTY = {"bootloader": "", "composeFsBackend": False, "imageType": "bootc"}

LEAF_FIELDS = ("imgref", "name", "product", "channel", "label", "path", "breadcrumb",
               "nvidia_imgref", "bootloader", "composefs", "filesystem", "filesystems",
               "default_hostname", "flatpaks", "flatpak_var_path",
               "needs_user_creation", "image_type")


def _catalog(raw=RAW):
    return core.Catalog(raw)


def test_contract_version():
    assert EXPECTED["contract_version"] == 1


def test_the_bundled_catalog_is_last_and_is_this_frontends_own():
    paths = core.catalog_search_paths(False, "/home/user/.config")
    assert paths[:3] == EXPECTED["search_paths"][0]["paths"][:3]
    assert tuple(paths[3:]) == core.BUNDLED_CATALOGS


def test_the_fixture_loads_through_the_file_reader():
    catalog = core.load_catalog([CATALOG_FILE])
    assert catalog.path == CATALOG_FILE
    assert [leaf.imgref for leaf in catalog.leaves] == [
        row["imgref"] for row in EXPECTED["leaves"]]


@pytest.mark.parametrize("row", EXPECTED["leaves"], ids=lambda row: row["imgref"])
def test_resolved_leaf(row):
    leaf = _catalog().find(row["imgref"])
    assert leaf is not None
    for field in LEAF_FIELDS:
        assert getattr(leaf, field) == row["leaf"][field], field


@pytest.mark.parametrize("row", EXPECTED["leaves"], ids=lambda row: row["imgref"])
def test_recipe_for_each_machine(row):
    leaf = _catalog().find(row["imgref"])
    for case in row["cases"]:
        inputs = case["inputs"]
        recipe = core.recipe_for_leaf(
            leaf, has_nvidia=inputs["has_nvidia"], live=inputs["is_live"],
            offline=set(inputs["offline_images"]), disk="/dev/vda",
            username="jo", password="pw")
        for key, want in case["recipe"].items():
            got = recipe.get(key, EMPTY[key]) if key in EMPTY else recipe.get(key)
            assert got == want, (inputs, key)
        for key in case["absent"]:
            assert key not in recipe, (inputs, key)
        # The account follows the leaf's flag.
        assert ("user" in recipe) == row["leaf"]["needs_user_creation"]
        # fallback_flatpaks never reaches a recipe.
        assert recipe.get("flatpaks") != RAW["fallback_flatpaks"]


@pytest.mark.parametrize("row", EXPECTED["default_selection"], ids=lambda row: (
    f"branding={row['branding_default_image'] or '-'},"
    f"catalog={row['catalog_default_image'] or '-'}"))
def test_default_selection(row):
    raw = dict(RAW)
    if row["catalog_default_image"]:
        assert raw["default_image"] == row["catalog_default_image"]
    else:
        del raw["default_image"]
    leaf = _catalog(raw).default_leaf(row["branding_default_image"])
    assert (leaf.imgref if leaf else None) == row["selected"]


def test_an_image_the_catalog_does_not_have_needs_an_account():
    unknown = EXPECTED["unknown_image"]
    assert _catalog().needs_user_creation(unknown["imgref"]) is unknown["needs_user_creation"]


def test_the_nvidia_variant_of_a_leaf_is_that_leaf():
    row = next(row for row in EXPECTED["leaves"] if row["leaf"]["nvidia_imgref"])
    leaf = _catalog().find(row["leaf"]["nvidia_imgref"])
    assert leaf is not None and leaf.imgref == row["imgref"]


def test_this_frontend_reads_the_shared_reader_and_has_no_copy():
    import inspect

    from bootc_shared import catalog as shared
    from bootc_shared import hardware

    assert core.shared_catalog is shared
    assert core.resolve_flatpaks is shared.resolve_flatpaks
    assert core.has_nvidia_gpu is hardware.has_nvidia_gpu
    source = inspect.getsource(core)
    # No second walk of the tree, and no second table of inherited keys.
    assert '"children"' not in source
    assert "_INHERITED" not in source
    assert "shared_catalog.walk(" in source


def test_the_harness_override_is_the_shared_one(monkeypatch, tmp_path):
    monkeypatch.setenv("FISHERMAN_IMAGES_PATH", CATALOG_FILE)
    assert core.images_json_paths()[0] == CATALOG_FILE
    assert core.load_catalog().path == CATALOG_FILE
    monkeypatch.delenv("FISHERMAN_IMAGES_PATH")
    assert CATALOG_FILE not in core.images_json_paths()
    assert tuple(core.images_json_paths()[-len(core.BUNDLED_CATALOGS):]) == core.BUNDLED_CATALOGS


def test_a_wrong_type_in_a_catalog_does_not_reach_the_recipe():
    """`"filesystem": 5` used to reach the recipe of this frontend."""
    catalog = core.Catalog({"images": [
        {"name": "Odd", "imgref": "r.example/odd:1", "filesystem": 5, "bootloader": 7,
         "composefs": "yes", "needs_user_creation": "no", "image_type": None}]})
    leaf = catalog.find("r.example/odd:1")
    recipe = core.recipe_for_leaf(leaf, disk="/dev/vda", username="jo", password="pw")
    assert recipe["filesystem"] == core.DEFAULT_FILESYSTEM
    assert recipe.get("bootloader", "") == ""
    assert recipe.get("composeFsBackend", False) is False
    assert "user" in recipe


def test_the_view_has_the_words_of_the_node():
    catalog = core.Catalog({"images": [
        {"imgref": "r.example/plain:1"},
        {"name": "Atlas", "desc": "A desktop", "subtitle": 7, "imgref": "r.example/atlas:1"}]})
    plain, atlas = catalog.leaves
    # A leaf with no name above it still has a row label.
    assert plain.breadcrumb == plain.label == "Plain"
    assert (atlas.desc, atlas.subtitle, atlas.breadcrumb) == ("A desktop", "", "Atlas")
