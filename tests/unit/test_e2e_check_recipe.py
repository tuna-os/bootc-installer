"""shared/e2e/check-recipe.py judges the account by the catalog contract.

The script used to hold a set of frontends "whose wizard has a required
account step". That is not the contract: the account is required exactly
when the image needs one (shared/catalog/README.md, #288). These tests pin
the verdict against the shared fixture catalog, and pin that the VM job no
longer repairs a composefs-on-xfs recipe behind the frontend's back (#287).
"""

import importlib.util
import json
import os
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(REPO, "shared", "e2e", "check-recipe.py")
VM_INSTALL = os.path.join(REPO, "shared", "e2e", "vm-install.sh")
CATALOG = os.path.join(REPO, "shared", "catalog", "fixtures", "catalog.json")
EXPECTED = os.path.join(REPO, "shared", "catalog", "fixtures", "expected.json")

_spec = importlib.util.spec_from_file_location("e2e_check_recipe", SCRIPT)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

USER = {"username": "tester", "fullname": "T", "password": "x", "groups": ["wheel"]}


def _catalog():
    with open(CATALOG, encoding="utf-8") as stream:
        return json.load(stream)


class AccountFollowsTheCatalog(unittest.TestCase):
    def test_every_fixture_leaf(self):
        with open(EXPECTED, encoding="utf-8") as stream:
            expected = json.load(stream)
        seen = set()
        for entry in expected["leaves"]:
            needs = entry["leaf"]["needs_user_creation"]
            seen.add(needs)
            for case in entry["cases"]:
                recipe = dict(case["recipe"])
                for frontend in ("gnome", "kde", "cosmic", "niri", "xfce"):
                    self.assertIs(check.account_required(frontend, recipe, _catalog()), needs,
                                  (frontend, entry["imgref"], case["inputs"]))
                    with_user = check.account_failures(frontend, dict(recipe, user=USER), _catalog())
                    without = check.account_failures(frontend, recipe, _catalog())
                    if needs:
                        self.assertEqual(with_user, [])
                        self.assertEqual(len(without), 1)
                    else:
                        self.assertEqual(without, [])
                        self.assertEqual(len(with_user), 1)
        self.assertEqual(seen, {True, False}, "the fixture must hold both answers")

    def test_nvidia_source_is_judged_as_its_base_leaf(self):
        # Boreal needs no account; its NVIDIA image is the same leaf.
        recipe = {"image": "registry.example/os/boreal-nvidia:latest",
                  "targetImgref": "registry.example/os/boreal-nvidia:latest"}
        self.assertIs(check.account_required("kde", recipe, _catalog()), False)

    def test_unknown_image_needs_an_account(self):
        recipe = {"image": "registry.example/os/other:1"}
        self.assertIs(check.account_required("gnome", recipe, _catalog()), True)
        self.assertEqual(len(check.account_failures("gnome", recipe, _catalog())), 1)

    def test_empty_username_is_no_account(self):
        recipe = {"image": "registry.example/os/atlas:beta",
                  "user": {"username": "", "groups": []}}
        self.assertEqual(check.account_failures("xfce", recipe, _catalog()), [])

    def test_account_outside_wheel_fails(self):
        recipe = {"image": "registry.example/os/atlas:stable",
                  "user": dict(USER, groups=["docker"])}
        failures = check.account_failures("niri", recipe, _catalog())
        self.assertEqual(len(failures), 1)
        self.assertIn("wheel", failures[0])


class WithoutACatalog(unittest.TestCase):
    """The interim rule, until every driver exports its catalog."""

    def test_legacy_frontends_still_must_create_a_user(self):
        for frontend in sorted(check.LEGACY_USER_STEP):
            self.assertIs(check.account_required(frontend, {}, None), True)
            self.assertEqual(len(check.account_failures(frontend, {}, None)), 1)
            self.assertEqual(check.account_failures(frontend, {"user": USER}, None), [])

    def test_the_rest_are_not_judged_rather_than_assumed(self):
        for frontend in ("cosmic", "gnome", "kde", "niri", "xfce"):
            self.assertIsNone(check.account_required(frontend, {}, None))
            self.assertEqual(check.account_failures(frontend, {}, None), [])

    def test_no_exported_catalog_reads_as_none(self):
        self.assertFalse(os.path.exists("/nonexistent-e2e/catalog.json"))
        saved = check.E2E_DIR
        check.E2E_DIR = "/nonexistent-e2e"
        try:
            self.assertIsNone(check.load_catalog())
        finally:
            check.E2E_DIR = saved
        self.assertEqual(check.load_catalog(CATALOG)["default_image"],
                         "registry.example/os/atlas:stable")


class VmInstallDoesNotRepairTheRecipe(unittest.TestCase):
    def test_no_filesystem_rewrite(self):
        with open(VM_INSTALL, encoding="utf-8") as stream:
            code = [line for line in stream.read().splitlines()
                    if not line.lstrip().startswith("#")]
        self.assertFalse([line for line in code if 'r["filesystem"]' in line],
                         "vm-install.sh must install the frontend's own filesystem (#287)")


if __name__ == "__main__":
    unittest.main()
