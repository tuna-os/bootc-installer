"""The cross-frontend recipe contract (#226, #186).

shared/recipe/fixtures/compliance.json holds one set of choices per case and
the one recipe that every frontend must write for it. Each frontend drives
the choices through its own recipe builder, in its own test framework:

    GNOME   this file, TestGnome: image_finals, disk_plan, the Processor
    XFCE    frontends/xfce/tests/test_recipe_compliance.py: core.recipe_for_leaf
    KDE     frontends/kde/tests/test_backend.cpp, recipeCompliance: InstallerController
    COSMIC  frontends/cosmic/src/recipe_compliance.rs: Recipe::apply_leaf and the page setters
    Niri    frontends/niri/installer/compliance_test.go: ui/recipe.js, then the Go backend

Each test normalises its recipe with the fixture's `normalise` table and
compares the bytes with the expected recipe. shared/recipe/compliance.py is
the reference normaliser. The rest of this file holds the fixture itself to
the other contracts, and sends each expected recipe to
`fisherman validate --json --partial -` when a fisherman binary is there.
The `Recipe compliance` workflow runs all five and fails when one differs.
"""

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "shared", "python"))

_spec = importlib.util.spec_from_file_location(
    "recipe_compliance", os.path.join(REPO, "shared", "recipe", "compliance.py"))
compliance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compliance)

FIXTURE = compliance.load()
CASES = FIXTURE["cases"]
IDS = [case["name"] for case in CASES]


def _json(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as stream:
        return json.load(stream)


CATALOG = _json(FIXTURE["catalog"])
CATALOG_EXPECTED = _json("shared", "catalog", "fixtures", "expected.json")
SCHEMA = _json("shared", "recipe", "fisherman-recipe.schema.json")


# --- the fixture itself -------------------------------------------------------

def test_the_fixture_has_cases_for_each_choice():
    """Together the cases set each choice the contract names: image, disk,
    filesystem, LUKS, account, language, keyboard, time zone, hostname,
    and a leaf with a choice of filesystems and no account."""
    assert FIXTURE["contract_version"] == 1
    assert len(CASES) >= 2
    choices = [case["choices"] for case in CASES]
    assert any(c["encryption"]["type"] == "luks-passphrase" for c in choices)
    assert any(c["account"] for c in choices)
    assert any(c["account"] is None for c in choices)
    assert any(c["locale"] and c["keyboard"] and c["timezone"] for c in choices)
    assert all(c["disk"] and c["hostname"] and c["image"] and c["filesystem"] for c in choices)
    assert len({case["name"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_expected_recipe_is_in_normal_form(case):
    """The expected recipe has no key that the table removes, so each
    frontend compares with it as it is."""
    assert compliance.normalise(case["recipe"]) == case["recipe"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_expected_recipe_has_only_schema_keys(case):
    properties = SCHEMA["properties"]
    for key, value in case["recipe"].items():
        assert key in properties, key
        if isinstance(value, dict) and "properties" in properties[key]:
            for inner in value:
                assert inner in properties[key]["properties"], f"{key}.{inner}"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_image_keys_are_the_catalog_contracts(case):
    """The keys that come from the leaf are what shared/catalog/fixtures
    expects for that leaf on that machine: the two fixtures cannot drift."""
    choices = case["choices"]
    row = next(row for row in CATALOG_EXPECTED["leaves"] if row["imgref"] == choices["image"])
    match = [c for c in row["cases"] if c["inputs"] == choices["machine"]]
    assert match, "no catalog case for this machine"
    want = compliance.normalise({k: v for k, v in match[0]["recipe"].items()
                                 if k != "filesystem"})
    for key, value in want.items():
        assert case["recipe"].get(key) == value, key
    for key in match[0]["absent"]:
        assert key not in case["recipe"], key
    leaf = row["leaf"]
    assert choices["filesystem"] in (leaf["filesystems"] or [leaf["filesystem"]])
    assert ("user" in case["recipe"]) is leaf["needs_user_creation"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_choices_reach_the_recipe(case):
    choices, recipe = case["choices"], case["recipe"]
    assert recipe["disk"] == choices["disk"]
    assert recipe["filesystem"] == choices["filesystem"]
    assert recipe["hostname"] == choices["hostname"]
    assert recipe["distroID"] == FIXTURE["branding"]["id"]
    assert recipe["encryption"]["type"] == choices["encryption"]["type"]
    assert recipe["encryption"].get("passphrase", "") == choices["encryption"]["passphrase"]
    for key in ("locale", "timezone"):
        assert recipe.get(key, "") == choices[key]
    assert recipe.get("keyboard") == choices["keyboard"]
    if choices["account"]:
        groups = _json("shared", "account", "groups.json")["default_groups"]
        assert recipe["user"] == dict(choices["account"], groups=groups)


def test_the_normaliser_rules():
    table = FIXTURE["normalise"]
    recipe = {"disk": "/dev/vda", "composeFsBackend": False, "imageType": "bootc",
              "bootloader": "", "selinuxDisabled": False, "btrfsSubvolumes": False,
              "encryption": {"type": "none", "passphrase": ""},
              "user": {"username": "", "fullname": "", "password": "", "groups": []}}
    assert compliance.normalise(recipe, table) == {"disk": "/dev/vda", "encryption": {"type": "none"}}
    # A value that is not the default stays, and so does a value of another
    # type (0 is not false).
    kept = {"composeFsBackend": True, "btrfsSubvolumes": 0, "bootloader": "grub2",
            "user": {"username": "jo"}}
    assert compliance.normalise(kept, table) == kept
    assert compliance.canonical({"b": 1, "a": "é"}, table) == '{"a":"é","b":1}'.encode()
    # The input is not changed.
    before = copy.deepcopy(recipe)
    compliance.normalise(recipe, table)
    assert recipe == before


def _fisherman():
    explicit = os.environ.get("FISHERMAN_BIN", "")
    if explicit:
        return explicit
    return shutil.which("fisherman")


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_fisherman_accepts_the_expected_recipe(case):
    """`fisherman validate --json --partial -`: the rules that need no
    machine. The full check reads the disk and the firmware, so it is the
    E2E job's (shared/e2e/). The workflow sets FISHERMAN_BIN and
    RECIPE_COMPLIANCE_REQUIRE_FISHERMAN, so there this test cannot skip."""
    binary = _fisherman()
    if not binary:
        if os.environ.get("RECIPE_COMPLIANCE_REQUIRE_FISHERMAN"):
            pytest.fail("no fisherman binary, and the workflow requires one")
        pytest.skip("no fisherman binary (set FISHERMAN_BIN)")
    run = subprocess.run([binary, "validate", "--json", "--partial", "-"],
                         input=json.dumps(case["recipe"]), capture_output=True, text=True,
                         timeout=60, check=False)
    answer = json.loads(run.stdout)
    assert answer["valid"] is True, answer["errors"]


# --- GNOME --------------------------------------------------------------------

class _Disk:
    pretty_size = "64 GB"
    size = 64 * 1024 ** 3

    def __init__(self, path):
        self.disk = path


def gnome_recipe(case, tmp_path):
    """The recipe GNOME writes for the case's choices: the finals of each
    page, in the shape its get_finals() returns, through the Processor."""
    from bootc_installer.defaults.disk_plan import (
        build_auto_partition_recipe, build_disk_finals, filesystem_options)
    from bootc_installer.utils import image_finals
    from bootc_installer.utils.processor import Processor
    from bootc_shared import account, catalog

    choices = case["choices"]
    leaf = catalog.find(CATALOG, choices["image"])
    image = image_finals.leaf_finals(leaf)
    options, _ = filesystem_options(image)
    assert choices["filesystem"] in options
    disk = build_disk_finals(build_auto_partition_recipe(_Disk(choices["disk"])),
                             choices["filesystem"], choices["hostname"])
    enc = choices["encryption"]
    if enc["type"] == "none":
        encryption = {"encryption": {"use_encryption": False, "encryption_key": ""}}
    else:
        encryption = {"encryption": {"use_encryption": True, "type": enc["type"],
                                     "encryption_key": enc["passphrase"]}}
    finals = [image, disk, encryption]
    if image["needs_user_creation"]:
        user = choices["account"] or {"username": "", "fullname": "", "password": ""}
        finals.append({"user": dict(user, groups=list(account.DEFAULT_GROUPS))})
    if choices["locale"]:
        finals.append({"language": choices["locale"]})
    if choices["keyboard"]:
        finals.append({"keyboard": dict(choices["keyboard"])})
    if choices["timezone"]:
        finals.append({"timezone": choices["timezone"]})

    branding = tmp_path / "branding.json"
    branding.write_text(json.dumps(FIXTURE["branding"]), encoding="utf-8")
    manifest = type(sys)("bootc_installer.defaults.image")
    manifest._MANIFEST = CATALOG
    machine = choices["machine"]
    with patch.dict(sys.modules, {"bootc_installer.defaults.image": manifest}), \
            patch.dict(os.environ, {"BOOTC_INSTALLER_BRANDING": str(branding)}), \
            patch("bootc_installer.core.system.Systeminfo.has_nvidia_gpu",
                  return_value=machine["has_nvidia"]), \
            patch("bootc_installer.core.system.Systeminfo.is_live",
                  return_value=machine["is_live"]), \
            patch("bootc_installer.core.system.Systeminfo.offline_images",
                  return_value=list(machine["offline_images"])):
        return Processor.gen_install_recipe("", finals, {})


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_gnome_writes_the_expected_recipe(case, tmp_path):
    got = compliance.canonical(gnome_recipe(case, tmp_path))
    want = compliance.canonical(case["recipe"])
    assert got.decode() == want.decode()
