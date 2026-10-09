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
