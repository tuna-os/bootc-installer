"""The first account's groups: shared/account/groups.json.

GNOME sent wheel plus four developer groups and honoured an operator
override; the other four sent only wheel, so an Ubuntu image (admin group
`sudo`) got an account with no admin rights (#302). The shared file is the
one list and the one override rule. Each frontend's own test reads the
`cases`; this one keeps the file consistent and GNOME inside it.
"""

import ast
import json
import os
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
GROUPS = os.path.join(REPO, "shared", "account", "groups.json")
GNOME_USER = os.path.join(REPO, "bootc_installer", "defaults", "user.py")


def _load():
    with open(GROUPS, encoding="utf-8") as stream:
        return json.load(stream)


def resolve_groups(contract, operator_recipe):
    """The reference for the override rule in shared/account/README.md."""
    node = operator_recipe
    for key in contract["override"]["key"]:
        if not isinstance(node, dict) or key not in node:
            return list(contract["default_groups"])
        node = node[key]
    if isinstance(node, list) and all(isinstance(group, str) for group in node):
        return list(node)
    return list(contract["default_groups"])


def _gnome_default_groups():
    with open(GNOME_USER, encoding="utf-8") as stream:
        tree = ast.parse(stream.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_DEFAULT_GROUPS"
                for target in node.targets):
            return ast.literal_eval(node.value)
    return None


class SharedGroups(unittest.TestCase):
    def test_default_list_has_both_admin_groups_first(self):
        groups = _load()["default_groups"]
        self.assertEqual(groups[:2], ["wheel", "sudo"])
        self.assertEqual(len(groups), len(set(groups)))
        for group in groups:
            # useradd --groups takes a comma-separated list.
            self.assertRegex(group, r"^[a-z_][a-z0-9_-]*$")

    def test_override_names_the_operator_recipe(self):
        override = _load()["override"]
        self.assertEqual(override["file"], "bootc-installer/recipe.json")
        self.assertEqual(override["key"], ["user", "groups"])

    def test_cases_follow_the_rule(self):
        contract = _load()
        self.assertGreaterEqual(len(contract["cases"]), 5)
        for case in contract["cases"]:
            self.assertEqual(resolve_groups(contract, case["operator_recipe"]),
                             case["groups"], case["name"])

    def test_cases_cover_default_replace_and_empty(self):
        contract = _load()
        results = [case["groups"] for case in contract["cases"]]
        self.assertIn(contract["default_groups"], results)
        self.assertIn([], results)
        self.assertTrue(any(result and result != contract["default_groups"] for result in results))

    def test_gnome_list_is_inside_the_shared_one(self):
        gnome = _gnome_default_groups()
        if gnome is None:
            # GNOME reads groups.json now; there is no literal left to drift.
            with open(GNOME_USER, encoding="utf-8") as stream:
                self.assertIn("groups.json", stream.read(),
                              "GNOME has neither a group list nor a read of the shared one")
            return
        shared = _load()["default_groups"]
        self.assertTrue(set(gnome) <= set(shared), set(gnome) - set(shared))
        # The shared order keeps GNOME's order.
        self.assertEqual([group for group in shared if group in gnome], gnome)


if __name__ == "__main__":
    unittest.main()
