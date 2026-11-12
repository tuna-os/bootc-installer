"""The source check (#266), the live host's bootc storage (#267) and the
boot verification result (#269): the shared case files and the readers.

shared/probe/capabilities-cases.json, shared/probe/bootc-store-cases.json
and shared/completion/verification-cases.json are generated from the
canonical Python readers (bootc_shared.source_check and
bootc_shared.completion). The KDE, COSMIC and Niri tests read the same
files with their own readers. These tests keep the files honest:

1. Each file is what the generator writes today, so a change to a reader
   cannot leave the other three languages on an old answer.
2. Each fixture that came from fisherman is equal to fisherman's golden
   file, when the submodule pin has that file.
3. The rules that the issues set hold for the fixtures: no unavailable or
   unsupported answer, and no stale reply, is shown as ready; no item of
   the live host's storage is offered as an install source; no result is
   verified without matching evidence.
4. No frontend runs bootc itself: the facts come from fisherman.
"""

import glob
import importlib.util
import json
import os
import re
import unittest
from typing import ClassVar

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
SHARED = os.path.join(REPO, "shared")
PROBE = os.path.join(SHARED, "probe")
COMPLETION = os.path.join(SHARED, "completion")
GENERATOR = os.path.join(PROBE, "generate-source-check-cases.py")
FISHERMAN = os.path.join(REPO, "fisherman", "fisherman", "internal")


def _generator():
    spec = importlib.util.spec_from_file_location("gen_source_check", GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cases(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["cases"]


CAPS = os.path.join(PROBE, "capabilities-cases.json")
STORE = os.path.join(PROBE, "bootc-store-cases.json")
VERIFY = os.path.join(COMPLETION, "verification-cases.json")
REUSE = os.path.join(PROBE, "source-reuse-cases.json")


class GeneratedFilesTest(unittest.TestCase):
    def test_case_files_are_current(self):
        for path, text in _generator().render().items():
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(
                    fh.read(), text,
                    f"{os.path.relpath(path, REPO)} is stale: run "
                    "python3 shared/probe/generate-source-check-cases.py")


class FishermanFixturesTest(unittest.TestCase):
    """The copies of fisherman's golden files are equal to fisherman's,
    for each file that the submodule pin has. A copy whose golden file the
    pin does not have yet comes from an open fisherman pull request; the
    pin bump makes this test cover it."""

    PAIRS: ClassVar[list] = [
        (os.path.join(PROBE, "fixtures", "capabilities"), "caps-",
         os.path.join(FISHERMAN, "probe", "testdata", "golden")),
        (os.path.join(PROBE, "fixtures", "bootc-store"), "store-",
         os.path.join(FISHERMAN, "probe", "testdata", "golden")),
        (os.path.join(COMPLETION, "fixtures"), "",
         os.path.join(FISHERMAN, "receipt", "testdata", "results")),
    ]

    def test_copies_match_fisherman(self):
        for local, prefix, golden in self.PAIRS:
            for path in sorted(glob.glob(os.path.join(local, prefix + "*.json"))):
                name = os.path.basename(path)
                if name.startswith("frontend-"):
                    continue
                theirs = os.path.join(golden, name)
                if not os.path.exists(theirs):
                    continue
                with open(path, encoding="utf-8") as a, open(theirs, encoding="utf-8") as b:
                    self.assertEqual(json.load(a), json.load(b), name)

    def test_frontend_fixtures_are_marked(self):
        """A fixture that this repository made has the frontend- prefix, so
        nobody mistakes it for fisherman's output."""
        for local, prefix, _ in self.PAIRS:
            for name in os.listdir(local):
                self.assertTrue(name.startswith(("frontend-", prefix or "")), name)


class SourceCheckRulesTest(unittest.TestCase):
    def setUp(self):
        self.cases = {c["name"]: c for c in _cases(CAPS)}

    def test_every_state_is_covered(self):
        states = {c["expected"]["state"] for c in self.cases.values()}
        self.assertEqual(states, {"ready", "blocked", "unsupported", "unavailable", "stale"})

    def test_only_an_established_root_is_ready(self):
        fixtures = os.path.join(PROBE, "fixtures", "capabilities")
        for case in self.cases.values():
            if case["expected"]["state"] != "ready":
                continue
            with open(os.path.join(fixtures, case["fixture"]), encoding="utf-8") as fh:
                caps = json.load(fh)
            self.assertIs(caps["execution_root"]["established"], True, case["name"])

    def test_defaults_only_when_ready(self):
        for case in self.cases.values():
            if case["expected"]["state"] != "ready":
                self.assertEqual(case["expected"]["defaults"], [], case["name"])

    def test_only_blocked_holds_install(self):
        for case in self.cases.values():
            self.assertEqual(case["blocks_install"],
                             case["expected"]["state"] == "blocked", case["name"])

    def test_old_and_new_backends(self):
        self.assertEqual(self.cases["old-backend"]["expected"]["state"], "unsupported")
        self.assertEqual(self.cases["version-2"]["expected"]["state"], "unsupported")
        self.assertEqual(self.cases["probe-failed"]["expected"]["state"], "unavailable")
        self.assertEqual(self.cases["not-an-object"]["expected"]["state"], "unavailable")

    def test_unknown_codes_fall_back(self):
        self.assertEqual(self.cases["unknown-codes"]["expected"]["reason_key"],
                         "source_check_reason_unknown")

    def test_reason_keys_exist(self):
        with open(os.path.join(SHARED, "branding", "copy-defaults.json"), encoding="utf-8") as fh:
            copy = json.load(fh)
        for case in self.cases.values():
            self.assertIn(case["expected"]["reason_key"], copy, case["name"])
            if case["expected"]["state"] != "stale":  # dropped, never shown
                self.assertIn("source_check_" + case["expected"]["state"], copy, case["name"])
            for line in case["expected"]["defaults"]:
                self.assertIn(line["key"], copy, case["name"])

    def test_probe_args_select_only(self):
        """The probe gets image references, never a recipe."""
        for case in self.cases.values():
            for arg in case["probe_args"]:
                if arg.startswith("--"):
                    self.assertIn(arg, ("--source", "--live-root", "--target-imgref"))


class RealProbeOutputTest(unittest.TestCase):
    """The probe fixtures are fisherman's output with `capabilities` and
    `bootc_store` (laptop.json is its golden file). A plain probe selects
    no source, so it answers no_source_selected, and a frontend that asked
    about a source drops it as a reply for another source."""

    def _probe(self, name):
        with open(os.path.join(PROBE, "fixtures", name + ".json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_plain_probe_selects_no_source(self):
        from bootc_shared import source_check
        for name in ("laptop", "container", "vm", "pure-live-oci"):
            with self.subTest(fixture=name):
                result = self._probe(name)
                view = source_check.source_check(result, source_check.request())
                self.assertEqual((view["state"], view["reason"]),
                                 ("unavailable", "no_source_selected"))
                asked = source_check.source_check(
                    result, source_check.request(source="ghcr.io/example/os:stable"))
                self.assertEqual(asked["state"], "stale")

    def test_the_laptop_lists_its_booted_image(self):
        from bootc_shared import source_check
        store = source_check.bootc_store(self._probe("laptop"))
        self.assertEqual(store["state"], "listed")
        self.assertEqual([(i["ref"], i["kind"], i["installable"]) for i in store["items"]],
                         [("ghcr.io/example/os:stable", "booted", False)])
        self.assertEqual(source_check.bootc_store(self._probe("container"))["reason"],
                         "bootc_missing")


class BootcStoreRulesTest(unittest.TestCase):
    def test_no_item_is_installable(self):
        for case in _cases(STORE):
            for item in case["expected"]["items"]:
                self.assertIs(item["installable"], False, case["name"])

    def test_redacted_references_are_hidden(self):
        case = {c["name"]: c for c in _cases(STORE)}["credentials"]
        self.assertEqual(case["expected"]["items"], [])
        self.assertGreater(case["expected"]["hidden"], 0)

    def test_kind_keys_exist(self):
        with open(os.path.join(SHARED, "branding", "copy-defaults.json"), encoding="utf-8") as fh:
            copy = json.load(fh)
        for case in _cases(STORE):
            for item in case["expected"]["items"]:
                self.assertIn("bootc_store_kind_" + item["kind"], copy, case["name"])


class SourceReuseRulesTest(unittest.TestCase):
    """#267: an item of this computer's bootc storage is a second install
    source only where fisherman can install from it (SOURCE-REUSE.md,
    "Which items qualify"), and never on live media."""

    def setUp(self):
        from bootc_shared import source_check
        self.sc = source_check
        self.cases = {c["name"]: c for c in _cases(REUSE)}

    def test_every_golden_inventory_has_a_case(self):
        fixtures = {c["fixture"] for c in self.cases.values()}
        for name in os.listdir(os.path.join(PROBE, "fixtures", "bootc-store")):
            if name.startswith("store-"):
                self.assertIn(name, fixtures)

    def test_an_offered_item_is_one_that_fisherman_takes(self):
        offered = [c for c in self.cases.values() if c["expected"]]
        self.assertGreaterEqual(len(offered), 3)
        for case in offered:
            with open(os.path.join(PROBE, "fixtures", "bootc-store", case["fixture"]),
                      encoding="utf-8") as fh:
                store = json.load(fh)
            item = next(i for i in store["items"] if i.get("digest") == case["expected"]["digest"])
            with self.subTest(case=case["name"]):
                self.assertIs(case["live"], False)
                self.assertTrue(store["available"])
                self.assertEqual((item["storage"], item["availability"]), ("ostree", "deployed"))
                self.assertIs(item["matches_machine"], True)
                self.assertIn("booted", item["roles"])

    def test_never_on_live_media_or_without_live_facts(self):
        for name in ("live-media", "store-live-media", "no-live-facts", "probe-failed",
                     "old-backend", "version-2", "staged-update-moves-the-ref",
                     "other-update-ref", "no-update-ref", "untrusted-items",
                     "store-composefs", "store-wrong-arch-machine", "store-credentials"):
            self.assertIsNone(self.cases[name]["expected"], name)

    def test_the_recipe_keeps_the_update_reference_and_leaves_image_empty(self):
        for case in self.cases.values():
            if not case["expected"]:
                continue
            recipe = case["recipe"]
            with self.subTest(case=case["name"]):
                self.assertEqual(recipe["image"], "")
                self.assertEqual(recipe["targetImgref"], case["update_ref"])
                self.assertIn("bootc_store_reuse", recipe["experimental"])
                self.assertEqual(recipe["sourceReuse"], {
                    "store": "bootc", "digest": case["expected"]["digest"],
                    "platform": case["expected"]["platform"]})
                self.assertNotIn("passphrase", json.dumps(case["fragment"]))
                self.assertNotIn("hostname", case["fragment"])

    def test_the_recipe_is_valid_for_the_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("python3-jsonschema is not installed")
        with open(os.path.join(SHARED, "recipe", "fisherman-recipe.schema.json"),
                  encoding="utf-8") as fh:
            validator = jsonschema.Draft7Validator(json.load(fh))
        for case in self.cases.values():
            if case["expected"]:
                self.assertEqual(list(validator.iter_errors(case["recipe"])), [], case["name"])

    def test_no_item_means_the_recipe_is_unchanged(self):
        recipe = {"image": "a", "targetImgref": "a"}
        self.assertEqual(self.sc.apply_reuse(recipe, None), recipe)

    def test_every_source_reuse_code_has_a_copy_line(self):
        reuse_go = os.path.join(FISHERMAN, "recipe", "reuse.go")
        if not os.path.exists(reuse_go):
            self.skipTest("fisherman submodule not checked out")
        with open(reuse_go, encoding="utf-8") as fh:
            codes = set(re.findall(r'=\s*"(source_reuse_[a-z_]+)"', fh.read()))
        self.assertEqual(len(codes), 26)
        with open(os.path.join(SHARED, "branding", "copy-defaults.json"), encoding="utf-8") as fh:
            copy = json.load(fh)
        have = {k[len("validate_"):] for k in copy if k.startswith("validate_source_reuse_")}
        self.assertEqual(have, codes)


class VerificationRulesTest(unittest.TestCase):
    def test_verified_needs_fishermans_verified(self):
        for case in _cases(VERIFY):
            if case["expected"]["state"] != "verified":
                continue
            with open(os.path.join(COMPLETION, "fixtures", case["fixture"]), encoding="utf-8") as fh:
                result = json.load(fh)
            self.assertEqual(result["outcome"], "verified", case["name"])
            self.assertNotIn("mismatch", result["checks"].values(), case["name"])

    def test_negative_cases(self):
        cases = {c["name"]: c["expected"] for c in _cases(VERIFY)}
        self.assertEqual(cases["stale-prior-install"]["state"], "unavailable")
        self.assertEqual(cases["wrong-image-mismatch"]["state"], "mismatch")
        self.assertEqual(cases["no-receipt-live"]["state"], "unavailable")
        self.assertEqual(cases["version-2"]["state"], "unsupported")
        self.assertEqual(cases["not-yet-run"]["state"], "pending")
        self.assertEqual(cases["verified-but-check-mismatch"]["state"], "unavailable")


FRONTEND_SOURCES = [
    ("bootc_installer", (".py",)),
    ("frontends/xfce/tuna_installer_xfce", (".py",)),
    ("frontends/kde/src", (".cpp", ".h")),
    ("frontends/kde/modules", (".qml",)),
    ("frontends/cosmic/src", (".rs",)),
    ("frontends/niri/installer", (".go",)),
    ("frontends/niri/ui", (".qml",)),
    ("shared/python/bootc_shared", (".py",)),
]

# A frontend that runs bootc, or a store command, decides a fact that is
# fisherman's (#266, #267): the image list needs root and writes.
BOOTC_CALL = re.compile(
    r"""["']bootc["']\s*,\s*["'](image|status|container|install)\b"""
    r"""|["']bootc (image|status|container|install)\b"""
    r"""|copy-to-storage|set-unified|pull-from-default-storage""")


class NoBootcInFrontendsTest(unittest.TestCase):
    def test_no_frontend_runs_bootc(self):
        offenders = []
        for subdir, exts in FRONTEND_SOURCES:
            for root, _, files in os.walk(os.path.join(REPO, subdir)):
                for name in files:
                    if not name.endswith(exts) or name.endswith("_test.go"):
                        continue
                    path = os.path.join(root, name)
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        for n, line in enumerate(fh, 1):
                            if line.lstrip().startswith(("#", "//", "*", "assert")):
                                continue
                            if BOOTC_CALL.search(line):
                                offenders.append(f"{os.path.relpath(path, REPO)}:{n}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
