"""No workflow pushes to dev. Pictures reach dev through a pull request.

The screenshot workflows and walkthrough.yml used to commit their pictures
straight to dev with a deploy key (.github/actions/push-to-dev), past the
required checks. Now only _walkthrough.yml holds that key. It pushes a
`bot/walkthrough-<frontend>-<sha>` branch and opens a pull request, which
then needs the same checks as any other change (tools/walkthrough/README.md).
"""

import os
import re
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKFLOWS = os.path.join(REPO, ".github", "workflows")
KEY_HOLDER = "_walkthrough.yml"
CALLERS = {f"walkthrough-{fe}.yml" for fe in ("gnome", "kde", "cosmic", "niri", "xfce")}


def read(name):
    with open(os.path.join(WORKFLOWS, name), encoding="utf-8") as stream:
        return stream.read()


def workflows():
    return sorted(n for n in os.listdir(WORKFLOWS) if n.endswith((".yml", ".yaml")))


class NoDirectPushTest(unittest.TestCase):
    def test_the_push_to_dev_action_is_gone(self):
        self.assertFalse(os.path.exists(os.path.join(REPO, ".github", "actions", "push-to-dev")))
        for name in workflows():
            with self.subTest(workflow=name):
                self.assertNotIn("push-to-dev", read(name))

    def test_no_workflow_pushes_to_dev(self):
        for name in workflows():
            text = read(name)
            with self.subTest(workflow=name):
                self.assertIsNone(re.search(r"git push\b[^\n]*\bHEAD:(refs/heads/)?dev\b", text))
                self.assertIsNone(re.search(r"git push\b[^\n]*\borigin dev\b", text))

    def test_only_the_walkthrough_job_holds_the_deploy_key(self):
        holders = {n for n in workflows() if "DEV_PUSH_DEPLOY_KEY" in read(n)}
        self.assertEqual(holders, {KEY_HOLDER} | CALLERS)
        for name in CALLERS:
            with self.subTest(workflow=name):
                # A caller only passes the secret on to the reusable workflow.
                self.assertIn("uses: $/.github/workflows/_walkthrough.yml", read(name))

    def test_the_walkthrough_pushes_only_a_bot_branch_from_dev(self):
        text = read(KEY_HOLDER)
        pushes = re.findall(r'git push -q "\$remote" "([^"]+)"', text)
        self.assertTrue(pushes)
        for target in pushes:
            self.assertEqual(target, "HEAD:refs/heads/$branch")
        self.assertIn('branch="bot/walkthrough-$FE-${GITHUB_SHA::8}"', text)
        job = text.split("\n  pull-request:\n", 1)[1]
        self.assertIn("github.ref == 'refs/heads/dev' && github.event_name != 'pull_request'", job)
        # The walk job itself holds no secret.
        walk = text.split("\n  walk:\n", 1)[1].split("\n  pull-request:\n", 1)[0]
        self.assertNotIn("secrets.", walk)


if __name__ == "__main__":
    unittest.main()
