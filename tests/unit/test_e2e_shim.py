"""shared/e2e/fisherman-shim.sh streams what a current fisherman emits.

The e2e gate exists to drive every frontend's real backend path with
fisherman's real protocol. Since tuna-os/fisherman#270 that protocol carries
overall_pct on step, substep and complete events and step_id on step events,
and the frontends prefer both. A shim with stale numbers would show the
frontends a bar fisherman never draws, so this reads the shim's event lines
and checks them against the reference parser and fisherman's id table.
"""

import json
import os
import re
import shlex
import unittest

from tests.unit.test_shared_progress import (
    CANONICAL, FISHERMAN_BAR, _fisherman_step_ids, _load)

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
SHIM = os.path.join(REPO, "shared", "e2e", "fisherman-shim.sh")


def shim_events():
    """The shim's events, rebuilt from its `step` / `substep` calls."""
    with open(SHIM, encoding="utf-8") as fh:
        text = fh.read()
    events, n = [], 0
    for line in text.splitlines():
        if line.startswith("step "):
            name, step_id, cumulative, weight, overall = shlex.split(line)[1:]
            n += 1
            events.append({"type": "step", "step": n, "total_steps": 8,
                           "step_name": name, "step_id": step_id,
                           "cumulative_pct": int(cumulative), "weight_pct": int(weight),
                           "overall_pct": float(overall)})
        elif line.startswith("substep "):
            message, overall = shlex.split(line)[1:]
            events.append({"type": "substep", "message": message,
                           "overall_pct": float(overall)})
        elif line.startswith("printf '{\"type\":\"complete\""):
            m = re.search(r'"overall_pct":(\d+)', line)
            events.append({"type": "complete", "message": "Installation complete!",
                           "overall_pct": float(m.group(1)) if m else None})
    return events


class ShimMatchesCurrentFisherman(unittest.TestCase):
    def setUp(self):
        self.events = shim_events()
        self.pp = _load(CANONICAL, "_pp_shim")

    def test_the_shim_was_parsed(self):
        kinds = [e["type"] for e in self.events]
        self.assertEqual(kinds.count("step"), 8)
        self.assertGreaterEqual(kinds.count("substep"), 3)
        self.assertEqual(kinds[-1], "complete")

    def test_every_event_carries_overall_pct(self):
        for e in self.events:
            self.assertIsInstance(e["overall_pct"], float, e)

    def test_overall_pct_is_the_bar_fisherman_computes(self):
        """With overall_pct stripped, the reference parser derives the bar
        that fisherman's Tracker (a port of it) emits for these events."""
        state = self.pp.new_progress_state()
        bar = 0.0
        for e in self.events:
            stripped = {k: v for k, v in e.items() if k not in ("overall_pct", "step_id")}
            update = self.pp.apply_progress_event(json.dumps(stripped), state)
            if update and update.get("fraction") is not None:
                bar = update["fraction"]
            want = 99.0 if e["type"] != "complete" else 100.0
            with self.subTest(event=e):
                self.assertAlmostEqual(e["overall_pct"], round(min(bar * 100, want), 2), places=6)

    def test_overall_pct_never_decreases(self):
        values = [e["overall_pct"] for e in self.events]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[-1], 100.0)

    @unittest.skipUnless(os.path.isfile(FISHERMAN_BAR), "fisherman submodule not checked out")
    def test_step_ids_are_fishermans(self):
        ids = _fisherman_step_ids()
        for e in self.events:
            if e["type"] == "step":
                self.assertEqual(e["step_id"], ids[e["step_name"]], e["step_name"])


if __name__ == "__main__":
    unittest.main()


class TestShimReadsStdin(unittest.TestCase):
    """Every frontend pipes the recipe to `fisherman -`; the shim must keep
    what arrived on stdin and hand `validate --json --partial -` its stdin."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.real = os.path.join(self.tmp, "fisherman.real")
        with open(self.real, "w") as fh:
            # Stands in for the fisherman built from the submodule: records
            # its argv and stdin, and accepts everything.
            fh.write("#!/bin/sh\n"
                     f'echo "$@" >> {self.tmp}/real-argv\n'
                     f'if [ "$*" != "${{*%-}}" ]; then cat > {self.tmp}/real-stdin; fi\n'
                     f'if [ -f {self.tmp}/verdict ]; then cat {self.tmp}/verdict; exit 1; fi\n'
                     'case "$*" in *--json*) echo \'{"protocol_version":1,"valid":true,"errors":[]}\';; esac\n'
                     "exit 0\n")
        os.chmod(self.real, 0o755)
        # The install path needs root, as fisherman's does. This test runs
        # as the CI user, so it takes the one exemption the shim has.
        self.env = dict(os.environ, TUNA_E2E_REAL=self.real, TUNA_E2E_DIR=self.tmp,
                        TUNA_E2E_ALLOW_NONROOT="1")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_shim(self, args, stdin):
        import subprocess
        return subprocess.run(["bash", SHIM, *args], input=stdin, env=self.env,
                              capture_output=True, text=True, timeout=60, check=False)

    def test_dash_reads_the_recipe_from_stdin(self):
        recipe = json.dumps({"disk": "/dev/loop0", "hostname": "e2e", "image": "x"})
        out = self.run_shim(["-"], recipe)
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(os.path.join(self.tmp, "recipe.json")) as fh:
            self.assertEqual(fh.read(), recipe)
        self.assertIn("recipe received on stdin", out.stdout)
        self.assertIn('"type":"complete"', out.stdout)
        with open(os.path.join(self.tmp, "real-argv")) as fh:
            self.assertIn(f"validate --json {self.tmp}/recipe.json", fh.read())

    def _events(self, stdout):
        events = []
        for line in stdout.splitlines():
            if line.startswith("{"):
                events.append(json.loads(line))
        return events

    def test_a_rejected_recipe_ends_as_fishermans_install_does(self):
        """One error event with the first problem's code and field, exit 1,
        no step: fisherman/docs/JSON-PROGRESS-FORMAT.md, "error"."""
        with open(os.path.join(self.tmp, "verdict"), "w") as fh:
            json.dump({"protocol_version": 1, "valid": False, "errors": [
                {"field": "encrypton", "code": "recipe_unknown_field",
                 "message": "unknown recipe field \"encrypton\""},
                {"field": "hostname", "code": "hostname_required", "message": "hostname is required"},
            ]}, fh)
        out = self.run_shim(["-"], json.dumps({"disk": "/dev/loop0", "encrypton": {}}))
        self.assertEqual(out.returncode, 1, out.stderr)
        events = self._events(out.stdout)
        self.assertEqual([e["type"] for e in events], ["error"])
        self.assertEqual(events[0]["code"], "recipe_unknown_field")
        self.assertEqual(events[0]["field"], "encrypton")
        self.assertTrue(events[0]["message"].startswith("loading recipe: "))
        self.assertIn("hostname_required", out.stderr)

    def test_a_problem_that_is_not_about_the_recipe_file_is_invalid_recipe(self):
        with open(os.path.join(self.tmp, "verdict"), "w") as fh:
            json.dump({"protocol_version": 1, "valid": False, "errors": [
                {"field": "", "code": "firmware_not_uefi", "message": "not UEFI"}]}, fh)
        out = self.run_shim(["-"], json.dumps({"disk": "/dev/loop0"}))
        event = self._events(out.stdout)[0]
        self.assertEqual(out.returncode, 1)
        self.assertEqual(event["message"], "invalid recipe: not UEFI")
        self.assertNotIn("field", event)

    def test_a_run_that_is_not_root_is_refused_before_the_recipe_is_read(self):
        if os.geteuid() == 0:
            self.skipTest("this test runs as root, where the install is allowed")
        env = dict(self.env)
        del env["TUNA_E2E_ALLOW_NONROOT"]
        import subprocess
        out = subprocess.run(["bash", SHIM, "-"], input='{"disk":"/dev/loop0"}', env=env,
                             capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(out.returncode, 1)
        events = self._events(out.stdout)
        self.assertEqual([(e["type"], e["code"]) for e in events], [("error", "not_root")])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "recipe.json")))

    def test_the_stream_has_fishermans_info_lines(self):
        """`Desktop extras: …` after the recipe loads and the BootNext line
        before `complete`: info events of the real stream."""
        recipe = {"disk": "/dev/loop0", "hostname": "e2e", "image": "x",
                  "extras": {"printServices": True, "bootSplash": True}}
        events = self._events(self.run_shim(["-"], json.dumps(recipe)).stdout)
        infos = [e["message"] for e in events if e["type"] == "info"]
        self.assertEqual(infos[0], "Desktop extras: printServices, bootSplash (from the recipe)")
        self.assertTrue(infos[-1].startswith("BootNext not set: this host is not live media"))
        self.assertEqual(events[-1]["type"], "complete")
        self.assertEqual(events[-2]["type"], "info")
        del recipe["extras"]
        events = self._events(self.run_shim(["-"], json.dumps(recipe)).stdout)
        self.assertTrue(events[0]["message"].startswith("Desktop extras: none (the recipe has no"))

    def test_empty_stdin_is_fishermans_error(self):
        out = self.run_shim(["-"], "")
        self.assertEqual(out.returncode, 1)
        self.assertIn("loading recipe: recipe is empty", out.stdout)

    def test_partial_validate_gets_its_stdin(self):
        out = self.run_shim(["validate", "--json", "--partial", "-"], '{"hostname":"-x"}')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('"valid":true', out.stdout)
        with open(os.path.join(self.tmp, "real-stdin")) as fh:
            self.assertEqual(fh.read(), '{"hostname":"-x"}')
