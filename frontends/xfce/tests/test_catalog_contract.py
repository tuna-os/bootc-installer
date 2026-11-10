"""The shared catalog contract, read through this frontend's own parser.

shared/catalog/fixtures/catalog.json is a small catalog that uses each rule
of shared/catalog/README.md, and expected.json holds the answers. Every
frontend reads the two files with its own code; none imports
shared/catalog/resolve.py. A row that fails here is a recipe this frontend
would write differently from the other four.
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
               "needs_user_creation", "image_type", "extras")


def _catalog(raw=RAW):
    return core.Catalog(raw)


def test_contract_version():
    assert EXPECTED["contract_version"] == 1


@pytest.mark.parametrize("row", EXPECTED["search_paths"],
                         ids=lambda row: "flatpak" if row["in_flatpak"] else "native")
def test_search_paths(row):
    paths = core.catalog_search_paths(row["in_flatpak"], row["xdg_config_home"],
                                      bundled=("<bundled>",))
    assert paths == row["paths"]


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


def test_nvidia_detection_reads_pci_display_devices(tmp_path):
    def device(name, pci_class, vendor):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "class").write_text(pci_class + "\n")
        (folder / "vendor").write_text(vendor + "\n")

    device("0000:00:02.0", "0x030000", "0x8086")
    # NVIDIA's audio function is not a display device.
    device("0000:01:00.1", "0x040300", "0x10de")
    assert core.has_nvidia_gpu(str(tmp_path)) is False
    device("0000:01:00.0", "0x030200", "0x10de")
    assert core.has_nvidia_gpu(str(tmp_path)) is True
    assert core.has_nvidia_gpu(str(tmp_path / "missing")) is False


def test_extras_follow_the_nearest_object_and_only_the_four_switches():
    """shared/catalog/README.md, "Desktop extras"."""
    rows = {row["imgref"].rsplit("/", 1)[-1]: row["leaf"]["extras"] for row in EXPECTED["leaves"]}
    assert rows["atlas:stable"]["bootSplash"] and not rows["atlas:stable"]["oemSetup"]
    assert rows["atlas:beta"] == {"printServices": False, "oemSetup": True,
                                  "audioNames": False, "bootSplash": False}
    assert rows["boreal:latest"] == dict.fromkeys(core.EXTRAS, False)
    assert rows["cirrus:1"] is None
    assert core.resolve_extras({"bootSplash": True, "notAStep": True}) == {
        "printServices": False, "oemSetup": False, "audioNames": False, "bootSplash": True}
    assert core.resolve_extras({"bootSplash": "yes"}) is None
    assert core.resolve_extras(["bootSplash"]) is None
    recipe = core.build_recipe(disk="/dev/vda", filesystem="xfs")
    assert "extras" not in recipe
    recipe = core.build_recipe(disk="/dev/vda", filesystem="xfs", extras={})
    assert recipe["extras"] == dict.fromkeys(core.EXTRAS, False)
