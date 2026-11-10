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


class ExtrasFollowTheCatalog(unittest.TestCase):
    def test_every_fixture_leaf(self):
        with open(EXPECTED, encoding="utf-8") as stream:
            expected = json.load(stream)
        seen = set()
        for entry in expected["leaves"]:
            recipe = dict(entry["cases"][0]["recipe"])
            self.assertEqual(check.extras_failures(recipe, _catalog()), [], entry["imgref"])
            has = entry["leaf"]["extras"] is not None
            seen.add(has)
            if has:
                dropped = {key: value for key, value in recipe.items() if key != "extras"}
                self.assertEqual(len(check.extras_failures(dropped, _catalog())), 1)
                flipped = dict(recipe, extras=dict(recipe["extras"],
                                                  oemSetup=not recipe["extras"]["oemSetup"]))
                self.assertEqual(len(check.extras_failures(flipped, _catalog())), 1)
            else:
                invented = dict(recipe, extras={})
                self.assertEqual(len(check.extras_failures(invented, _catalog())), 1)
        self.assertEqual(seen, {True, False}, "the fixture must hold both answers")

    def test_a_switch_that_is_left_out_is_off(self):
        recipe = {"image": "registry.example/os/atlas:beta", "extras": {"oemSetup": True}}
        self.assertEqual(check.extras_failures(recipe, _catalog()), [])

    def test_no_catalog_and_an_unknown_image_are_not_judged(self):
        self.assertEqual(check.extras_failures({"image": "r/x:1", "extras": {}}, None), [])
        self.assertEqual(check.extras_failures({"image": "r/x:1", "extras": {}}, _catalog()), [])


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


E2E_CATALOG = os.path.join(REPO, "shared", "e2e", "catalog.json")
# The file of each E2E driver, and how it names the shared catalog.
DRIVERS = {
    "gnome": ("tests/e2e/run_gnome.py", '"shared" / "e2e" / "catalog.json"'),
    "xfce": ("frontends/xfce/tests/e2e/run.py", '"shared", "e2e", "catalog.json"'),
    "niri": ("frontends/niri/tests/e2e/run.py", '"shared", "e2e", "catalog.json"'),
    "kde": ("frontends/kde/CMakeLists.txt", "${TUNA_SHARED_DIR}/e2e/catalog.json"),
    "cosmic": ("frontends/cosmic/src/main.rs", '"/../../shared/e2e/catalog.json"'),
}


def _e2e_catalog():
    with open(E2E_CATALOG, encoding="utf-8") as stream:
        return json.load(stream)


def _read(path):
    with open(os.path.join(REPO, path), encoding="utf-8") as stream:
        return stream.read()


class OneCatalogForTheFiveDrivers(unittest.TestCase):
    """shared/e2e/catalog.json is the one catalog of the E2E drivers
    (shared/e2e/README.md, "The catalog")."""

    def test_every_driver_reads_the_shared_catalog(self):
        for frontend, (path, reference) in DRIVERS.items():
            self.assertIn(reference, _read(path), frontend)
        self.assertIn("E2E_CATALOG_FILE", _read("frontends/kde/tests/e2e.cpp"))
        self.assertFalse(os.path.exists(os.path.join(REPO, "frontends", "niri", "tests",
                                                     "e2e", "images.json")))

    def test_the_catalog_has_a_leaf_with_and_one_without_an_account(self):
        resolver = check._catalog_resolver()
        leaves = {leaf["imgref"]: leaf for leaf in resolver.leaves(_e2e_catalog())}
        self.assertEqual({leaf["needs_user_creation"] for leaf in leaves.values()}, {True, False})
        default = _e2e_catalog()["default_image"]
        self.assertIs(leaves[default]["needs_user_creation"], True)
        # The fallback list is there to show that no frontend sends it.
        self.assertTrue(_e2e_catalog()["fallback_flatpaks"])
        for leaf in leaves.values():
            self.assertNotEqual(leaf["flatpaks"], _e2e_catalog()["fallback_flatpaks"])

    def test_the_vm_matrix_installs_an_account_and_no_account(self):
        """GNOME, XFCE, KDE and Niri install the default_image leaf (an
        account); COSMIC installs the leaf with no account."""
        resolver = check._catalog_resolver()
        catalog = _e2e_catalog()
        cosmic = _read("frontends/cosmic/src/main.rs")
        marker = 'const E2E_IMAGE: &str = "'
        cosmic_image = cosmic[cosmic.index(marker) + len(marker):].split('"', 1)[0]
        picked = {"gnome": catalog["default_image"], "xfce": catalog["default_image"],
                  "kde": "quay.io/centos-bootc/centos-bootc:c10s",
                  "niri": catalog["default_image"], "cosmic": cosmic_image}
        self.assertIn(picked["kde"], _read("frontends/kde/tests/e2e.cpp"))
        accounts = {frontend: resolver.find(catalog, imgref)["needs_user_creation"]
                    for frontend, imgref in picked.items()}
        self.assertEqual(accounts, {"gnome": True, "xfce": True, "kde": True,
                                    "niri": True, "cosmic": False})

    def test_an_exported_catalog_must_be_the_shared_one(self):
        self.assertEqual(check.shared_catalog_failures(_e2e_catalog()), [])
        self.assertEqual(check.shared_catalog_failures(None), [])
        own = {"images": [{"name": "Own", "imgref": "r/own:1"}]}
        self.assertEqual(len(check.shared_catalog_failures(own)), 1)
        # A catalog the job passes with --catalog is the job's choice.
        self.assertEqual(check.shared_catalog_failures(own, "/tmp/own.json"), [])
