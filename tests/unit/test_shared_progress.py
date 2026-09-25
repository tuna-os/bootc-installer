"""The fisherman progress protocol: canonical parser, copies, and fixture.

shared/progress/ is canonical; each Python frontend keeps a byte-identical
copy, the same arrangement shared/branding/ and shared/recipe/ use.

These tests exist because the XFCE frontend spent its whole life parsing a
"[n/9] " step prefix that fisherman has never emitted. Nothing caught it: the
frontend's own dry-run fixture was written in that shape, so the screenshot
harness photographed a bar advancing through a format no install produces
while the bar on a real install sat at zero. So the assertions below are
deliberately pointed at the wire format fisherman actually writes, and at the
one property the old code got wrong in both directions — that the bar moves.
"""

import importlib.util
import json
import os
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
CANONICAL = os.path.join(REPO, "shared", "progress", "progress_parser.py")
TRANSCRIPT = os.path.join(REPO, "shared", "progress", "dry-run-transcript.ndjson")

COPIES = [
    os.path.join(REPO, "bootc_installer", "utils", "progress_parser.py"),
    os.path.join(REPO, "frontends", "xfce", "tuna_installer_xfce", "progress_parser.py"),
]
TRANSCRIPT_COPIES = [
    os.path.join(REPO, "frontends", "xfce", "tuna_installer_xfce",
                 "dry-run-transcript.ndjson"),
]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


class CanonicalCopyTest(unittest.TestCase):
    def test_parser_copies_are_byte_identical(self):
        want = _read(CANONICAL)
        for path in COPIES:
            with self.subTest(copy=os.path.relpath(path, REPO)):
                self.assertEqual(
                    want, _read(path),
                    "copy has drifted from shared/progress/progress_parser.py; "
                    "edit the canonical file and re-copy, never the copy")

    def test_transcript_copies_are_byte_identical(self):
        want = _read(TRANSCRIPT)
        for path in TRANSCRIPT_COPIES:
            with self.subTest(copy=os.path.relpath(path, REPO)):
                self.assertEqual(want, _read(path))


class TranscriptShapeTest(unittest.TestCase):
    """The fixture must be fisherman's wire format, not a frontend's idea of it."""

    def setUp(self):
        with open(TRANSCRIPT, encoding="utf-8") as fh:
            self.lines = [ln for ln in fh.read().splitlines() if ln.strip()]

    def test_every_line_is_a_json_object_with_a_type(self):
        for line in self.lines:
            event = json.loads(line)  # raises if the fixture regresses to text
            self.assertIsInstance(event, dict)
            self.assertIn("type", event)

    def test_no_line_carries_a_step_prefix(self):
        # The exact bug: "[1/9] Partitioning /dev/vda" is not a fisherman line.
        for line in self.lines:
            self.assertNotRegex(line, r"^\[\d+/\d+\]")

    def test_step_events_carry_the_fields_a_bar_needs(self):
        steps = [json.loads(ln) for ln in self.lines]
        steps = [e for e in steps if e["type"] == "step"]
        self.assertTrue(steps)
        for event in steps:
            for field in ("step", "total_steps", "step_name",
                          "cumulative_pct", "weight_pct"):
                self.assertIn(field, event)

    def test_total_steps_is_not_nine(self):
        # Not a style point. The old parser hardcoded /9; this configuration
        # emits 8, so that parser would not have matched a single line.
        totals = {json.loads(ln).get("total_steps") for ln in self.lines}
        totals.discard(None)
        self.assertEqual({8}, totals)

    def test_names_no_product(self):
        # A fixture is rendered into docs/ screenshots; a product name here
        # ships that product's branding to everyone who rebrands.
        blob = "\n".join(self.lines).lower()
        for banned in ("tunaos", "bluefin", "bonito", "ghcr.io"):
            self.assertNotIn(banned, blob)


class ParserDrivesTheBarTest(unittest.TestCase):
    def setUp(self):
        self.pp = _load(CANONICAL, "canonical_progress_parser")
        self.state = self.pp.new_progress_state()
        with open(TRANSCRIPT, encoding="utf-8") as fh:
            self.lines = [ln for ln in fh.read().splitlines() if ln.strip()]

    def _run(self):
        out = []
        for line in self.lines:
            update = self.pp.apply_progress_event(line, self.state)
            if update is not None:
                out.append(update)
        return out

    def test_the_transcript_produces_updates(self):
        self.assertTrue(self._run(), "parser matched nothing — the exact old bug")

    def test_the_bar_advances_and_never_goes_backwards(self):
        fractions = [u["fraction"] for u in self._run() if u["fraction"] is not None]
        self.assertEqual(sorted(fractions), fractions)
        self.assertLess(fractions[0], fractions[-1])

    def test_the_bar_reaches_one_hundred_percent(self):
        self.assertEqual(1.0, self._run()[-1]["fraction"])

    def test_substeps_move_the_bar_inside_the_long_step(self):
        # Installing OS is 87% of a cold install. Without substep
        # interpolation the bar would freeze there for most of the install.
        seen = [u["fraction"] for u in self._run() if u["fraction"] is not None]
        mid = [f for f in seen if 0.01 < f < 0.88]
        self.assertGreaterEqual(len(mid), 2, "no intra-step progress")

    def test_product_label_is_branded_not_hardcoded(self):
        self.pp.set_product_name("ExampleOS")
        labels = [u["label"] for u in self._run() if u["label"]]
        self.assertTrue(any("ExampleOS" in text for text in labels))
        for banned in ("Bluefin", "TunaOS"):
            self.assertFalse(any(banned in text for text in labels))

    def test_unknown_step_name_falls_back_to_the_raw_name(self):
        line = json.dumps({"type": "step", "step": 1, "total_steps": 3,
                           "step_name": "Polishing the hull",
                           "cumulative_pct": 10, "weight_pct": 5})
        update = self.pp.apply_progress_event(line, self.pp.new_progress_state())
        self.assertEqual("Polishing the hull", update["label"])

    def test_non_json_lines_are_ignored(self):
        # fisherman's stderr is interleaved into the same view.
        state = self.pp.new_progress_state()
        self.assertIsNone(self.pp.apply_progress_event("fisherman: warning", state))
        self.assertIsNone(self.pp.apply_progress_event("", state))


if __name__ == "__main__":
    unittest.main()
