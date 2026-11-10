"""A change in shared/ runs every frontend's own tests.

Each frontend has tests that read fixtures in shared/ (the catalog, the
account groups, the probe, the progress cases, the branding). The workflows
that run those tests each listed some of the shared directories and missed
others, so a fixture could change and only the GNOME suite would read it.
The rule is now uniform: each per-frontend test workflow runs on
`shared/**`.

The workflows keep their path filters. A workflow with no filter must be in
REQUIRED_CHECKS (tests/unit/test_promote_gate.py), and none of these is a
required check.
"""

import os
import unittest

import yaml

WORKFLOWS = os.path.join(os.path.dirname(__file__), "..", "..", ".github", "workflows")
# The workflows that run one frontend's tests or its capture harness.
PER_FRONTEND = [
    "screenshots-gnome.yml",
    "screenshots-kde.yml",
    "screenshots-cosmic.yml",
    "screenshots-niri.yml",
    "screenshots-xfce.yml",
    "ci-niri.yml",
    "cargo-test-cosmic.yml",
]


def triggers(name):
    with open(os.path.join(WORKFLOWS, name), encoding="utf-8") as stream:
        doc = yaml.safe_load(stream)
    return doc.get("on") or doc.get(True)  # PyYAML reads the key `on` as True


class SharedPathFilterTest(unittest.TestCase):
    def test_each_frontend_test_workflow_runs_on_a_change_in_shared(self):
        for name in PER_FRONTEND:
            for event in ("push", "pull_request"):
                with self.subTest(workflow=name, event=event):
                    paths = triggers(name)[event]["paths"]
                    self.assertIn("shared/**", paths)
                    # One rule, not a list of contract directories to forget.
                    self.assertEqual([p for p in paths if p.startswith("shared/")], ["shared/**"])
                    self.assertIn(f".github/workflows/{name}", paths)

    def test_a_pull_request_and_a_push_use_the_same_filter(self):
        for name in PER_FRONTEND:
            with self.subTest(workflow=name):
                on = triggers(name)
                self.assertEqual(on["push"]["paths"], on["pull_request"]["paths"])

    def test_the_xfce_suite_runs_when_one_of_its_tests_changes(self):
        # screenshots-xfce.yml is the workflow that runs frontends/xfce/tests.
        self.assertIn("frontends/xfce/tests/**", triggers("screenshots-xfce.yml")["push"]["paths"])


if __name__ == "__main__":
    unittest.main()
