"""The fisherman progress protocol: the Python parser and the fixtures.

shared/progress/ has the protocol and the case files. The Python parser is
bootc_shared.progress (shared/python/), which GNOME and XFCE both import.

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
CANONICAL = os.path.join(REPO, "shared", "python", "bootc_shared", "progress.py")
TRANSCRIPT = os.path.join(REPO, "shared", "progress", "dry-run-transcript.ndjson")

def _load(path, name):
    """A new instance of a bootc_shared module, so that a test which sets
    module state (the product label, a patched function) does not leak
    into another. The name keeps it inside the package for `from . import`."""
    import bootc_shared  # noqa: F401  (pytest.ini puts shared/python on the path)
    spec = importlib.util.spec_from_file_location("bootc_shared." + name.lstrip("_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


class OneTranscriptTest(unittest.TestCase):
    def test_the_package_points_at_the_shared_transcript(self):
        pp = _load(CANONICAL, "progress_transcript")
        self.assertEqual(os.path.realpath(pp.transcript_path()), os.path.realpath(TRANSCRIPT))


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


FRACTION_CASES = os.path.join(REPO, "shared", "progress", "fraction-cases.json")
GENERATOR = os.path.join(REPO, "shared", "progress", "generate-fraction-cases.py")


class FractionCasesTest(unittest.TestCase):
    """shared/progress/fraction-cases.json pins the bar position after every
    event. COSMIC, KDE and Niri test their own parsers against it, so it has
    to be exactly what the canonical parser produces -- and stay that way."""

    def test_fixture_is_what_the_canonical_parser_produces(self):
        gen = _load(GENERATOR, "_fraction_gen")
        with open(FRACTION_CASES, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(
            committed, json.loads(json.dumps(gen.build())),
            "fraction-cases.json is stale; run "
            "python3 shared/progress/generate-fraction-cases.py")

    def test_the_python_parser_reproduces_the_fixture(self):
        with open(FRACTION_CASES, encoding="utf-8") as fh:
            cases = json.load(fh)["cases"]
        self.assertGreaterEqual(len(cases), 5)
        for path in [CANONICAL]:
            pp = _load(path, "_pp_" + os.path.basename(os.path.dirname(path)))
            for case in cases:
                state, bar = pp.new_progress_state(), 0.0
                for i, (event, want) in enumerate(zip(case["events"], case["bar"])):
                    update = pp.apply_progress_event(json.dumps(event), state)
                    if update and update.get("fraction") is not None:
                        bar = update["fraction"]
                    with self.subTest(copy=os.path.relpath(path, REPO),
                                      case=case["name"], event=i):
                        self.assertAlmostEqual(bar, want, places=6)

    def test_offline_install_bar_moves_before_the_flatpak_copy(self):
        """#115: the silent export/deploy phases must move the bar."""
        with open(FRACTION_CASES, encoding="utf-8") as fh:
            case = next(c for c in json.load(fh)["cases"]
                        if c["name"] == "offline_install_moves_through_silent_phases")
        self.assertEqual(case["bar"], sorted(case["bar"]))
        self.assertGreater(case["bar"][-1], case["bar"][0] + 0.5)


OVERALL_CASES = os.path.join(REPO, "shared", "progress", "overall-pct-cases.json")


def _replay(pp, events):
    state, bar, out = pp.new_progress_state(), 0.0, []
    for event in events:
        update = pp.apply_progress_event(json.dumps(event), state)
        if update and update.get("fraction") is not None:
            bar = update["fraction"]
        out.append(bar)
    return out


class OverallPctCasesTest(unittest.TestCase):
    """shared/progress/overall-pct-cases.json: fisherman's overall_pct is the
    bar; without it the parser falls back to its own derivation. COSMIC, KDE
    and Niri replay the same file."""

    def setUp(self):
        with open(OVERALL_CASES, encoding="utf-8") as fh:
            self.cases = json.load(fh)["cases"]

    def test_fixture_is_what_the_canonical_parser_produces(self):
        gen = _load(GENERATOR, "_fraction_gen_overall")
        with open(OVERALL_CASES, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(
            committed, json.loads(json.dumps(gen.build_overall())),
            "overall-pct-cases.json is stale; run "
            "python3 shared/progress/generate-fraction-cases.py")

    def test_the_python_parser_reproduces_the_fixture(self):
        for path in [CANONICAL]:
            pp = _load(path, "_pp_overall_" + os.path.basename(os.path.dirname(path)))
            for case in self.cases:
                got = _replay(pp, case["events"])
                for i, (bar, want) in enumerate(zip(got, case["bar"])):
                    with self.subTest(copy=os.path.relpath(path, REPO),
                                      case=case["name"], event=i):
                        self.assertAlmostEqual(bar, want, places=6)

    def test_the_bar_follows_overall_pct_not_the_derivation(self):
        """Guards the guard: with overall_pct stripped, the derivation holds
        the bar through the Flatpak copy, so the fixture would catch a
        frontend that ignores the field."""
        pp = _load(CANONICAL, "_pp_overall_strip")
        case = next(c for c in self.cases if c["name"] == "overall_pct_drives_the_bar")
        stripped = [{k: v for k, v in e.items() if k != "overall_pct"}
                    for e in case["events"]]
        self.assertNotEqual([round(b, 6) for b in _replay(pp, stripped)], case["bar"])
        self.assertEqual(case["bar"],
                         [min(e["overall_pct"], 100) / 100 for e in case["events"]])


FISHERMAN_BAR = os.path.join(REPO, "fisherman", "fisherman", "internal",
                             "progress", "bar.go")
COPY_DEFAULTS = os.path.join(REPO, "shared", "branding", "copy-defaults.json")


def _fisherman_step_ids():
    """fisherman's step_name -> step_id table, parsed out of bar.go."""
    import re
    with open(FISHERMAN_BAR, encoding="utf-8") as fh:
        body = fh.read().split("var stepIDs = map[string]string{", 1)[1].split("}", 1)[0]
    return dict(re.findall(r'"([^"]+)":\s*"([a-z0-9_]+)"', body))


@unittest.skipUnless(os.path.isfile(FISHERMAN_BAR), "fisherman submodule not checked out")
class StepIdCopyTest(unittest.TestCase):
    """Every step_id fisherman emits has a step_<id> copy key, and the
    step-name table the parser falls back to says the same words."""

    def setUp(self):
        self.ids = _fisherman_step_ids()
        with open(COPY_DEFAULTS, encoding="utf-8") as fh:
            self.copy = json.load(fh)

    def test_the_table_parsed(self):
        self.assertGreaterEqual(len(self.ids), 12)
        self.assertEqual(self.ids["Installing OS"], "install_os")

    def test_every_step_id_has_a_copy_key_and_no_more(self):
        keys = {k for k in self.copy if k.startswith("step_")}
        self.assertEqual(keys, {"step_" + i for i in self.ids.values()})

    def test_the_fallback_table_says_what_the_copy_says(self):
        pp = _load(CANONICAL, "_pp_step_ids")
        self.assertEqual(set(pp._FRIENDLY_STEP_LABELS), set(self.ids))
        for name, step_id in self.ids.items():
            with self.subTest(step=name):
                self.assertEqual(
                    pp._FRIENDLY_STEP_LABELS[name].replace("{product}", "{name}"),
                    self.copy["step_" + step_id])


ERROR_CASES = os.path.join(REPO, "shared", "progress", "error-cases.json")


class ErrorCasesTest(unittest.TestCase):
    """shared/progress/error-cases.json pins what a parser keeps of the
    `error` event (the last one, as {message, code, field}). COSMIC, KDE and
    Niri test their own parsers against it."""

    def test_fixture_is_what_the_canonical_parser_produces(self):
        gen = _load(GENERATOR, "_fraction_gen_errors")
        with open(ERROR_CASES, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(
            committed, json.loads(json.dumps(gen.build_errors())),
            "error-cases.json is stale; run "
            "python3 shared/progress/generate-fraction-cases.py")

    def test_the_python_parser_reproduces_the_fixture(self):
        with open(ERROR_CASES, encoding="utf-8") as fh:
            cases = json.load(fh)["cases"]
        self.assertGreaterEqual(len(cases), 6)
        self.assertEqual({case["error"] is None for case in cases}, {True, False})
        pp = _load(CANONICAL, "_pp_errors")
        for case in cases:
            state, bar = pp.new_progress_state(), 0.0
            for i, (event, want) in enumerate(zip(case["events"], case["bar"])):
                update = pp.apply_progress_event(json.dumps(event), state)
                if update and update.get("fraction") is not None:
                    bar = update["fraction"]
                with self.subTest(case=case["name"], event=i):
                    self.assertAlmostEqual(bar, want, places=6)
            self.assertEqual(state["error"], case["error"], case["name"])


RECEIPT_CASES = os.path.join(REPO, "shared", "progress", "receipt-cases.json")
FISHERMAN_RECEIPTS = os.path.join(REPO, "fisherman", "fisherman", "internal", "progress",
                                  "testdata", "receipt-events.ndjson")


class ReceiptCasesTest(unittest.TestCase):
    """shared/progress/receipt-cases.json pins what a parser keeps of the
    `receipt` event (#269, tuna-os/fisherman#441) and the done page's
    lines. COSMIC, KDE and Niri test their own parsers against it."""

    def test_fixture_is_what_the_canonical_parser_produces(self):
        gen = _load(GENERATOR, "_fraction_gen_receipts")
        with open(RECEIPT_CASES, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(
            committed, json.loads(json.dumps(gen.build_receipts())),
            "receipt-cases.json is stale; run "
            "python3 shared/progress/generate-fraction-cases.py")

    def test_every_fisherman_line_is_a_case(self):
        if not os.path.exists(FISHERMAN_RECEIPTS):
            self.skipTest("fisherman submodule not checked out")
        with open(RECEIPT_CASES, encoding="utf-8") as fh:
            events = [e for c in json.load(fh)["cases"] for e in c["events"]]
        with open(FISHERMAN_RECEIPTS, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    self.assertIn(json.loads(line), events)

    def test_no_line_says_the_system_started(self):
        with open(os.path.join(REPO, "shared", "branding", "copy-defaults.json"),
                  encoding="utf-8") as fh:
            copy = json.load(fh)
        for key, line in copy.items():
            if key.startswith("done_receipt_") or key == "done_verification":
                self.assertNotRegex(line.lower(), r"\bverified\b|\bbooted\b", key)

    def test_the_python_parser_reproduces_the_fixture(self):
        with open(RECEIPT_CASES, encoding="utf-8") as fh:
            cases = json.load(fh)["cases"]
        self.assertGreaterEqual(len(cases), 15)
        pp = _load(CANONICAL, "_pp_receipts")
        from bootc_shared import completion
        for case in cases:
            state, bar = pp.new_progress_state(), 0.0
            for i, (event, want) in enumerate(zip(case["events"], case["bar"])):
                update = pp.apply_progress_event(json.dumps(event), state)
                if update and update.get("fraction") is not None:
                    bar = update["fraction"]
                with self.subTest(case=case["name"], event=i):
                    self.assertAlmostEqual(bar, want, places=6)
            self.assertEqual(state["receipt"], case["receipt"], case["name"])
            self.assertEqual([{"key": k, "value": v} for k, v in
                              completion.receipt_lines(state["receipt"])],
                             case["done_lines"], case["name"])


OUTCOME_CASES = os.path.join(REPO, "shared", "progress", "outcome-cases.json")


class OutcomeCasesTest(unittest.TestCase):
    """shared/progress/outcome-cases.json: the exit code decides how an
    install ended, never a `complete` event (#269). GNOME and XFCE call
    bootc_shared.progress.install_outcome; KDE, COSMIC and Niri test their
    own rule against the same file."""

    def test_fixture_is_what_the_canonical_rule_produces(self):
        gen = _load(GENERATOR, "_fraction_gen_outcomes")
        with open(OUTCOME_CASES, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(committed, json.loads(json.dumps(gen.build_outcomes())),
                         "outcome-cases.json is stale; run "
                         "python3 shared/progress/generate-fraction-cases.py")

    def test_the_python_rule_reproduces_the_fixture(self):
        with open(OUTCOME_CASES, encoding="utf-8") as fh:
            cases = json.load(fh)["cases"]
        self.assertEqual({c["outcome"] for c in cases}, {"succeeded", "cancelled", "failed"})
        pp = _load(CANONICAL, "_pp_outcomes")
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertEqual(pp.install_outcome(case["exit_code"], case["cancel_requested"]),
                                 case["outcome"])

    def test_a_complete_event_never_decides(self):
        with open(OUTCOME_CASES, encoding="utf-8") as fh:
            cases = {c["name"]: c for c in json.load(fh)["cases"]}
        self.assertEqual(cases["complete_then_a_non_zero_exit"]["outcome"], "failed")
        self.assertEqual(cases["complete_then_a_signal"]["outcome"], "failed")
        self.assertEqual(cases["exit_0_without_a_complete_event"]["outcome"], "succeeded")

    def test_the_python_frontends_call_the_shared_rule(self):
        for path in ("bootc_installer/views/progress.py",
                     "frontends/xfce/tuna_installer_xfce/app.py"):
            with open(os.path.join(REPO, path), encoding="utf-8") as fh:
                self.assertIn("install_outcome(", fh.read(), path)

    def test_after_a_confirmed_cancel_only_130_or_a_signal_is_the_cancel(self):
        # The decided rule (#267): fisherman failed before the cancel
        # reached it, so its own exit code stands.
        with open(OUTCOME_CASES, encoding="utf-8") as fh:
            cases = {c["name"]: c for c in json.load(fh)["cases"]}
        self.assertEqual(cases["exit_1_after_a_confirmed_cancel"]["outcome"], "failed")
        self.assertEqual(cases["a_failed_copy_after_a_confirmed_cancel"]["outcome"], "failed")
        self.assertEqual(cases["a_cancelled_copy"]["outcome"], "cancelled")
        self.assertEqual(cases["a_signal_after_a_confirmed_cancel"]["outcome"], "cancelled")


REUSE_CASES = os.path.join(REPO, "shared", "progress", "source-reuse-cases.json")
FISHERMAN_DOC = os.path.join(REPO, "fisherman", "docs", "JSON-PROGRESS-FORMAT.md")
FISHERMAN_REUSE_GO = os.path.join(REPO, "fisherman", "fisherman", "internal", "progress", "reuse.go")
FISHERMAN_REUSE_IMPL = os.path.join(REPO, "fisherman", "fisherman", "internal", "reuse", "reuse.go")
FISHERMAN_RECIPE_DIR = os.path.join(REPO, "fisherman", "fisherman", "internal", "recipe")
COPY_DEFAULTS = os.path.join(REPO, "shared", "branding", "copy-defaults.json")


class SourceReuseCasesTest(unittest.TestCase):
    """shared/progress/source-reuse-cases.json pins what a parser keeps of
    fisherman's `source_reuse` events (#267) and the progress page's lines.
    KDE, COSMIC and Niri test their own parsers against it."""

    def setUp(self):
        with open(REUSE_CASES, encoding="utf-8") as fh:
            self.cases = json.load(fh)["cases"]

    def test_fixture_is_what_the_canonical_parser_produces(self):
        gen = _load(GENERATOR, "_fraction_gen_reuse")
        with open(REUSE_CASES, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(committed, json.loads(json.dumps(gen.build_reuse())),
                         "source-reuse-cases.json is stale; run "
                         "python3 shared/progress/generate-fraction-cases.py")

    def test_the_documented_line_is_the_pinned_fisherman_doc(self):
        if not os.path.exists(FISHERMAN_DOC):
            self.skipTest("fisherman submodule not checked out")
        gen = _load(GENERATOR, "_fraction_gen_reuse_doc")
        with open(FISHERMAN_DOC, encoding="utf-8") as fh:
            self.assertIn(gen.REUSE_DOC_EXAMPLE + "\n", fh.read())
        self.assertEqual(self.cases[0]["events"], [json.loads(gen.REUSE_DOC_EXAMPLE)])

    def test_every_field_is_one_that_fisherman_writes(self):
        # The lines come from fisherman's fake host; a renamed Go field
        # would leave them behind. Only the edge cases add a bad value.
        if not os.path.exists(FISHERMAN_REUSE_GO):
            self.skipTest("fisherman submodule not checked out")
        import re
        with open(FISHERMAN_REUSE_GO, encoding="utf-8") as fh:
            tags = set(re.findall(r'json:"([a-z_]+)', fh.read()))
        tags |= {"timestamp", "elapsed_ms"}
        gen = _load(GENERATOR, "_fraction_gen_reuse_tags")
        for name, lines in gen.REUSE_LINES.items():
            for line in lines:
                event = json.loads(line)
                for key, value in event.items():
                    self.assertIn(key, tags, name)
                    if isinstance(value, dict):
                        self.assertLessEqual(set(value), tags, name)

    def test_every_failure_code_of_the_copy_has_a_line(self):
        # The codes that internal/reuse puts on a `failed` event, by the
        # name of their Go constant in internal/recipe.
        if not os.path.exists(FISHERMAN_REUSE_IMPL):
            self.skipTest("fisherman submodule not checked out")
        import glob
        import re
        consts = {}
        for path in glob.glob(os.path.join(FISHERMAN_RECIPE_DIR, "*.go")):
            with open(path, encoding="utf-8") as fh:
                consts.update(re.findall(r'(CodeSourceReuse\w+)\s*=\s*"(source_reuse_\w+)"', fh.read()))
        with open(FISHERMAN_REUSE_IMPL, encoding="utf-8") as fh:
            used = set(re.findall(r"fail\(recipe\.(CodeSourceReuse\w+)", fh.read()))
        self.assertGreaterEqual(len(used), 10)
        with open(COPY_DEFAULTS, encoding="utf-8") as fh:
            copy = json.load(fh)
        for const in used:
            code = consts[const]
            self.assertIn("progress_reuse_failed_" + code[len("source_reuse_"):], copy, code)
        self.assertIn("progress_reuse_failed_unknown", copy)

    def test_the_python_parser_reproduces_the_fixture(self):
        self.assertGreaterEqual(len(self.cases), 15)
        pp = _load(CANONICAL, "_pp_reuse")
        for case in self.cases:
            state, bar = pp.new_progress_state(), 0.0
            for i, (event, want) in enumerate(zip(case["events"], case["bar"])):
                update = pp.apply_progress_event(json.dumps(event), state)
                if update and update.get("fraction") is not None:
                    bar = update["fraction"]
                with self.subTest(case=case["name"], event=i):
                    self.assertAlmostEqual(bar, want, places=6)
            self.assertEqual(state["source_reuse"], case["source_reuse"], case["name"])
            self.assertEqual([{"key": k, "value": v} for k, v in
                              pp.source_reuse_lines(state["source_reuse"])],
                             case["lines"], case["name"])
            self.assertEqual(pp.copy_cancel(state), case["copy_cancel"], case["name"])

    def test_the_bar_does_not_move_during_the_copy(self):
        for case in self.cases:
            before = 0.0
            for event, bar in zip(case["events"], case["bar"]):
                if event.get("type") == "source_reuse":
                    with self.subTest(case=case["name"]):
                        self.assertEqual(bar, before)
                before = bar

    def test_every_line_key_is_in_the_copy(self):
        with open(COPY_DEFAULTS, encoding="utf-8") as fh:
            copy = json.load(fh)
        for case in self.cases:
            for line in case["lines"]:
                self.assertIn(line["key"], copy, case["name"])
                if line["value"]:
                    self.assertIn("{value}", copy[line["key"]], line["key"])

    def test_the_cases_cover_every_phase_and_a_cancelled_copy(self):
        phases = {e.get("phase") for c in self.cases for e in c["events"]
                  if e.get("type") == "source_reuse"}
        self.assertLessEqual({"planned", "copying", "verified", "failed", "released"}, phases)
        cancelled = {c["name"]: c for c in self.cases}["cancelled_copy"]
        self.assertEqual(cancelled["events"][-1]["message"], "installation cancelled (SIGTERM)")

    def test_the_python_frontends_render_the_lines(self):
        for paths in (("bootc_installer/views/progress.py",),
                      ("frontends/xfce/tuna_installer_xfce/pages.py",
                       "frontends/xfce/tuna_installer_xfce/app.py")):
            text = ""
            for path in paths:
                with open(os.path.join(REPO, path), encoding="utf-8") as fh:
                    text += fh.read()
            self.assertIn("source_reuse_text(", text, paths[0])
            self.assertIn("copy_cancel(", text, paths[0])
