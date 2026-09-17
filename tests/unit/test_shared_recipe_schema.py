"""The recipe schema is the contract every frontend writes against.

shared/recipe/fisherman-recipe.schema.json is the canonical copy. The KDE
frontend still installs its own copy from frontends/kde/ (its Flatpak builds
from that directory alone, so it cannot reach shared/ at build time). Until
that build reads the shared file, the two must stay byte-identical, or the
"shared" schema is a lie.
"""

import json
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SHARED = REPO / "shared" / "recipe" / "fisherman-recipe.schema.json"
KDE = REPO / "frontends" / "kde" / "fisherman-recipe.schema.json"


class SharedRecipeSchemaTests(unittest.TestCase):
    def test_shared_schema_is_valid_json_schema(self):
        doc = json.loads(SHARED.read_text())
        self.assertIn("$schema", doc)
        self.assertIn("properties", doc)
        for field in ("disk", "encryption", "image"):
            self.assertIn(field, doc["properties"], f"schema lost the '{field}' field")

    def test_kde_copy_matches_shared(self):
        self.assertEqual(
            KDE.read_bytes(), SHARED.read_bytes(),
            "frontends/kde/fisherman-recipe.schema.json has diverged from "
            "shared/recipe/fisherman-recipe.schema.json; change the shared copy "
            "and copy it over, not the other way round",
        )


if __name__ == "__main__":
    unittest.main()
