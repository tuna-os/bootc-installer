"""The image catalog contract: shared/catalog/.

Five frontends read images.json in five languages. shared/catalog/README.md
says what each must read and what each must write into the recipe, and
fixtures/expected.json is that contract as data. These tests keep the data
honest:

1. expected.json is exactly what the reference resolver writes for
   fixtures/catalog.json, so the README, the resolver and the fixture
   cannot disagree.
2. The fixture exercises every rule the contract names. A fixture that lost
   its composefs leaf would let a frontend pass while still wrong.
3. fisherman's bundled catalog parses with the same resolver, and every
   recipe fragment it yields is valid against the recipe schema.
"""

import importlib.util
import json
import os
import tempfile
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
SHARED = os.path.join(REPO, "shared", "catalog")
BUNDLED = os.path.join(REPO, "fisherman", "data", "images.json")
SCHEMA = os.path.join(REPO, "shared", "recipe", "fisherman-recipe.schema.json")

_spec = importlib.util.spec_from_file_location(
    "shared_catalog_resolve", os.path.join(SHARED, "resolve.py"))
resolve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolve)


def _fixture():
    return resolve.load(resolve.FIXTURE_CATALOG)


def _leaf(imgref):
    leaf = resolve.find(_fixture(), imgref)
    assert leaf is not None, imgref
    return leaf


class ExpectedIsGenerated(unittest.TestCase):
    def test_expected_json_is_what_the_resolver_writes(self):
        with open(resolve.FIXTURE_EXPECTED, encoding="utf-8") as stream:
            committed = stream.read()
        self.assertEqual(
            committed, resolve.dumps(resolve.expected(_fixture())),
            "run: python3 shared/catalog/resolve.py --write")

    def test_expected_json_is_plain_json(self):
        with open(resolve.FIXTURE_EXPECTED, encoding="utf-8") as stream:
            data = json.load(stream)
        self.assertEqual(data["contract_version"], resolve.CONTRACT_VERSION)
        self.assertEqual([entry["imgref"] for entry in data["leaves"]],
                         [leaf["imgref"] for leaf in resolve.leaves(_fixture())])


class SearchPath(unittest.TestCase):
    def test_native_order(self):
        self.assertEqual(resolve.search_paths(False, "/home/u/.config", "/pkg/images.json"), [
            "/etc/bootc-installer/images.json",
            "/etc/tuna-installer/images.json",
            "/home/u/.config/bootc-installer/images.json",
            "/pkg/images.json",
        ])

    def test_flatpak_reads_the_host_etc(self):
        paths = resolve.search_paths(True, "/home/u/.var/app/x/config", "/app/share/images.json")
        self.assertEqual(paths[:2], [
            "/run/host/etc/bootc-installer/images.json",
            "/run/host/etc/tuna-installer/images.json",
        ])
        self.assertFalse(any(path.startswith("/etc/") for path in paths))

    def test_xdg_default_is_dot_config(self):
        paths = resolve.default_search_paths("/pkg/images.json", environ={}, home="/home/u")
        self.assertIn("/home/u/.config/bootc-installer/images.json", paths)

    def test_first_file_that_loads_wins_and_a_broken_one_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = os.path.join(tmp, "broken.json")
            not_a_catalog = os.path.join(tmp, "list.json")
            good = os.path.join(tmp, "good.json")
            later = os.path.join(tmp, "later.json")
            with open(broken, "w") as stream:
                stream.write("{ not json")
            with open(not_a_catalog, "w") as stream:
                stream.write("[]")
            for path, name in ((good, "good"), (later, "later")):
                with open(path, "w") as stream:
                    json.dump({"images": [{"name": name, "imgref": f"r.example/{name}:1"}]}, stream)
            catalog, path = resolve.load_first(
                [os.path.join(tmp, "missing.json"), broken, not_a_catalog, good, later])
            self.assertEqual(path, good)
            self.assertEqual(catalog["images"][0]["name"], "good")
            self.assertEqual(resolve.load_first([broken]), (None, None))


class FixtureCoversTheContract(unittest.TestCase):
    """Each rule in the README has a leaf that would catch a frontend that
    skips it."""

    def test_inheritance_and_registry_tag(self):
        leaf = _leaf("registry.example/os/atlas:stable")
        self.assertEqual((leaf["bootloader"], leaf["filesystem"], leaf["default_hostname"]),
                         ("grub2", "xfs", "atlas"))
        self.assertFalse(leaf["composefs"])
        self.assertEqual((leaf["product"], leaf["channel"], leaf["label"]),
                         ("Atlas", "Stable", "Atlas Stable"))
        self.assertEqual(leaf["breadcrumb"], "Atlas › Stable")

    def test_a_nested_registry_names_the_product(self):
        leaf = _leaf("registry.example/os/atlas-dx:latest")
        self.assertEqual(leaf["label"], "Atlas DX Latest")
        self.assertEqual(leaf["bootloader"], "grub2")

    def test_composefs_systemd_leaf_with_a_filesystem_list(self):
        leaf = _leaf("registry.example/os/boreal:latest")
        self.assertTrue(leaf["composefs"])
        self.assertEqual(leaf["bootloader"], "systemd")
        self.assertEqual(leaf["filesystems"], ["btrfs", "ext4"])
        self.assertEqual(leaf["filesystem"], "btrfs")
        self.assertEqual(leaf["label"], "Boreal")
        fragment = resolve.recipe_fragment(leaf)
        self.assertEqual(fragment["recipe"]["composeFsBackend"], True)
        self.assertEqual(fragment["recipe"]["filesystem"], "btrfs")
        self.assertEqual(fragment["recipe"]["flatpakVarPath"], "state/os/default/var")

    def test_a_child_overrides_an_inherited_value_with_false(self):
        edge = _leaf("registry.example/os/drift:edge")
        kiosk = _leaf("registry.example/os/drift:kiosk")
        self.assertTrue(edge["composefs"])
        self.assertFalse(kiosk["composefs"])
        self.assertEqual((edge["filesystem"], kiosk["filesystem"]), ("ext4", "xfs"))

    def test_needs_user_creation_defaults_to_true_and_inherits(self):
        want = {
            "registry.example/os/atlas:stable": True,    # unset anywhere
            "registry.example/os/atlas:beta": False,     # set on the leaf
            "registry.example/os/boreal:latest": False,
            "registry.example/os/drift:edge": False,     # inherited from the group
            "registry.example/os/drift:kiosk": True,     # leaf overrides the group
            "registry.example/os/cirrus:1": True,        # bare leaf
        }
        for imgref, value in want.items():
            self.assertIs(_leaf(imgref)["needs_user_creation"], value, imgref)
            self.assertIs(resolve.needs_user_creation(_fixture(), imgref), value, imgref)
        self.assertIs(resolve.needs_user_creation(_fixture(), "r.example/unknown:1"), True)
        self.assertIs(resolve.needs_user_creation(None, "r.example/unknown:1"), True)

    def test_flatpak_lists(self):
        def fragment(imgref):
            return resolve.recipe_fragment(_leaf(imgref))

        # An alias that names a list.
        self.assertEqual(fragment("registry.example/os/atlas:stable")["recipe"]["flatpaks"],
                         ["org.example.Browser", "org.example.Editor"])
        # An explicit empty list is "copy nothing", and it beats the parent.
        self.assertEqual(fragment("registry.example/os/atlas:beta")["recipe"]["flatpaks"], [])
        # A literal list.
        self.assertEqual(fragment("registry.example/os/boreal:latest")["recipe"]["flatpaks"],
                         ["org.example.Files"])
        # An alias that names a URL, an unknown alias and no value: no key.
        for imgref in ("registry.example/os/atlas-dx:latest",
                       "registry.example/os/drift:edge",
                       "registry.example/os/cirrus:1"):
            got = fragment(imgref)
            self.assertNotIn("flatpaks", got["recipe"], imgref)
            self.assertIn("flatpaks", got["absent"], imgref)
        self.assertEqual(_leaf("registry.example/os/atlas-dx:latest")["flatpaks_url"],
                         "https://flatpaks.example/system-flatpaks.Brewfile")

    def test_fallback_flatpaks_never_reach_a_recipe(self):
        fallback = set(_fixture()["fallback_flatpaks"])
        self.assertTrue(fallback)
        for entry in resolve.expected(_fixture())["leaves"]:
            for case in entry["cases"]:
                self.assertFalse(fallback & set(case["recipe"].get("flatpaks", [])),
                                 entry["imgref"])

    def test_nvidia_table(self):
        leaf = _leaf("registry.example/os/boreal:latest")
        base, nvidia = leaf["imgref"], leaf["nvidia_imgref"]
        self.assertTrue(nvidia)
        cases = [
            # has_nvidia, is_live, offline_images -> image, targetImgref
            (False, False, [], base, base),            # #314: no download of the big image
            (False, False, [nvidia], base, base),      # a store off live media is not trusted
            (True, False, [], nvidia, nvidia),
            (True, True, [nvidia], nvidia, nvidia),
            (False, True, [nvidia], nvidia, base),     # only the NVIDIA image is on the media
            (False, True, [base, nvidia], base, base),
            (False, True, [base], base, base),
        ]
        for has_nvidia, is_live, offline, image, target in cases:
            self.assertEqual(
                resolve.source_and_target(leaf, has_nvidia, is_live, offline),
                (image, target), (has_nvidia, is_live, offline))
        plain = _leaf("registry.example/os/cirrus:1")
        self.assertEqual(resolve.source_and_target(plain, True, True, []),
                         (plain["imgref"], plain["imgref"]))

    def test_target_imgref_is_always_written(self):
        for entry in resolve.expected(_fixture())["leaves"]:
            for case in entry["cases"]:
                self.assertTrue(case["recipe"]["targetImgref"], entry["imgref"])
                self.assertTrue(case["recipe"]["image"], entry["imgref"])

    def test_default_selection(self):
        catalog = _fixture()
        default = catalog["default_image"]
        other = "registry.example/os/atlas:beta"
        self.assertEqual(resolve.default_imgref(catalog), default)
        self.assertEqual(resolve.default_imgref(catalog, other), other)
        self.assertEqual(resolve.default_imgref(catalog, "r.example/unknown:1"), default)
        del catalog["default_image"]
        self.assertIsNone(resolve.default_imgref(catalog))
        self.assertIsNone(resolve.default_imgref(catalog, "r.example/unknown:1"))
        catalog["default_image"] = "r.example/unknown:2"
        self.assertIsNone(resolve.default_imgref(catalog))

    def test_bare_leaf_has_every_default(self):
        leaf = _leaf("registry.example/os/cirrus:1")
        self.assertEqual(
            {key: leaf[key] for key in ("nvidia_imgref", "bootloader", "composefs", "filesystem",
                                        "filesystems", "default_hostname", "flatpaks",
                                        "flatpak_var_path", "needs_user_creation", "image_type")},
            {"nvidia_imgref": "", "bootloader": "", "composefs": False, "filesystem": "",
             "filesystems": [], "default_hostname": "", "flatpaks": None,
             "flatpak_var_path": "", "needs_user_creation": True, "image_type": "bootc"})
        fragment = resolve.recipe_fragment(leaf)
        self.assertNotIn("filesystem", fragment["recipe"])
        self.assertEqual(sorted(fragment["absent"]), ["flatpakVarPath", "flatpaks"])


class RecipeMatches(unittest.TestCase):
    """The comparison rule the README gives the per-frontend tests."""

    def test_missing_key_equals_its_empty_value(self):
        fragment = resolve.recipe_fragment(_leaf("registry.example/os/cirrus:1"))
        recipe = {"image": "registry.example/os/cirrus:1",
                  "targetImgref": "registry.example/os/cirrus:1"}
        self.assertEqual(resolve.recipe_matches(recipe, fragment), [])

    def test_dropped_boot_stack_is_reported(self):
        fragment = resolve.recipe_fragment(_leaf("registry.example/os/boreal:latest"))
        recipe = dict(fragment["recipe"])
        self.assertEqual(resolve.recipe_matches(recipe, fragment), [])
        del recipe["composeFsBackend"], recipe["bootloader"]
        recipe["filesystem"] = "xfs"
        problems = resolve.recipe_matches(recipe, fragment)
        self.assertEqual(len(problems), 3, problems)

    def test_a_substituted_flatpak_list_is_reported(self):
        fragment = resolve.recipe_fragment(_leaf("registry.example/os/atlas-dx:latest"))
        recipe = dict(fragment["recipe"], flatpaks=["org.example.NeverSent"])
        self.assertTrue(any(p.startswith("flatpaks") for p in resolve.recipe_matches(recipe, fragment)))


class MalformedCatalog(unittest.TestCase):
    def test_bad_values_are_refused(self):
        for node in ({"name": "x", "imgref": "r/x:1", "bootloader": "lilo"},
                     {"name": "x", "imgref": "r/x:1", "filesystem": "ntfs"},
                     {"name": "x", "imgref": "r/x:1", "composefs": "yes"},
                     {"name": "x", "imgref": "r/x:1", "needs_user_creation": 0},
                     {"name": "x", "imgref": "r/x:1", "flatpaks": [1]},
                     "not a node"):
            with self.assertRaises(resolve.CatalogError, msg=node):
                resolve.leaves({"images": [node]})

    def test_tag_without_registry_is_not_a_leaf(self):
        self.assertEqual(resolve.leaves({"images": [{"name": "x", "tag": "1"}]}), [])


@unittest.skipUnless(os.path.exists(BUNDLED), "fisherman submodule not checked out")
class BundledCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = resolve.load(BUNDLED)
        cls.leaves = resolve.leaves(cls.catalog)

    def test_it_parses_and_every_leaf_is_unique(self):
        self.assertGreater(len(self.leaves), 100)
        refs = [leaf["imgref"] for leaf in self.leaves]
        self.assertEqual(len(refs), len(set(refs)))

    def test_leaf_count_matches_a_plain_walk(self):
        def count(nodes, registry=""):
            total = 0
            for node in nodes:
                scope = node.get("registry", registry)
                if node.get("imgref") or ("tag" in node and scope):
                    total += 1
                else:
                    total += count(node.get("children", []), scope)
            return total

        self.assertEqual(len(self.leaves), count(self.catalog["images"]))

    def test_breadcrumbs_are_unique_where_labels_are_not(self):
        crumbs = [leaf["breadcrumb"] for leaf in self.leaves]
        self.assertEqual(len(crumbs), len(set(crumbs)))
        for leaf in self.leaves:
            self.assertTrue(leaf["product"], leaf["imgref"])

    def test_no_composefs_leaf_defaults_to_a_filesystem_without_fs_verity(self):
        # fisherman refuses composefs on xfs (composefs_requires_fs_verity).
        for leaf in self.leaves:
            if leaf["composefs"]:
                self.assertIn(leaf["filesystem"], ("btrfs", "ext4"), leaf["imgref"])

    def test_every_fragment_is_valid_against_the_recipe_schema(self):
        with open(SCHEMA, encoding="utf-8") as stream:
            properties = json.load(stream)["properties"]
        for leaf in self.leaves:
            fragment = resolve.recipe_fragment(leaf, has_nvidia=True)
            for key, value in fragment["recipe"].items():
                self.assertIn(key, properties, f"{leaf['imgref']}: {key} is not a recipe key")
                enum = properties[key].get("enum")
                if enum:
                    self.assertIn(value, enum, f"{leaf['imgref']}: {key}")
            for key in fragment["absent"]:
                self.assertIn(key, properties)

    def test_remote_lists_are_never_fetched_or_replaced(self):
        remote = [leaf for leaf in self.leaves if leaf["flatpaks_url"]]
        self.assertTrue(remote, "the bundled catalog no longer has a remote list")
        for leaf in remote:
            self.assertIsNone(leaf["flatpaks"])
            self.assertIn("flatpaks", resolve.recipe_fragment(leaf)["absent"])


class ResolverIsStandalone(unittest.TestCase):
    """No GTK, no frontend and no network in the reference resolver."""

    def test_resolver_has_no_frontend_import(self):
        with open(os.path.join(SHARED, "resolve.py"), encoding="utf-8") as stream:
            source = stream.read()
        for banned in ("import gi", "from gi", "bootc_installer", "urllib", "requests", "socket"):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
