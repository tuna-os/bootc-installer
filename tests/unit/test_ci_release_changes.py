"""shared/ci/release_changes.py: which frontends a release run publishes.

Issue #319: release.yml compared against the latest GitHub release, which
the run creates before its publish jobs start. A failed publish in run N
therefore left run N+1 with no diff, and the frontend stayed stale until
its files changed again. The baseline is now, per frontend, the commit of
the newest earlier run whose publish jobs for that frontend all succeeded.
The job names below are the real ones from a release run.
"""

import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "shared", "ci"))
import release_changes as rc  # noqa: E402

A, B, C, D = "a" * 40, "b" * 40, "c" * 40, "d" * 40   # prod history, oldest first
ORDER = [A, B, C, D]
FOREIGN = "f" * 40
ALL = rc.FRONTENDS


def is_ancestor(a, b):
    return a in ORDER and b in ORDER and ORDER.index(a) <= ORDER.index(b)


def jobs(ok=(), failed=(), skipped=(), cancelled=(), running=()):
    out = [{"name": "Guard", "status": "completed", "conclusion": "success"},
           {"name": "Cut release", "status": "completed", "conclusion": "success"}]
    for name in ok:
        for leg in ("Build OCI (x86_64)", "Build OCI (aarch64)", "Publish"):
            out.append({"name": f"Publish ({name}) / publish / {leg}",
                        "status": "completed", "conclusion": "success"})
    for name, conclusion in [(n, "failure") for n in failed] + [(n, "cancelled") for n in cancelled]:
        for leg in ("Build OCI (x86_64)", "Build OCI (aarch64)"):
            out.append({"name": f"Publish ({name}) / publish / {leg}",
                        "status": "completed", "conclusion": "success"})
        out.append({"name": f"Publish ({name}) / publish / Publish",
                    "status": "completed", "conclusion": conclusion})
    for name in skipped:
        out.append({"name": f"Publish ({name})", "status": "completed", "conclusion": "skipped"})
    for name in running:
        out.append({"name": f"Publish ({name}) / publish / Build OCI (x86_64)",
                    "status": "in_progress", "conclusion": None})
    return out


def run(run_id, sha, status="completed"):
    return {"id": run_id, "head_sha": sha, "status": status}


def verdict(runs, job_map, changes, head=D, current=None):
    found = rc.baselines(runs, lambda run_id: job_map[run_id], is_ancestor, head, current)
    decided = rc.decide(found, lambda sha: changes.get((sha, head), []), head)
    return {name: decided[name][0] for name in ALL}, found


class TheBugInIssue319(unittest.TestCase):
    def test_a_failed_publish_is_retried_by_the_next_run_with_no_new_change(self):
        # Run 1 (A) published everything. Run 2 (C) carried a kde change and
        # its kde publish failed. Run 3 (D) has no kde change since C.
        runs = [run(2, C), run(1, A)]
        job_map = {2: jobs(failed=["kde"], skipped=["gnome", "cosmic", "niri", "xfce"]),
                   1: jobs(ok=ALL)}
        changes = {(A, D): ["frontends/kde/src/recipe.cpp", "docs/RELEASE.md"]}
        publish, found = verdict(runs, job_map, changes)
        self.assertEqual(found["kde"], A, "the failed run must not become the baseline")
        self.assertTrue(publish["kde"])
        self.assertEqual({n: publish[n] for n in ALL if n != "kde"},
                         {"gnome": False, "cosmic": False, "niri": False, "xfce": False})

    def test_the_old_rule_would_have_skipped_it(self):
        # The diff the old code took: latest release (C) to HEAD (D).
        self.assertEqual(rc.pf.touches("kde", ["docs/RELEASE.md"]), [])

    def test_every_publish_failed_then_every_frontend_is_retried(self):
        # #279: all five stale after one failed run.
        runs = [run(2, C), run(1, A)]
        job_map = {2: jobs(failed=ALL), 1: jobs(ok=ALL)}
        changes = {(A, D): ["bootc_installer/main.py"] + [f"frontends/{n}/x" for n in ALL[1:]]}
        publish, _ = verdict(runs, job_map, changes)
        self.assertEqual(set(publish.values()), {True})


class Baselines(unittest.TestCase):
    def test_baseline_is_per_frontend(self):
        runs = [run(3, C), run(2, B), run(1, A)]
        job_map = {3: jobs(ok=["gnome"], failed=["kde"], skipped=["cosmic", "niri", "xfce"]),
                   2: jobs(ok=["kde", "cosmic"], skipped=["gnome", "niri", "xfce"]),
                   1: jobs(ok=ALL)}
        found = rc.baselines(runs, lambda i: job_map[i], is_ancestor, D)
        self.assertEqual(found, {"gnome": C, "kde": B, "cosmic": B, "niri": A, "xfce": A})

    def test_skipped_cancelled_and_unfinished_publishes_are_not_baselines(self):
        for bad in (jobs(skipped=["kde"]), jobs(cancelled=["kde"]), jobs(running=["kde"]), jobs()):
            self.assertFalse(rc.published("kde", bad))
        self.assertTrue(rc.published("kde", jobs(ok=["kde"])))
        # One frontend's name must not match another's jobs.
        self.assertFalse(rc.published("kde", jobs(ok=["gnome", "cosmic", "niri", "xfce"])))

    def test_this_run_and_unfinished_runs_are_ignored(self):
        runs = [run(9, D), run(8, C, status="in_progress"), run(1, A)]
        job_map = {9: jobs(ok=ALL), 8: jobs(ok=ALL), 1: jobs(ok=ALL)}
        found = rc.baselines(runs, lambda i: job_map[i], is_ancestor, D, current_run_id="9")
        self.assertEqual(set(found.values()), {A})

    def test_a_run_for_a_commit_outside_this_history_is_ignored(self):
        runs = [run(2, FOREIGN), run(1, A)]
        job_map = {2: jobs(ok=ALL), 1: jobs(ok=ALL)}
        found = rc.baselines(runs, lambda i: job_map[i], is_ancestor, D)
        self.assertEqual(set(found.values()), {A})

    def test_lookback_bounds_the_api_calls(self):
        calls = []

        def jobs_of(run_id):
            calls.append(run_id)
            return jobs(failed=ALL)

        runs = [run(i, A) for i in range(100, 0, -1)]
        found = rc.baselines(runs, jobs_of, is_ancestor, D, lookback=5)
        self.assertEqual(len(calls), 5)
        self.assertEqual(set(found.values()), {None})

    def test_the_search_stops_when_every_frontend_has_a_baseline(self):
        calls = []

        def jobs_of(run_id):
            calls.append(run_id)
            return jobs(ok=ALL)

        rc.baselines([run(3, C), run(2, B), run(1, A)], jobs_of, is_ancestor, D)
        self.assertEqual(calls, [3])


class Decide(unittest.TestCase):
    def test_no_baseline_publishes(self):
        decided = rc.decide({n: None for n in ALL}, lambda sha: [], D)
        self.assertTrue(all(publish for publish, _ in decided.values()))

    def test_baseline_at_head_does_not_republish(self):
        decided = rc.decide({n: D for n in ALL}, lambda sha: self.fail("no diff needed"), D)
        self.assertFalse(any(publish for publish, _ in decided.values()))

    def test_path_rule_is_the_shared_one(self):
        changed = ["shared/catalog/README.md", "frontends/niri/ui/installer.qml", "docs/PARITY.md"]
        decided = rc.decide({n: A for n in ALL}, lambda sha: changed, D)
        self.assertEqual({n: decided[n][0] for n in ALL},
                         {"gnome": True, "kde": False, "cosmic": False, "niri": True, "xfce": False})

    def test_outputs_are_one_line_per_frontend(self):
        text = rc.render_outputs(rc.publish_everything("x"))
        self.assertEqual(text, "".join(f"{n}=true\n" for n in ALL))


class Main(unittest.TestCase):
    def test_unreadable_history_publishes_everything(self):
        saved = rc.gh_runs
        rc.gh_runs = lambda repo: (_ for _ in ()).throw(RuntimeError("api down"))
        out = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"rc-out-{os.getpid()}")
        try:
            self.assertEqual(rc.main(["--git-dir", REPO, "--github-output", out]), 0)
            with open(out, encoding="utf-8") as stream:
                self.assertEqual(stream.read(), "".join(f"{n}=true\n" for n in ALL))
        finally:
            rc.gh_runs = saved
            if os.path.exists(out):
                os.remove(out)


class WorkflowUsesTheScript(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(REPO, ".github", "workflows", "release.yml"), encoding="utf-8") as f:
            self.text = f.read()

    def test_release_yml_calls_the_script_and_not_the_latest_release(self):
        guard = self.text.split("\n  build:")[0]
        self.assertIn("shared/ci/release_changes.py", guard)
        self.assertNotIn("gh release list", guard,
                         "the latest release is created before the publish jobs: not a baseline")
        self.assertIn("actions: read", self.text)

    def test_every_frontend_has_an_output_and_a_gated_publish_job(self):
        for name in ALL:
            self.assertIn(f"{name}: ${{{{ steps.changes.outputs.{name} }}}}", self.text)
            self.assertRegex(self.text, rf"publish-{name}:\n    name: Publish \({name}\)\n"
                                        rf"    needs: \[guard, release\]\n"
                                        rf"    if: needs\.guard\.outputs\.{name} == 'true'")

    def test_job_names_match_what_the_script_reads(self):
        # published() keys on "Publish (<name>) / "; a renamed job would make
        # every run look unpublished (safe, but every release would publish
        # everything, and nobody would know why).
        names = re.findall(r"^    name: (Publish \(\w+\))$", self.text, re.M)
        self.assertEqual(names, [f"Publish ({n})" for n in ALL])


if __name__ == "__main__":
    unittest.main()
