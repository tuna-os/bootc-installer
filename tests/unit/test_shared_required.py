"""shared/README.md, "Required by this version" (#226).

Each boot stack row names a case of the compliance fixture
(shared/recipe/fixtures/compliance.json, which all five frontends run)
with the same bootloader, storage backend and filesystem; the region row
names a case with the same locale, keyboard and time zone. Each language
row has a catalog in every frontend. A row that names nothing that a frontend test reads is a claim,
not a requirement.
"""

import json
import os
import re
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
README = os.path.join(REPO, "shared", "README.md")
COMPLIANCE = os.path.join(REPO, "shared", "recipe", "fixtures", "compliance.json")
FIXTURE = "recipe/fixtures/compliance.json"

# Where each frontend keeps the catalog of a language (shared/i18n/README.md).
LANGUAGE_CATALOGS = {
    "gnome": "po/{lang}.po",
    "kde": "frontends/kde/i18n/tuna-installer-kde_{lang}.ts",
    "niri": "frontends/niri/i18n/tuna-installer-niri_{lang}.ts",
    "xfce": "frontends/xfce/po/{lang}.po",
    "cosmic": "frontends/cosmic/i18n/{lang}.json",
}


def _rows():
    with open(README, encoding="utf-8") as stream:
        text = stream.read()
    section = text.split("## Required by this version\n", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] not in ("Requirement", "---"):
            rows.append(cells)
    return rows


def _codes(cell):
    return re.findall(r"`([^`]+)`", cell)


class RequiredByThisVersion(unittest.TestCase):
    def test_the_table_has_boot_stacks_and_languages(self):
        kinds = {row[0] for row in _rows()}
        self.assertIn("Boot stack", kinds)
        self.assertIn("Language of the interface", kinds)

    def _case(self, cell):
        self.assertIn(FIXTURE, cell)
        with open(COMPLIANCE, encoding="utf-8") as stream:
            cases = {case["name"]: case["recipe"] for case in json.load(stream)["cases"]}
        name = _codes(cell)[0]
        self.assertIn(name, cases, f"no compliance case {name}")
        return name, cases[name]

    def test_every_boot_stack_has_a_compliance_case(self):
        stacks = [row for row in _rows() if row[0] == "Boot stack"]
        self.assertGreaterEqual(len(stacks), 2)
        for _kind, values, cell in stacks:
            bootloader, filesystem = _codes(values)
            composefs = "composefs" in values
            self.assertTrue(composefs or "ostree" in values, values)
            name, recipe = self._case(cell)
            self.assertEqual(recipe.get("bootloader"), bootloader, name)
            self.assertEqual(bool(recipe.get("composeFsBackend")), composefs, name)
            self.assertEqual(recipe.get("filesystem"), filesystem, name)

    def test_every_compliance_boot_stack_is_listed(self):
        """A stack that the compliance fixture holds the frontends to is
        a requirement, so the table lists it."""
        with open(COMPLIANCE, encoding="utf-8") as stream:
            cases = json.load(stream)["cases"]
        listed = {(_codes(v)[0], "composefs" in v, _codes(v)[1])
                  for k, v, _c in _rows() if k == "Boot stack"}
        for case in cases:
            r = case["recipe"]
            stack = (r.get("bootloader"), bool(r.get("composeFsBackend")), r.get("filesystem"))
            self.assertIn(stack, listed, case["name"])

    def test_the_region_row_has_a_compliance_case(self):
        region = [row for row in _rows() if row[0] == "Region in the recipe"]
        self.assertEqual(len(region), 1)
        locale, layout, zone = _codes(region[0][1])
        name, recipe = self._case(region[0][2])
        self.assertEqual(recipe.get("locale"), locale, name)
        self.assertEqual((recipe.get("keyboard") or {}).get("layout"), layout, name)
        self.assertEqual(recipe.get("timezone"), zone, name)

    def test_every_language_has_a_catalog_in_each_frontend(self):
        languages = [row for row in _rows() if row[0] == "Language of the interface"]
        self.assertTrue(languages)
        for _kind, values, _case in languages:
            for lang in _codes(values):
                for frontend, pattern in LANGUAGE_CATALOGS.items():
                    path = os.path.join(REPO, pattern.format(lang=lang))
                    self.assertTrue(os.path.isfile(path), f"{frontend}: no {lang} catalog at {path}")



if __name__ == "__main__":
    unittest.main()
