"""The pixel audit and the capture fixtures in shared/walkthrough/ are what
the GNOME, XFCE and Niri capture harnesses and report_from_pngs.py all read.
Each harness used to carry its own copy of the arithmetic."""

import json
import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "shared" / "walkthrough"))

import capture_fixtures  # noqa: E402
import pixel_audit  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
