"""GNOME reads the catalog fixture to the contract's answers.

shared/catalog/README.md is the contract, shared/catalog/fixtures/catalog.json
a catalog that uses each rule, and fixtures/expected.json the answers. This
test feeds the fixture through GNOME's own code and compares:

    utils/catalog.py      where the catalog is, the leaves, the default
                          selection, the account flag
    catalog.leaf_finals   what the image page hands on for a selected leaf
    disk_plan             what the disk page selects before the user picks
    Processor             the recipe

It does not import shared/catalog/resolve.py: that is the reference, and a
frontend must agree with it through the two fixture files only.
"""

import copy
import json
import os
import sys
from unittest.mock import patch

import pytest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from bootc_installer.defaults.disk_plan import (  # noqa: E402
    build_auto_partition_recipe, build_disk_finals, filesystem_options)
from bootc_installer.utils import catalog  # noqa: E402
from bootc_installer.utils import user_step  # noqa: E402
from bootc_installer.utils.processor import Processor  # noqa: E402

FIXTURES = os.path.join(REPO, "shared", "catalog", "fixtures")

# A recipe without the key means the same to fisherman as these values.
EMPTY = {"bootloader": "", "composeFsBackend": False, "imageType": "bootc"}


def _json(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as stream:
        return json.load(stream)


CATALOG = _json("catalog.json")
EXPECTED = _json("expected.json")
CASES = [(entry["imgref"], index, entry, case)
         for entry in EXPECTED["leaves"] for index, case in enumerate(entry["cases"])]


class _Disk:
    disk = "/dev/vda"
    pretty_size = "64 GB"
    size = 64 * 1024 ** 3


def _resolved_like_the_page():
    """The catalog as bootc_installer/defaults/image.py holds it: the
    `@alias` strings are replaced when the file is loaded."""
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


def _recipe_for(leaf, inputs, loaded):
    """The recipe GNOME writes when the user selects `leaf` and changes
    nothing: the image step's finals, the disk step's finals, the Processor."""
    image_finals = catalog.leaf_finals(leaf)
    options, selected = filesystem_options(image_finals)
    disk_finals = build_disk_finals(
        build_auto_partition_recipe(_Disk()), options[selected], "host")
    fake_image_module = type(sys)("bootc_installer.defaults.image")
    fake_image_module._MANIFEST = loaded
    with patch.dict(sys.modules, {"bootc_installer.defaults.image": fake_image_module}), \
            patch("bootc_installer.core.system.Systeminfo.has_nvidia_gpu",
                  return_value=inputs["has_nvidia"]), \
            patch("bootc_installer.core.system.Systeminfo.is_live",
                  return_value=inputs["is_live"]), \
            patch("bootc_installer.core.system.Systeminfo.offline_images",
                  return_value=list(inputs["offline_images"])):
        return Processor.gen_install_recipe("", [image_finals, disk_finals], {})


@pytest.mark.parametrize("variant", ["as written", "aliases resolved at load"])
def test_leaves_match_the_contract(variant):
    loaded = CATALOG if variant == "as written" else _resolved_like_the_page()
    leaves = catalog.leaves(loaded)
    assert [leaf["imgref"] for leaf in leaves] == [e["imgref"] for e in EXPECTED["leaves"]]
    for leaf, entry in zip(leaves, EXPECTED["leaves"], strict=True):
        want = dict(entry["leaf"])
        want.pop("flatpaks_url")  # for the record only; a frontend does not read a URL
        assert leaf == want, leaf["imgref"]


@pytest.mark.parametrize("imgref,index,entry,case", CASES,
                         ids=[f"{imgref.rsplit('/', 1)[-1]}#{index}"
                              for imgref, index, _e, _c in CASES])
def test_recipe_matches_the_contract(imgref, index, entry, case):
    for loaded in (CATALOG, _resolved_like_the_page()):
        leaf = catalog.find(loaded, imgref)
        assert leaf is not None
        recipe = _recipe_for(leaf, case["inputs"], loaded)
        for key, want in case["recipe"].items():
            got = recipe.get(key, EMPTY[key]) if key in EMPTY else recipe.get(key)
            assert got == want, f"{key}: expected {want!r}, found {got!r}"
        for key in case["absent"]:
            assert key not in recipe, f"{key} must be left out, found {recipe[key]!r}"
        # Never the list the catalog calls fallback_flatpaks.
        assert "org.example.NeverSent" not in json.dumps(recipe)


def test_the_fixture_covers_each_flatpak_rule():
    """A literal list, [], an alias that names a list, an alias that names a
    URL and an alias that does not exist: the test above has a case for each."""
    by_ref = {entry["imgref"].rsplit("/", 1)[-1]: entry for entry in EXPECTED["leaves"]}
    assert by_ref["atlas:stable"]["cases"][0]["recipe"]["flatpaks"]
    assert by_ref["atlas:beta"]["cases"][0]["recipe"]["flatpaks"] == []
    assert "flatpaks" in by_ref["atlas-dx:latest"]["cases"][0]["absent"]
    assert "flatpaks" in by_ref["drift:edge"]["cases"][0]["absent"]


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


def test_the_first_file_that_is_a_catalog_is_used(tmp_path):
    system, legacy, user = (tmp_path / name for name in ("system.json", "legacy.json", "user.json"))
    system.write_text("{not json")
    legacy.write_text(json.dumps({"no": "images"}))
    user.write_text(json.dumps({"images": [{"name": "U", "imgref": "r/u:1"}]}))
    loaded, path = catalog.load_first([str(tmp_path / "absent.json"), str(system),
                                       str(legacy), str(user)])
    assert path == str(user)
    assert loaded["images"][0]["imgref"] == "r/u:1"
    assert catalog.load_first([str(system)]) == (None, None)


@pytest.mark.parametrize("case", EXPECTED["default_selection"], ids=lambda case: (
    f"branding={case['branding_default_image'].rsplit('/', 1)[-1] or '-'},"
    f"catalog={case['catalog_default_image'].rsplit('/', 1)[-1] or '-'}"))
def test_default_selection_matches_the_contract(case):
    loaded = dict(CATALOG)
    if not case["catalog_default_image"]:
        loaded.pop("default_image")
    assert catalog.default_imgref(loaded, case["branding_default_image"]) == case["selected"]


def test_an_image_the_catalog_does_not_have_needs_an_account():
    unknown = EXPECTED["unknown_image"]
    assert catalog.needs_user_creation(CATALOG, unknown["imgref"]) is unknown["needs_user_creation"]
    assert catalog.needs_user_creation(None, unknown["imgref"]) is True
    assert catalog.custom_image_finals(unknown["imgref"])["needs_user_creation"] is True


@pytest.mark.parametrize("entry", EXPECTED["leaves"], ids=lambda e: e["imgref"].rsplit("/", 1)[-1])
def test_the_account_flag_on_live_media_is_that_of_the_installed_image(entry):
    """Live media has no image page: the flag is the one of the leaf whose
    reference is the image that is installed, not of the first row."""
    want = entry["leaf"]["needs_user_creation"]
    assert user_step.account_needed_for({"imgref": entry["imgref"]}, CATALOG) is want
    window = type("Window", (), {"image_step": None, "recipe": {"imgref": entry["imgref"]}})()
    with patch.object(user_step, "_loaded_catalog", return_value=CATALOG):
        assert user_step.user_step_shows(window, {}) is want


def test_the_account_flag_defaults_to_an_account():
    assert user_step.account_needed_for({"imgref": "r/unknown:1"}, CATALOG) is True
    assert user_step.account_needed_for({}, CATALOG) is True
    assert user_step.account_needed_for({"imgref": "r/x:1"}, {"images": []}) is True
    # The system recipe's own `images`: the entry for the image, with the
    # same default; a single entry that names no image is its metadata.
    images = [{"imgref": "r/a:1"}, {"imgref": "r/b:1", "needs_user_creation": False}]
    assert user_step.account_needed_for({"imgref": "r/a:1", "images": images}, CATALOG) is True
    assert user_step.account_needed_for({"imgref": "r/b:1", "images": images}, CATALOG) is False
    assert user_step.account_needed_for(
        {"imgref": "r/c:1", "images": [{"needs_user_creation": False}]}, CATALOG) is False
    assert user_step.account_needed_for(
        {"imgref": "r/c:1", "images": [{"filesystem": "xfs"}]}, CATALOG) is True


def test_a_choice_of_filesystems_is_the_users():
    """Drift Edge offers ext4 and btrfs and starts at ext4. The user's pick
    from that list stands; the image's `filesystem` is only the start."""
    leaf = catalog.find(CATALOG, "registry.example/os/drift:edge")
    finals = catalog.leaf_finals(leaf)
    assert filesystem_options(finals) == (["ext4", "btrfs"], 0)
    disk = build_disk_finals(build_auto_partition_recipe(_Disk()), "btrfs", "host")
    with patch("bootc_installer.core.system.Systeminfo.has_nvidia_gpu", return_value=False):
        recipe = Processor.gen_install_recipe("", [finals, disk], {})
    assert recipe["filesystem"] == "btrfs"
    assert recipe["btrfsSubvolumes"] is True
    # The start is the leaf's `filesystem`, also when it is not the first.
    assert filesystem_options({"supported_filesystems": ["ext4", "btrfs"],
                               "default_filesystem": "btrfs"}) == (["ext4", "btrfs"], 1)
    assert filesystem_options({}) == (["xfs"], 0)


def test_extras_come_from_the_system_recipe_or_the_host_catalog_on_live_media():
    """Live media has no image step. The object is then the system recipe's,
    or the one of the catalog entry of the installed image."""
    disk = build_disk_finals(build_auto_partition_recipe(_Disk()), "xfs", "host")
    on = {"printServices": True, "oemSetup": False, "audioNames": True, "bootSplash": True}
    with patch("bootc_installer.core.system.Systeminfo.has_nvidia_gpu", return_value=False):
        from_images = Processor.gen_install_recipe("", [disk], {
            "imgref": "registry.example/os/atlas:stable", "images": CATALOG["images"]})
        from_recipe = Processor.gen_install_recipe("", [disk], {
            "imgref": "r/x:1", "extras": {"bootSplash": True, "notAStep": True}})
        none = Processor.gen_install_recipe("", [disk], {"imgref": "r/x:1"})
        wrong = Processor.gen_install_recipe("", [disk], {
            "imgref": "r/x:1", "extras": {"bootSplash": "yes"}})
    assert from_images["extras"] == on
    assert from_recipe["extras"] == {"printServices": False, "oemSetup": False,
                                     "audioNames": False, "bootSplash": True}
    assert "extras" not in none
    assert "extras" not in wrong


def test_wrong_types_in_a_catalog_do_not_reach_the_recipe():
    leaves = catalog.leaves({"images": [
        {"name": "Odd", "imgref": "r/odd:1", "needs_user_creation": "no", "composefs": 1,
         "filesystems": "xfs", "bootloader": 7, "flatpaks": ["ok", 3],
         "extras": ["bootSplash"]},
        "not a node",
        {"name": "No registry", "tag": "stable"},
    ]})
    assert len(leaves) == 1
    odd = leaves[0]
    assert odd["needs_user_creation"] is True
    assert odd["composefs"] is False
    assert odd["filesystems"] == []
    assert odd["bootloader"] == ""
    assert odd["flatpaks"] is None
    assert odd["extras"] is None
