"""shared/README.md, "Required by this version" (#226).

Each boot stack row names a fixture case with the same bootloader,
storage backend and filesystem. Each language row has a catalog in every
frontend. A row that names nothing that a frontend test reads is a claim,
not a requirement.
"""

import json
import os
import re
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
README = os.path.join(REPO, "shared", "README.md")
EXPECTED = os.path.join(REPO, "shared", "catalog", "fixtures", "expected.json")

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

    def test_every_boot_stack_has_a_fixture_case(self):
        with open(EXPECTED, encoding="utf-8") as stream:
            leaves = {entry["imgref"]: entry for entry in json.load(stream)["leaves"]}
        stacks = [row for row in _rows() if row[0] == "Boot stack"]
        self.assertGreaterEqual(len(stacks), 2)
        for _kind, values, case in stacks:
            bootloader, filesystem = _codes(values)
            composefs = "composefs" in values
            self.assertTrue(composefs or "ostree" in values, values)
            self.assertIn("catalog/fixtures/expected.json", case)
            imgref = [code for code in _codes(case) if code.startswith("registry.")]
            self.assertEqual(len(imgref), 1, case)
            entry = leaves.get(imgref[0])
            self.assertIsNotNone(entry, f"no fixture leaf {imgref[0]}")
            leaf = entry["leaf"]
            self.assertEqual(leaf["bootloader"], bootloader, imgref[0])
            self.assertEqual(bool(leaf["composefs"]), composefs, imgref[0])
            self.assertEqual(leaf["filesystem"], filesystem, imgref[0])
            self.assertTrue(entry["cases"], f"{imgref[0]} has no case")

    def test_every_language_has_a_catalog_in_each_frontend(self):
        languages = [row for row in _rows() if row[0] == "Language of the interface"]
        self.assertTrue(languages)
        for _kind, values, _case in languages:
            for lang in _codes(values):
                for frontend, pattern in LANGUAGE_CATALOGS.items():
                    path = os.path.join(REPO, pattern.format(lang=lang))
                    self.assertTrue(os.path.isfile(path), f"{frontend}: no {lang} catalog at {path}")

    def test_the_region_row_names_what_the_kde_driver_picks(self):
        region = [row for row in _rows() if row[0] == "Region in the recipe"]
        self.assertEqual(len(region), 1)
        with open(os.path.join(REPO, "frontends", "kde", "tests", "e2e.cpp"), encoding="utf-8") as stream:
            driver = stream.read()
        for value in ("de_DE.UTF-8", "de", "Europe/Berlin"):
            self.assertIn(value, _codes(region[0][2]))
            self.assertIn(f'"{value}"', driver)


if __name__ == "__main__":
    unittest.main()
