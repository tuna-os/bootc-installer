"""docs/PARITY.md's Features table is generated, and cannot drift (#303).

The table was hand-written and was wrong in at least twelve cells after one
change. Each frontend now owns a manifest (frontends/<name>/features.json;
shared/walkthrough/features-gnome.json for the root frontend) and
shared/walkthrough/features.py renders the table from the five.

Three checks:
1. the committed table is exactly what the generator prints;
2. every manifest has exactly the rows of feature-rows.json and fits
   features.schema.json;
3. a cell that says "yes" for a row with machine-visible evidence (a
   walkthrough screen, a walkthrough report, an E2E job) has that evidence.
"""

import copy
import importlib.util
import json
import os
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
WALK = os.path.join(REPO, "shared", "walkthrough")

_spec = importlib.util.spec_from_file_location("parity_features", os.path.join(WALK, "features.py"))
features = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(features)


def _workflow(name):
    with open(os.path.join(REPO, ".github", "workflows", name), encoding="utf-8") as stream:
        return stream.read()


def _summary():
    with open(features.SUMMARY, encoding="utf-8") as stream:
        return json.load(stream)


class TableIsGenerated(unittest.TestCase):
    def test_committed_table_equals_the_generated_one(self):
        with open(features.PARITY, encoding="utf-8") as stream:
            document = stream.read()
        self.assertEqual(features.committed_table(document), features.generated_table(),
                         "run: python3 shared/walkthrough/features.py")
        self.assertEqual(features.main(["--check"]), 0)

    def test_the_document_says_the_table_is_generated(self):
        with open(features.PARITY, encoding="utf-8") as stream:
            document = stream.read()
        self.assertIn("shared/walkthrough/features.py", document)
        self.assertNotIn("Nothing generates it yet", document)

    def test_rewrite_is_stable(self):
        with open(features.PARITY, encoding="utf-8") as stream:
            document = stream.read()
        self.assertEqual(features.replace_table(document, features.generated_table()), document)

    def test_a_changed_cell_changes_the_table(self):
        rows = features.load_rows()
        manifests = features.load_manifests(rows)
        before = features.render(rows, manifests)
        changed = copy.deepcopy(manifests)
        changed["kde"]["features"]["staged_fisherman"] = "yes"
        after = features.render(rows, changed)
        self.assertNotEqual(before, after)
        self.assertEqual(sum(a != b for a, b in zip(before.splitlines(), after.splitlines())), 1)

    def test_markers_are_required_once(self):
        for document in ("no markers", f"{features.BEGIN}\n{features.BEGIN}\n{features.END}"):
            with self.assertRaises(features.FeatureError):
                features.replace_table(document, "x")


class Manifests(unittest.TestCase):
    def setUp(self):
        self.rows = features.load_rows()
        self.manifests = features.load_manifests(self.rows)

    def test_five_manifests_where_the_contract_says(self):
        self.assertEqual([frontend for frontend, _t, _p in features.FRONTENDS],
                         ["gnome", "kde", "cosmic", "niri", "xfce"])
        for frontend, _title, relative in features.FRONTENDS:
            self.assertTrue(os.path.isfile(os.path.join(REPO, relative)), relative)
            if frontend != "gnome":
                self.assertEqual(relative, f"frontends/{frontend}/features.json")

    def test_every_manifest_has_exactly_the_rows(self):
        ids = [row["id"] for row in self.rows]
        self.assertGreaterEqual(len(ids), 30)
        for frontend, manifest in self.manifests.items():
            self.assertEqual(sorted(manifest["features"]), sorted(ids), frontend)

    def test_a_missing_an_unknown_and_a_bad_cell_are_reported(self):
        manifest = copy.deepcopy(self.manifests["niri"])
        del manifest["features"]["hostname"]
        manifest["features"]["teleport"] = "yes"
        manifest["features"]["autoinstall"] = "a | b"
        manifest["features"]["translatable"] = " "
        problems = features.check_manifest("niri", manifest, self.rows)
        self.assertEqual(len(problems), 4, problems)
        self.assertTrue(features.check_manifest("kde", self.manifests["niri"], self.rows))

    def test_schema_lists_the_same_rows_and_frontends(self):
        with open(os.path.join(WALK, "features.schema.json"), encoding="utf-8") as stream:
            schema = json.load(stream)
        ids = [row["id"] for row in self.rows]
        cells = schema["properties"]["features"]
        self.assertEqual(cells["required"], ids)
        self.assertEqual(list(cells["properties"]), ids)
        self.assertEqual({row["id"]: row["label"] for row in self.rows},
                         {key: value["description"] for key, value in cells["properties"].items()})
        self.assertEqual(schema["properties"]["frontend"]["enum"],
                         [frontend for frontend, _t, _p in features.FRONTENDS])

    def test_manifests_fit_the_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("python3-jsonschema is not installed")
        with open(os.path.join(WALK, "features.schema.json"), encoding="utf-8") as stream:
            validator = jsonschema.Draft7Validator(json.load(stream))
        for frontend, manifest in self.manifests.items():
            self.assertEqual([error.message for error in validator.iter_errors(manifest)], [], frontend)


class Evidence(unittest.TestCase):
    def setUp(self):
        self.rows = features.load_rows()
        self.manifests = features.load_manifests(self.rows)

    def test_some_rows_have_evidence(self):
        kinds = set()
        for row in self.rows:
            kinds |= set(row.get("evidence", {})) - {"name"}
        self.assertEqual(kinds, {"walkthrough_screen", "walkthrough_report", "workflow_job"})

    def test_every_yes_with_evidence_is_backed(self):
        self.assertEqual(
            features.evidence_problems(self.rows, self.manifests, _summary(), _workflow), [])

    def test_evidence_screens_are_screens_of_the_contract(self):
        screens = set(_summary()["screens"])
        for row in self.rows:
            screen = row.get("evidence", {}).get("walkthrough_screen")
            if screen:
                self.assertIn(screen, screens, row["id"])

    def test_a_claim_without_its_screen_fails(self):
        summary = copy.deepcopy(_summary())
        summary["screens"]["encryption"]["xfce"] = "no"
        problems = features.evidence_problems(self.rows, self.manifests, summary, _workflow)
        self.assertEqual(len(problems), 1)
        self.assertIn("xfce", problems[0])
        self.assertIn("encryption_passphrase", problems[0])

    def test_a_claim_without_its_report_or_job_fails(self):
        summary = copy.deepcopy(_summary())
        summary["frontends"]["niri"]["report"] = False
        problems = features.evidence_problems(self.rows, self.manifests, summary, lambda name: "")
        self.assertTrue(any("niri" in p and "walkthrough" in p for p in problems))
        self.assertEqual(sum("e2e_gate" in p for p in problems), 5)

    def test_a_cell_that_does_not_say_yes_needs_no_evidence(self):
        manifests = copy.deepcopy(self.manifests)
        manifests["kde"]["features"]["e2e_gate"] = "no (#999)"
        self.assertEqual(features.evidence_problems(self.rows, manifests, _summary(), lambda name: ""
                                                    if name != "e2e.yml" else _workflow(name)), [])
        self.assertTrue(features.claims_yes("yes (TLS)"))
        self.assertTrue(features.claims_yes("Yes"))
        self.assertFalse(features.claims_yes("yesterday"))
        self.assertFalse(features.claims_yes("no (#290)"))


if __name__ == "__main__":
    unittest.main()
