"""Every runtime failure code fisherman can emit has a failure-page line.

The done page reads an error event's `code` as the copy key
`validate_<code>` (bootc_installer/views/done.py). fisherman lists its
runtime failure codes in internal/progress/failure.go. A code with no copy
key falls back to a generic line, so a new code that bootc-installer does not
know is found here, at the pin that adds it, and not on a user's screen.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAILURE_GO = ROOT / "fisherman" / "fisherman" / "internal" / "progress" / "failure.go"
COPY = ROOT / "shared" / "branding" / "copy-defaults.json"


def failure_codes(text):
    return set(re.findall(r'^\s*Failure\w+\s*=\s*"([a-z0-9_]+)"', text, re.M))


class FailureCodesHaveCopy(unittest.TestCase):
    def test_the_reader_finds_codes(self):
        sample = 'const (\n\tFailureUnknown = "unknown"\n\tFailureLockFailed   = "lock_failed"\n)\n'
        self.assertEqual(failure_codes(sample), {"unknown", "lock_failed"})

    def test_every_fisherman_failure_code_has_a_copy_line(self):
        if not FAILURE_GO.exists():
            self.fail(f"{FAILURE_GO} is missing: check out the fisherman submodule")
        codes = failure_codes(FAILURE_GO.read_text(encoding="utf-8"))
        self.assertGreater(len(codes), 10, "the failure code reader found almost nothing")
        copy = json.loads(COPY.read_text(encoding="utf-8"))
        missing = sorted(c for c in codes if f"validate_{c}" not in copy)
        self.assertEqual(missing, [], "add validate_<code> lines to shared/branding/copy-defaults.json")


if __name__ == "__main__":
    unittest.main()
