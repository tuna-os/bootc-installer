"""GNOME writes the contract's recipe for each leaf of the catalog fixture.

shared/catalog/README.md is the contract, shared/catalog/fixtures/catalog.json
a catalog that uses each rule, and fixtures/expected.json the answers.

The reader is bootc_shared.catalog, which XFCE also uses;
tests/unit/test_shared_python_catalog.py holds it to the fixture (the search
path, the leaves, the default selection, the account flag). This file is
the GNOME half: what GNOME's own code does with a leaf.

    image_finals.leaf_finals   what the image page hands on for a leaf
    disk_plan                  what the disk page selects before the user picks
    Processor                  the recipe
    user_step                  the account, when there is no image page

and that the page, the Processor and the user step read the shared reader
and no copy of it.
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
from bootc_shared import catalog  # noqa: E402
from bootc_installer.utils import image_finals  # noqa: E402
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
    image_finals_ = image_finals.leaf_finals(leaf)
    options, selected = filesystem_options(image_finals_)
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
        return Processor.gen_install_recipe("", [image_finals_, disk_finals], {})


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


def test_an_image_the_catalog_does_not_have_needs_an_account():
    unknown = EXPECTED["unknown_image"]
    assert catalog.needs_user_creation(CATALOG, unknown["imgref"]) is unknown["needs_user_creation"]
    assert catalog.needs_user_creation(None, unknown["imgref"]) is True
    assert image_finals.custom_image_finals(unknown["imgref"])["needs_user_creation"] is True


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
    finals = image_finals.leaf_finals(leaf)
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


def test_gnome_reads_the_shared_reader_and_has_no_copy():
    import bootc_shared.catalog as shared
    from bootc_installer.utils import processor
    assert catalog is shared
    assert processor.catalog is shared
    assert user_step.catalog is shared
    assert image_finals.catalog is shared
    assert not os.path.exists(os.path.join(REPO, "bootc_installer", "utils", "catalog.py"))
    source = open(os.path.join(REPO, "bootc_installer", "defaults", "image.py"),
                  encoding="utf-8").read()
    assert "from bootc_shared import catalog" in source
    # One walk of the tree: the Processor has no second one.
    text = open(processor.__file__, encoding="utf-8").read()
    assert '"children"' not in text.replace('("imgref", "tag", "registry", "children")', "")
    assert "catalog.find(" in text


def test_the_processor_finds_metadata_through_the_shared_reader():
    """Processor.find_metadata is catalog.find plus one special case."""
    nested = [{"registry": "r.example/os/atlas", "composefs": True, "bootloader": "systemd",
               "filesystems": ["ext4"], "flatpaks": "@desktop",
               "children": [{"name": "Stable", "tag": "stable"}]}]
    found = Processor.find_metadata(nested, {"desktop": ["org.example.A"]},
                                    "r.example/os/atlas:stable")
    assert found == {"composefs": True, "image_type": "bootc", "bootloader": "systemd",
                     "filesystem": "ext4", "flatpak_var_path": "",
                     "flatpaks": ["org.example.A"], "extras": None}
    # A choice of filesystems is the user's: the image forces none.
    nested[0]["filesystems"] = ["ext4", "btrfs"]
    assert Processor.find_metadata(nested, {}, "r.example/os/atlas:stable")["filesystem"] == ""
    # No leaf for the image: nothing, never the first row.
    assert Processor.find_metadata(nested, {}, "r.example/other:1") == {}
    # A single entry that names no image is the metadata of the one image.
    only = [{"composefs": True, "filesystem": "ext4"}]
    assert Processor.find_metadata(only, {}, "r.example/other:1") is only[0]
    # A wrong type in the leaf of this image stops the install.
    with pytest.raises(ValueError):
        Processor.find_metadata([{"imgref": "r/a:1", "composefs": "yes"}], {}, "r/a:1")
    for broken in ([None], [{"children": None}], None):
        with pytest.raises(ValueError):
            Processor.find_metadata(broken, {}, "r/a:1")


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


def test_zfs_carries_the_experimental_opt_in():
    """fisherman refuses filesystem zfs without "experimental": ["zfs"]
    (zfs_experimental). Only zfs gets the key."""
    for fs, want in (("zfs", ["zfs"]), ("xfs", None), ("btrfs", None)):
        disk = build_disk_finals(build_auto_partition_recipe(_Disk()), fs, "host")
        with patch("bootc_installer.core.system.Systeminfo.has_nvidia_gpu", return_value=False):
            recipe = Processor.gen_install_recipe("", [disk], {"imgref": "r/x:1"})
        assert recipe["filesystem"] == fs
        assert recipe.get("experimental") == want


def test_the_override_follows_the_fixture():
    """FISHERMAN_IMAGES_PATH (shared/catalog/README.md): the search path
    that GNOME's image page reads, for each case of expected.json. The
    bundled catalog follows the list."""
    override = EXPECTED["override"]
    assert override["env"] == catalog.OVERRIDE_ENV == "FISHERMAN_IMAGES_PATH"
    for case in override["cases"]:
        environ = {override["env"]: case["value"], "XDG_CONFIG_HOME": case["xdg_config_home"]}
        assert catalog.default_search_paths(environ, "/home/user", flatpak=case["in_flatpak"]) \
            == case["paths"][:-1], case
        assert case["paths"][-1] == "<bundled>"
