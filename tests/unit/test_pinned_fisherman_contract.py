"""The shared readers against the pinned fisherman itself (#266, #267, #269).

The case files hold the five readers to fisherman's golden files. This
test closes the last step: it builds fisherman from the submodule pin and
runs the unprivileged commands that the frontends run, then reads the
answers through bootc_shared. A field that fisherman renames, or an answer
that the reader takes for a reply about another source, fails here, not on
a user's computer.

Only `probe --json` (with and without a selected source), `validate
--json --partial -` and `plan --json -` run. None needs root, pulls an
image or touches a disk. The build needs Go; without it the test skips.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from bootc_shared import plan as install_plan
from bootc_shared import progress, source_check
from bootc_shared import validate as fisherman_validate
from bootc_shared.branding import COPY_DEFAULTS

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOURCE = os.path.join(REPO, "fisherman", "fisherman")
REF = "ghcr.io/example/os:stable"


def _build(out_dir):
    go = shutil.which("go")
    if go is None or not os.path.isdir(os.path.join(SOURCE, "cmd", "fisherman")):
        return None
    binary = os.path.join(out_dir, "fisherman")
    try:
        subprocess.run([go, "build", "-o", binary, "./cmd/fisherman/"], cwd=SOURCE,
                       check=True, capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return None
    return binary


class PinnedFishermanContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.fisherman = _build(cls._tmp.name)
        if cls.fisherman is None:
            cls._tmp.cleanup()
            raise unittest.SkipTest("cannot build the pinned fisherman (no Go, or no submodule)")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _probe(self, args):
        env = {k: v for k, v in os.environ.items() if k != "BOOTC_INSTALLER_FAKE_PROBE"}
        proc = subprocess.run([self.fisherman, "probe", "--json", *args], capture_output=True,
                              text=True, timeout=120, env=env, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def _validate(self, fragment):
        return fisherman_validate.run(fisherman_validate.argv([self.fisherman]), fragment)

    def test_a_source_probe_answers_for_the_selected_source(self):
        req = source_check.request(source=REF, target=REF)
        view = source_check.source_check(self._probe(source_check.probe_args(req)), req)
        self.assertNotEqual(view["state"], "stale", view)
        self.assertNotEqual(view["state"], "unsupported", view)
        self.assertEqual(view["install_from"], REF)
        self.assertEqual(view["update_ref"], REF)
        self.assertIn(view["reason_key"], COPY_DEFAULTS)
        # A registry source is never checked here: the probe pulls nothing.
        self.assertNotEqual(view["state"], "ready")

    def test_a_plain_probe_selects_no_source(self):
        result = self._probe([])
        req = source_check.request(source=REF, target=REF)
        self.assertEqual(source_check.source_check(result, req)["state"], "stale")
        store = source_check.bootc_store(result)
        self.assertIn(store["state"], ("listed", "empty", "unavailable"))
        for item in store["items"]:
            self.assertIs(item["installable"], False)

    def test_the_reuse_reader_takes_the_real_probe(self):
        result = self._probe([])
        source = source_check.reuse_source(result, REF)
        if result.get("live", {}).get("is_live") is not False:
            self.assertIsNone(source)
        if source is not None:
            self.assertEqual(source["ref"], REF)

    def test_validate_accepts_the_reuse_fragment_of_the_cases(self):
        with open(os.path.join(REPO, "shared", "probe", "source-reuse-cases.json"),
                  encoding="utf-8") as fh:
            cases = [c for c in json.load(fh)["cases"] if c["expected"]]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertEqual(fisherman_validate.problems(self._validate(case["fragment"])), [])

    def test_validate_codes_have_copy_lines(self):
        fragment = {"image": "", "targetImgref": REF,
                    "sourceReuse": {"store": "bootc", "digest": "sha256:" + "1" * 64,
                                    "platform": "x86_64"}}
        problems = fisherman_validate.problems(self._validate(fragment))
        self.assertEqual([p["code"] for p in problems], ["source_reuse_experimental"])
        line = fisherman_validate.render(problems[0], lambda key: COPY_DEFAULTS.get(key, ""))
        self.assertEqual(line, COPY_DEFAULTS["validate_source_reuse_experimental"])

    def test_the_plan_reader_takes_the_real_plan_command(self):
        """`plan --json -` of the pin, for a disk that is not there: the
        reader parses the answer, and the recipe's passphrase is not in it."""
        secret = "pinned-plan-sentinel-passphrase"
        recipe = {"disk": "/dev/bootc-installer-no-such-disk", "image": REF,
                  "encryption": {"type": "luks-passphrase", "passphrase": secret}}
        proc = subprocess.run(install_plan.argv([self.fisherman]), input=json.dumps(recipe),
                              capture_output=True, text=True, timeout=120, check=False)
        self.assertNotIn(secret, proc.stdout + proc.stderr)
        result = install_plan.run(install_plan.argv([self.fisherman]), recipe)
        self.assertFalse(result["valid"])
        self.assertIsNone(result["plan"])
        self.assertTrue(result["errors"])

    def test_the_receipt_events_of_the_pin_parse(self):
        path = os.path.join(SOURCE, "internal", "progress", "testdata", "receipt-events.ndjson")
        with open(path, encoding="utf-8") as fh:
            lines = [line.strip() for line in fh if line.strip()]
        self.assertEqual(len(lines), 6)
        for line in lines:
            state = progress.new_progress_state()
            self.assertIsNone(progress.apply_progress_event(line, state))
            self.assertNotEqual(state["receipt"]["state"], "unreadable", line)


if __name__ == "__main__":
    unittest.main()
