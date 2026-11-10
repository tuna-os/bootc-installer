"""The recovery key is not in a log that stays on disk or leaves the installer.

shared/progress/recovery-key-cases.json pins the redacted form of fisherman's
`recovery_key` event, byte for byte, for every frontend that keeps a log
(#337). This file holds GNOME's `redact_recovery_key` to it; KDE's QtTest
(frontends/kde/tests/test_backend.cpp) reads the same file.
"""

import json
import pathlib
import unittest

from bootc_installer.utils.fisherman_session import REDACTED, redact_recovery_key

REPO = pathlib.Path(__file__).resolve().parents[2]
PROGRESS = REPO / "shared" / "progress"
SPEC = json.loads((PROGRESS / "recovery-key-cases.json").read_text(encoding="utf-8"))
KEY = SPEC["key"]
TRANSCRIPT = (PROGRESS / SPEC["transcript"]).read_text(encoding="utf-8")


class TheFixtureIsSound(unittest.TestCase):
    def test_the_transcript_has_one_recovery_key_event_with_the_key(self):
        events = [json.loads(line) for line in TRANSCRIPT.splitlines()]
        keys = [e for e in events if e["type"] == "recovery_key"]
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0]["key"], KEY)
        self.assertEqual(events[-1]["type"], "complete")

    def test_the_redacted_event_keeps_the_type_and_drops_the_key(self):
        event = json.loads(SPEC["redacted_event"])
        self.assertEqual(event["type"], "recovery_key")
        self.assertEqual(event["key"], SPEC["placeholder"])
        self.assertNotIn(KEY, SPEC["redacted_event"])

    def test_no_expected_line_has_the_key_unless_the_case_says_it_stays(self):
        for case in SPEC["lines"]:
            if KEY in case["redacted"]:
                self.assertFalse(case["known_key"], case["name"])
                self.assertIn("stays", case["name"])


class GnomeRedactionFollowsTheFixture(unittest.TestCase):
    def test_the_placeholder_is_the_shared_one(self):
        self.assertEqual(REDACTED, SPEC["placeholder"])

    def test_each_line_case(self):
        self.assertGreaterEqual(len(SPEC["lines"]), 5)
        for case in SPEC["lines"]:
            with self.subTest(case=case["name"]):
                known = KEY if case["known_key"] else ""
                self.assertEqual(redact_recovery_key(case["line"], known), case["redacted"])

    def test_the_transcript_as_a_log(self):
        """A log is the transcript with the one event in its redacted form."""
        want = "".join(
            (SPEC["redacted_event"] if '"recovery_key"' in line else line) + "\n"
            for line in TRANSCRIPT.splitlines())
        for known in ("", KEY):
            with self.subTest(known_key=bool(known)):
                got = redact_recovery_key(TRANSCRIPT, known)
                self.assertEqual(got, want)
                self.assertNotIn(KEY, got)


if __name__ == "__main__":
    unittest.main()
