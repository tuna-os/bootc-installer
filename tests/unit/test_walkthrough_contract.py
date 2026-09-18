"""The shared screen contract (shared/walkthrough/parity_report.py) is what
every frontend's capture reports parity against. Two things it must get
right, both of which were wrong on the first day of the monorepo."""

import importlib.util
import io
import pathlib
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[2]
SPEC = REPO / "shared" / "walkthrough" / "parity_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("_parity_report", SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


UPSTREAM_YAML = """
screens:
  - id: welcome
    keywords: ["welcome", "get started", "let's get", "begin",
               "will guide you through"]
  - id: install
    # a comment with "quotes" and [brackets]
    keywords: ["installation progress", "copying files", "deploying",
               "please wait", "writing image", "installing\\u2026",
               "partitioning", "installing image", "do not power off"]
"""


class DriftCheckTests(unittest.TestCase):
    def test_yaml_escapes_are_decoded_before_comparing(self):
        """Upstream writes the Niri heading as "installing\\u2026". Comparing
        the raw six characters against our decoded ellipsis reported drift
        on every capture job while the two lists were identical."""
        pr = _load()
        fake = io.BytesIO(UPSTREAM_YAML.encode("utf-8"))
        fake.__enter__ = lambda s: s
        fake.__exit__ = lambda s, *a: None
        with mock.patch("urllib.request.urlopen", return_value=fake):
            diffs = pr.verify_spec_matches_upstream()
        self.assertEqual([d for d in diffs if "install'" in d], [],
                         f"install keywords reported as drifted: {diffs}")


class ScreenMatchingTests(unittest.TestCase):
    def test_xfce_setup_page_counts_as_the_encryption_screen(self):
        """XFCE's combined page was titled "Filesystem and encryption", which
        matched no contract keyword, so the matrix showed XFCE as the one
        frontend without an encryption screen it plainly has."""
        pr = _load()
        pages = [
            {"name": "welcome", "text": "Welcome to TunaOS"},
            {"name": "setup", "text": "Disk encryption No encryption Passphrase Advanced Filesystem"},
        ]
        reached, detail = pr.match_screens(pages)
        self.assertTrue(reached["encryption"], detail["encryption"])
        self.assertEqual(detail["encryption"]["on_pages"], ["setup"])

    def test_first_page_never_credits_a_later_screen(self):
        pr = _load()
        pages = [{"name": "welcome",
                  "text": "Welcome. You will choose a disk and disk encryption, then confirm installation."}]
        reached, _ = pr.match_screens(pages)
        self.assertTrue(reached["welcome"])
        self.assertFalse(reached["encryption"])
        self.assertFalse(reached["summary"])


if __name__ == "__main__":
    unittest.main()
