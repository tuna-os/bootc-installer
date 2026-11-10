"""The recipe.json the Flatpak ships (#315).

It is the recipe of last resort: a host that ships none gets this one. It
must reach the image catalog, check the connection before a download, and
name no product.
"""

import json
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
RECIPE = json.loads((REPO / "recipe.json").read_text(encoding="utf-8"))


class TestBundledRecipe(unittest.TestCase):
    def test_names_no_image_and_no_product(self):
        """`imgref` and `images` pinned one product's image, so the Flatpak
        could install nothing else, and CLAUDE.md said the file had no
        product strings."""
        for key in ("imgref", "images", "distro_name", "welcome_title", "local_imgref"):
            self.assertNotIn(key, RECIPE, f"recipe.json must not set {key}")
        text = json.dumps(RECIPE).lower()
        for word in ("bluefin", "dakota", "tunaos", "tuna-os", "ghcr.io", "quay.io"):
            self.assertNotIn(word, text)

    def test_has_the_image_and_connection_steps(self):
        steps = list(RECIPE["steps"])
        self.assertIn("image", steps)
        self.assertIn("conn-check", steps)
        # The connection is checked before the catalog is offered, and the
        # disk is chosen after the image (its filesystems follow the image).
        self.assertLess(steps.index("conn-check"), steps.index("image"))
        self.assertLess(steps.index("image"), steps.index("disk"))

    def test_every_step_names_a_template_the_builder_has(self):
        source = (REPO / "bootc_installer" / "utils" / "builder.py").read_text(encoding="utf-8")
        for key, step in RECIPE["steps"].items():
            self.assertIn(f'"{step["template"]}":', source, key)

    def test_steps_up_to_the_image_step_are_protected(self):
        """The image step rebuilds every step that is not protected and
        appends it again. A step before it that is not protected would
        move behind it."""
        steps = list(RECIPE["steps"].items())
        last = [k for k, _ in steps].index("image")
        for key, step in steps[: last + 1]:
            self.assertTrue(step.get("protected"), f"{key} must be protected")
        for key, step in steps[last + 1:]:
            self.assertNotIn("protected", step, f"{key} must follow the image")


if __name__ == "__main__":
    unittest.main()
