"""bootc_shared.catalog reads the catalog fixture to the contract's answers.

shared/catalog/README.md is the contract, shared/catalog/fixtures/catalog.json
a catalog that uses each rule, and fixtures/expected.json the answers. GNOME
and XFCE each had a reader and a test like this one; the two readers are
now this module, so the module is held to the fixture one time, here. Each
frontend keeps a short test of what its own code does with a leaf:
tests/unit/test_gnome_catalog_contract.py and
frontends/xfce/tests/test_catalog_contract.py.

This test does not import shared/catalog/resolve.py: that is the reference,
and a reader must agree with it through the two fixture files only.
"""

import copy
import json
import os
import pathlib
from unittest.mock import patch

import pytest
from bootc_shared import catalog, hardware

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURES = REPO / "shared" / "catalog" / "fixtures"
CATALOG = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
CASES = [(entry, index, case) for entry in EXPECTED["leaves"]
         for index, case in enumerate(entry["cases"])]


def _aliases_resolved_at_load():
    """The catalog as a page that replaces `@alias` strings at load holds
    it. The leaves must be the same."""
    loaded = copy.deepcopy(CATALOG)
    aliases = loaded.get("aliases", {})

    def resolve(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and value.startswith("@") and value[1:] in aliases:
                    node[key] = aliases[value[1:]]
                else:
                    resolve(value)
        elif isinstance(node, list):
            for item in node:
                resolve(item)

    resolve(loaded["images"])
    return loaded


def test_contract_version():
    assert EXPECTED["contract_version"] == 1


# ── Leaves ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("variant", ["as written", "aliases resolved at load"])
def test_leaves_match_the_contract(variant):
    loaded = CATALOG if variant == "as written" else _aliases_resolved_at_load()
    leaves = catalog.leaves(loaded)
    assert [leaf["imgref"] for leaf in leaves] == [e["imgref"] for e in EXPECTED["leaves"]]
    for leaf, entry in zip(leaves, EXPECTED["leaves"], strict=True):
        want = dict(entry["leaf"])
        want.pop("flatpaks_url")  # for the record only; a frontend does not read a URL
        assert leaf == want, leaf["imgref"]


def test_walk_gives_the_node_of_each_leaf():
    pairs = list(catalog.walk(CATALOG["images"], CATALOG["aliases"]))
    assert [leaf for _node, leaf in pairs] == catalog.leaves(CATALOG)
    for node, leaf in pairs:
        assert node.get("imgref") == leaf["imgref"] or "tag" in node


@pytest.mark.parametrize("entry,index,case", CASES, ids=[
    f"{entry['imgref'].rsplit('/', 1)[-1]}#{index}" for entry, index, _case in CASES])
def test_image_and_target_match_the_contract(entry, index, case):
    """The NVIDIA table: `image` and `targetImgref` of each machine case."""
    leaf = catalog.find(CATALOG, entry["imgref"])
    inputs = case["inputs"]
    image, target = catalog.source_and_target(
        leaf["imgref"], leaf["nvidia_imgref"], inputs["has_nvidia"], inputs["is_live"],
        inputs["offline_images"])
    assert image == case["recipe"]["image"]
    assert target == case["recipe"]["targetImgref"]


def test_the_fixture_covers_each_flatpak_rule():
    """A literal list, [], an alias that names a list, an alias that names a
    URL and an alias that does not exist."""
    by_ref = {entry["imgref"].rsplit("/", 1)[-1]: entry for entry in EXPECTED["leaves"]}
    assert by_ref["atlas:stable"]["cases"][0]["recipe"]["flatpaks"]
    assert by_ref["atlas:beta"]["cases"][0]["recipe"]["flatpaks"] == []
    assert "flatpaks" in by_ref["atlas-dx:latest"]["cases"][0]["absent"]
    assert "flatpaks" in by_ref["drift:edge"]["cases"][0]["absent"]
    for entry in EXPECTED["leaves"]:
        leaf = catalog.find(CATALOG, entry["imgref"])
        first = entry["cases"][0]
        if "flatpaks" in first["absent"]:
            assert leaf["flatpaks"] is None
        else:
            assert leaf["flatpaks"] == first["recipe"]["flatpaks"]
        # Never the list the catalog calls fallback_flatpaks.
        assert leaf["flatpaks"] != CATALOG["fallback_flatpaks"]


def test_flatpak_lists_resolve_offline_or_not_at_all():
    aliases = {"desktop": ["org.example.A"], "remote": "https://example.org/Brewfile"}
    assert catalog.resolve_flatpaks("@desktop", aliases) == ["org.example.A"]
    assert catalog.resolve_flatpaks("@remote", aliases) is None
    assert catalog.resolve_flatpaks("@missing", aliases) is None
    assert catalog.resolve_flatpaks("https://example.org/Brewfile", aliases) is None
    assert catalog.resolve_flatpaks(None, aliases) is None
    assert catalog.resolve_flatpaks([], aliases) == []
    assert catalog.resolve_flatpaks(["ok", 3], aliases) is None


def test_wrong_types_in_a_catalog_do_not_reach_a_leaf():
    leaves = catalog.leaves({"images": [
        {"name": "Odd", "imgref": "r/odd:1", "needs_user_creation": "no", "composefs": 1,
         "filesystems": "xfs", "filesystem": 5, "bootloader": 7, "flatpaks": ["ok", 3]},
        "not a node",
        {"name": "No registry", "tag": "stable"},
    ]})
    assert len(leaves) == 1
    odd = leaves[0]
    assert odd["needs_user_creation"] is True
    assert odd["composefs"] is False
    assert odd["filesystems"] == []
    assert odd["filesystem"] == ""
    assert odd["bootloader"] == ""
    assert odd["flatpaks"] is None


def test_extras_are_the_nearest_object_with_the_four_switches():
    """shared/catalog/README.md, "Desktop extras": the object of the nearest
    node, not merged; {} is four times off; no object is None; a key that
    is not a switch is not copied (fisherman refuses unknown recipe keys)."""
    by_ref = {e["imgref"].rsplit("/", 1)[-1]: e["leaf"]["extras"] for e in EXPECTED["leaves"]}
    assert by_ref["atlas:beta"] == {"printServices": False, "oemSetup": True,
                                    "audioNames": False, "bootSplash": False}
    assert by_ref["boreal:latest"] == dict.fromkeys(catalog.EXTRAS, False)
    assert by_ref["cirrus:1"] is None
    for entry in EXPECTED["leaves"]:
        assert catalog.find(CATALOG, entry["imgref"])["extras"] == entry["leaf"]["extras"]
    assert catalog.resolve_extras({"bootSplash": True, "notAStep": True}) == {
        "printServices": False, "oemSetup": False, "audioNames": False, "bootSplash": True}
    assert catalog.resolve_extras(None) is None
    # A wrong type: no object (lenient), a CatalogError (strict).
    for bad in (["bootSplash"], {"bootSplash": "yes"}):
        assert catalog.resolve_extras(bad) is None
        with pytest.raises(catalog.CatalogError):
            catalog.resolve_extras(bad, strict=True)
        assert catalog.leaves({"images": [{"imgref": "r/a:1", "extras": bad}]})[0]["extras"] is None
        with pytest.raises(catalog.CatalogError):
            catalog.find({"images": [{"imgref": "r/a:1", "extras": bad}]}, "r/a:1", strict=True)


def test_extras_keys_are_fishermans():
    recipe_go = REPO / "fisherman" / "fisherman" / "internal" / "recipe" / "recipe.go"
    if not recipe_go.exists():
        pytest.skip("fisherman submodule not checked out")
    import re
    src = recipe_go.read_text(encoding="utf-8")
    start = src.index("type Extras struct {")
    assert tuple(re.findall(r'`json:"([A-Za-z0-9]+)', src[start:src.index("\n}", start)])) == catalog.EXTRAS


def test_a_name_is_made_from_a_reference_with_or_without_a_registry():
    assert catalog.pretty_from_imgref("registry.example/os/atlas-dx:latest") == "Atlas DX"
    assert catalog.pretty_from_imgref("atlas-dx:latest") == "Atlas DX"
    assert catalog.pretty_from_imgref("") == ""
    assert catalog.pretty_from_imgref(None) is None


# ── find ─────────────────────────────────────────────────────────────────────

def test_the_nvidia_image_of_a_leaf_is_that_leaf():
    entry = next(e for e in EXPECTED["leaves"] if e["leaf"]["nvidia_imgref"])
    assert catalog.find(CATALOG, entry["leaf"]["nvidia_imgref"])["imgref"] == entry["imgref"]
    # A leaf whose own reference is the image wins over a variant.
    both = {"images": [{"imgref": "r/a:1", "nvidia_imgref": "r/b:1"},
                       {"imgref": "r/b:1", "needs_user_creation": False}]}
    assert catalog.find(both, "r/b:1")["needs_user_creation"] is False
    assert catalog.needs_user_creation(both, "r/b:1") is False
    assert catalog.find(CATALOG, "") is None
    assert catalog.find(None, "r/a:1") is None


def test_a_strict_search_refuses_a_wrong_catalog():
    good = {"images": [{"registry": "r/a", "composefs": True,
                        "children": [{"tag": "1"}]}]}
    assert catalog.find(good, "r/a:1", strict=True)["composefs"] is True
    assert catalog.find(good, "r/other:1", strict=True) is None
    for images in (None, {}, [None], [False], [{"children": None}]):
        with pytest.raises(catalog.CatalogError):
            catalog.find({"images": images}, "r/a:1", strict=True)
    with pytest.raises(catalog.CatalogError):
        catalog.find({"images": [{"imgref": "r/a:1", "bootloader": 7}]}, "r/a:1", strict=True)
    # Only the leaf that is found is judged: a wrong type in a different
    # leaf does not stop the install of this one.
    mixed = {"images": [{"imgref": "r/bad:1", "composefs": "yes"}, {"imgref": "r/a:1"}]}
    assert catalog.find(mixed, "r/a:1", strict=True)["imgref"] == "r/a:1"
    # CatalogError is a ValueError: a caller that fails closed on a bad
    # recipe needs no second rule.
    assert issubclass(catalog.CatalogError, ValueError)
    # The lenient search skips what the strict one refuses.
    assert catalog.find({"images": [None, {"imgref": "r/a:1"}]}, "r/a:1")["imgref"] == "r/a:1"


# ── Where the catalog is ─────────────────────────────────────────────────────

@pytest.mark.parametrize("case", EXPECTED["search_paths"],
                         ids=lambda case: "flatpak" if case["in_flatpak"] else "native")
def test_search_paths_match_the_contract(case):
    paths = catalog.search_paths(case["in_flatpak"], case["xdg_config_home"])
    assert [*paths, "<bundled>"] == case["paths"]


def test_default_search_paths_read_the_environment():
    with patch.object(catalog, "in_flatpak", return_value=False):
        assert catalog.default_search_paths({"XDG_CONFIG_HOME": "/x"}, "/home/u")[2] == \
            "/x/bootc-installer/images.json"
        # An empty XDG_CONFIG_HOME means $HOME/.config.
        assert catalog.default_search_paths({"XDG_CONFIG_HOME": ""}, "/home/u")[2] == \
            "/home/u/.config/bootc-installer/images.json"
    with patch.object(catalog, "in_flatpak", return_value=True):
        assert catalog.default_search_paths({}, "/home/u")[0] == \
            "/run/host/etc/bootc-installer/images.json"
    assert catalog.default_search_paths({}, "/home/u", flatpak=True)[0] == \
        "/run/host/etc/bootc-installer/images.json"


def test_the_override_file_is_first():
    """FISHERMAN_IMAGES_PATH: the file of a test harness or an operator is
    tried before each other place (shared/catalog/README.md)."""
    plain = catalog.default_search_paths({}, "/home/u", flatpak=False)
    with_override = catalog.default_search_paths(
        {catalog.OVERRIDE_ENV: "/tmp/x.json"}, "/home/u", flatpak=False)
    assert catalog.OVERRIDE_ENV == "FISHERMAN_IMAGES_PATH"
    assert with_override == ["/tmp/x.json", *plain]
    assert catalog.default_search_paths({catalog.OVERRIDE_ENV: ""}, "/home/u",
                                        flatpak=False) == plain
    readme = (REPO / "shared" / "catalog" / "README.md").read_text(encoding="utf-8")
    assert "FISHERMAN_IMAGES_PATH" in readme


def test_the_override_file_is_read_and_a_bad_one_does_not_stop_the_search(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"images": [{"name": "G", "imgref": "r/g:1"}]}))
    env = {catalog.OVERRIDE_ENV: str(FIXTURES / "catalog.json")}
    loaded, path = catalog.load_first(
        [*catalog.default_search_paths(env, str(tmp_path), flatpak=False)[:1], str(good)])
    assert path == str(FIXTURES / "catalog.json") and loaded == CATALOG
    env = {catalog.OVERRIDE_ENV: str(tmp_path / "absent.json")}
    loaded, path = catalog.load_first(
        [*catalog.default_search_paths(env, str(tmp_path), flatpak=False)[:1], str(good)])
    assert path == str(good)


def test_the_first_file_that_is_a_catalog_is_used(tmp_path):
    system, legacy, user = (tmp_path / name for name in ("system.json", "legacy.json", "user.json"))
    system.write_text("{not json")
    legacy.write_text(json.dumps({"no": "images"}))
    user.write_text(json.dumps({"images": [{"name": "U", "imgref": "r/u:1"}]}))
    loaded, path = catalog.load_first([str(tmp_path / "absent.json"), "", str(system),
                                       str(legacy), str(user)])
    assert path == str(user)
    assert loaded["images"][0]["imgref"] == "r/u:1"
    assert catalog.load_first([str(system)]) == (None, None)


# ── Selection and the account ────────────────────────────────────────────────

@pytest.mark.parametrize("case", EXPECTED["default_selection"], ids=lambda case: (
    f"branding={case['branding_default_image'].rsplit('/', 1)[-1] or '-'},"
    f"catalog={case['catalog_default_image'].rsplit('/', 1)[-1] or '-'}"))
def test_default_selection_matches_the_contract(case):
    loaded = dict(CATALOG)
    if case["catalog_default_image"]:
        assert loaded["default_image"] == case["catalog_default_image"]
    else:
        loaded.pop("default_image")
    assert catalog.default_imgref(loaded, case["branding_default_image"]) == case["selected"]


def test_an_image_the_catalog_does_not_have_needs_an_account():
    unknown = EXPECTED["unknown_image"]
    assert catalog.needs_user_creation(CATALOG, unknown["imgref"]) is unknown["needs_user_creation"]
    assert catalog.needs_user_creation(None, unknown["imgref"]) is True
    for entry in EXPECTED["leaves"]:
        assert catalog.needs_user_creation(CATALOG, entry["imgref"]) is \
            entry["leaf"]["needs_user_creation"]


@pytest.mark.parametrize("case", EXPECTED["live_image"], ids=lambda case: case["live_image"] or "empty")
def test_the_live_image_names_its_leaf_and_its_account_flag(case):
    """Live media: live.live_image of the probe. The NVIDIA image of a leaf
    is that leaf."""
    leaf = catalog.find(CATALOG, case["live_image"])
    assert (leaf["imgref"] if leaf else None) == case["leaf"]
    assert catalog.needs_user_creation(CATALOG, case["live_image"]) is case["needs_user_creation"]


# ── NVIDIA detection ─────────────────────────────────────────────────────────

def test_nvidia_detection_reads_pci_display_devices(tmp_path):
    def device(name, pci_class, vendor):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "class").write_text(pci_class + "\n")
        (folder / "vendor").write_text(vendor + "\n")

    device("0000:00:02.0", "0x030000", "0x8086")
    # NVIDIA's audio function is not a display device.
    device("0000:01:00.1", "0x040300", "0x10de")
    # A class that is not a number is not a display device.
    device("0000:02:00.0", "display", "0x10de")
    assert hardware.has_nvidia_gpu(str(tmp_path)) is False
    assert hardware.display_devices(str(tmp_path)) == [("0000:00:02.0", "0x8086")]
    device("0000:01:00.0", "0x030200", "0x10DE")
    assert hardware.has_nvidia_gpu(str(tmp_path)) is True
    assert hardware.has_nvidia_gpu(str(tmp_path / "missing")) is False
    os.remove(tmp_path / "0000:01:00.0" / "vendor")
    assert hardware.has_nvidia_gpu(str(tmp_path)) is False
