"""The bot commits to dev go through one action: .github/actions/push-to-dev.

Five screenshot workflows and walkthrough.yml each carried a copy of the
same commit, rebase and retry step. These tests keep the copies from coming
back, and hold the two properties that the release flow depends on: each
message has `[skip ci]` (promote.yml does not take such a commit as a
candidate, docs/RELEASE.md), and a frontend workflow adds paths in its own
tree.
"""

import os
import re
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKFLOWS = os.path.join(REPO, ".github", "workflows")
ACTION = os.path.join(REPO, ".github", "actions", "push-to-dev", "action.yml")
USE = re.compile(
    r"        uses: \./\.github/actions/push-to-dev\n"
    r"        with:\n"
    r"(?:          working-directory: (?P<wd>\S+)\n)?"
    r"          paths: (?P<paths>.+)\n"
    r"          message: \"(?P<message>.+)\"\n")
CALLERS = {
    "screenshots-gnome.yml": (None, "docs/screenshots", "docs(gnome): refresh GUI screenshots [skip ci]"),
    "screenshots-kde.yml": ("frontends/kde", "docs/screenshots", "docs(kde): refresh GUI screenshots [skip ci]"),
    "screenshots-cosmic.yml": ("frontends/cosmic", "docs/screenshots",
                               "docs(cosmic): refresh GUI screenshots [skip ci]"),
    "screenshots-niri.yml": ("frontends/niri", "docs/screenshots", "docs(niri): refresh GUI screenshots [skip ci]"),
    "screenshots-xfce.yml": ("frontends/xfce", "docs/screenshots", "docs(xfce): refresh GUI screenshots [skip ci]"),
    "walkthrough.yml": (None, "docs/walkthrough", "docs: refresh cross-frontend walkthrough [skip ci]"),
}


def read(path):
    with open(path, encoding="utf-8") as stream:
        return stream.read()


class PushToDevTest(unittest.TestCase):
    def test_the_action_keeps_the_retry_and_the_safe_directory(self):
        text = read(ACTION)
        self.assertIn('git config --global --add safe.directory "$GITHUB_WORKSPACE"', text)
        self.assertIn("for attempt in 1 2 3 4 5 6; do", text)
        self.assertIn("git rebase -q origin/dev", text)
        self.assertIn("git push origin HEAD:dev", text)
        self.assertIn("could not push after 6 attempts", text)
        # The inputs reach the script through the environment only.
        script = text.split("      run: |\n")[1]
        self.assertNotIn("${{", script)

    def test_no_workflow_pushes_to_dev_by_itself(self):
        for name in sorted(os.listdir(WORKFLOWS)):
            with self.subTest(workflow=name):
                self.assertNotIn("git push origin HEAD:dev", read(os.path.join(WORKFLOWS, name)))

    def test_each_caller_commits_its_own_paths_with_skip_ci(self):
        using = sorted(name for name in os.listdir(WORKFLOWS)
                       if "actions/push-to-dev" in read(os.path.join(WORKFLOWS, name)).split("\njobs:")[1])
        self.assertEqual(using, sorted(CALLERS))
        for name, expected in CALLERS.items():
            with self.subTest(workflow=name):
                text = read(os.path.join(WORKFLOWS, name))
                found = [(m["wd"], m["paths"], m["message"]) for m in USE.finditer(text)]
                self.assertEqual(found, [expected])
                # The job's run steps and the action must agree on the
                # directory, or `git add` names a path that is not there.
                default = re.search(r"^      run:\n        working-directory: (\S+)$", text, re.M)
                self.assertEqual(default.group(1) if default else None, expected[0])

    def test_a_screenshot_job_pushes_only_from_a_push_to_dev(self):
        for name in CALLERS:
            if not name.startswith("screenshots-"):
                continue
            with self.subTest(workflow=name):
                self.assertIn(
                    "        if: github.event_name == 'push' && github.ref == 'refs/heads/dev'\n"
                    "        uses: ./.github/actions/push-to-dev\n", read(os.path.join(WORKFLOWS, name)))


if __name__ == "__main__":
    unittest.main()
