"""The pixel audit and the capture fixtures in shared/walkthrough/ are what
the GNOME, XFCE and Niri capture harnesses and report_from_pngs.py all read.
Each harness used to carry its own copy of the arithmetic."""

import json
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "shared" / "walkthrough"))

import capture_fixtures
import pixel_audit


def _image(rows):
    return len(rows[0]), len(rows), lambda x, y: rows[y][x]


WHITE, BLACK, GREY = (255, 255, 255), (0, 0, 0), (100, 100, 100)


class StatsTests(unittest.TestCase):
    def test_light_theme_counts_dark_pixels_as_ink(self):
        w, h, px = _image([[WHITE, WHITE], [WHITE, BLACK]])
        s = pixel_audit.stats(w, h, px, step=1)
        self.assertEqual(s["colours"], 2)
        self.assertEqual(s["flat"], 0.75)
        self.assertEqual(s["ink"], 0.25)
        # luma 255 x3 and 0 x1: mean 191.25, variance 12192.1875.
        self.assertAlmostEqual(s["stddev"], (12192.1875 ** 0.5) / 255.0)

    def test_dark_theme_rule_counts_light_pixels(self):
        w, h, px = _image([[BLACK, BLACK], [BLACK, GREY]])
        s = pixel_audit.stats(w, h, px, step=1, ink=lambda luma: luma > 60)
        self.assertEqual(s["ink"], 0.25)

    def test_step_samples_every_nth_pixel_of_every_nth_row(self):
        rows = [[BLACK if (x, y) == (0, 0) else WHITE for x in range(4)]
                for y in range(4)]
        w, h, px = _image(rows)
        s = pixel_audit.stats(w, h, px, step=3)
        # (0,0) (3,0) (0,3) (3,3)
        self.assertEqual(s["ink"], 0.25)
        self.assertEqual(s["flat"], 0.75)

    def test_luma_is_the_integer_30_59_11_weighting(self):
        # (30*200 + 59*120 + 11*40) // 100 = 135.2 -> 135, below 160.
        w, h, px = _image([[(200, 120, 40)]])
        self.assertEqual(pixel_audit.stats(w, h, px)["ink"], 1.0)

    def test_empty_image_has_no_stats(self):
        self.assertIsNone(pixel_audit.stats(0, 0, lambda x, y: WHITE))


class FixtureTests(unittest.TestCase):
    def test_transcript_is_cut_in_the_middle_of_the_image_pull(self):
        lines = capture_fixtures.fixture_log()
        self.assertIn(capture_fixtures.CUT_MARKER, lines[-1])
        self.assertTrue(all(ln.strip() for ln in lines))
        for ln in lines:
            json.loads(ln)

    def test_recovery_event_carries_the_key(self):
        event = json.loads(capture_fixtures.RECOVERY_EVENT)
        self.assertEqual(event["type"], "recovery_key")
        self.assertEqual(event["key"], capture_fixtures.RECOVERY_KEY)


class ReportFromPngsTests(unittest.TestCase):
    """KDE hands report_from_pngs.py its own audit and its item text."""

    def test_harness_audit_and_item_text_are_used(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            # A PNG header and nothing a decoder could audit: audit.json
            # covers the pixels. The strict check reads the header (#186).
            for i, name in enumerate(("01-welcome.png", "02-disk.png")):
                (d / name).write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR"
                                       + struct.pack(">II", 8, 8) + bytes([i]))
            audit = {"rendered": False, "colours": 7, "flat": 0.5,
                     "ink": 0.25, "stddev": 0.125}
            (d / "audit.json").write_text(json.dumps(
                {"welcome": dict(audit, rendered=True), "disk": audit}))
            (d / "texts.json").write_text(json.dumps(
                {"welcome": "Welcome", "disk": "Where should it be installed?"}))
            subprocess.run(
                [sys.executable, str(REPO / "shared" / "walkthrough" / "report_from_pngs.py"),
                 "kde", str(d), "--harness", "h", "--text-source", "qml-item-tree"],
                check=True, capture_output=True)
            report = json.loads((d / "walkthrough-kde.json").read_text())
        self.assertEqual(report["text_source"], "qml-item-tree")
        self.assertIn("item tree", report["notes"])
        self.assertEqual(report["rendered_frames"], 1)
        self.assertEqual(report["pages"][1]["colours"], 7)
        self.assertEqual(report["pages"][1]["flat"], 0.5)
        self.assertTrue(report["screens"]["welcome"])
        # The disk text matched, but the harness audit says the page did not
        # render, so the screen has no evidence: a strict failure (#186).
        self.assertEqual(report["screens_detail"]["disk"]["on_pages"], ["disk"])
        self.assertFalse(report["screens"]["disk"])
        self.assertEqual(report["screen_outcomes"]["disk"]["outcome"], "failed")
        # summary fails too: this fixture has no confirm page.
        self.assertEqual([f["screen"] for f in report["failure_reasons"]],
                         ["disk", "summary"])
        self.assertEqual(report["failures"], 2)


if __name__ == "__main__":
    unittest.main()
