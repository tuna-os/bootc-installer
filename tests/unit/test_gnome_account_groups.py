"""GNOME's groups for the first account are the shared ones.

shared/account/README.md is the contract and shared/account/groups.json the
data: the default list and the operator override, with cases. An installed
package cannot read shared/, so bootc_installer/utils/account.py holds the
list; this test keeps it equal to the shared file and runs each case
through GNOME's own code, the Processor included.
"""

import json
import os
import sys

import pytest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from bootc_shared import account  # noqa: E402
from bootc_installer.utils.processor import Processor  # noqa: E402

with open(os.path.join(REPO, "shared", "account", "groups.json"), encoding="utf-8") as _stream:
    CONTRACT = json.load(_stream)


def test_the_default_list_is_the_shared_list():
    assert account.DEFAULT_GROUPS == CONTRACT["default_groups"]
    assert "sudo" in account.DEFAULT_GROUPS  # the admin group of Debian and Ubuntu (#302)


def test_the_user_page_sends_the_shared_list():
    with open(os.path.join(REPO, "bootc_installer", "defaults", "user.py"), encoding="utf-8") as stream:
        source = stream.read()
    assert "from bootc_shared.account import DEFAULT_GROUPS as _DEFAULT_GROUPS" in source
    assert '"groups": list(_DEFAULT_GROUPS)' in source


@pytest.mark.parametrize("case", CONTRACT["cases"], ids=lambda case: case["name"])
def test_resolve_groups_follows_each_case(case):
    assert account.resolve_groups(case["operator_recipe"]) == case["groups"]


@pytest.mark.parametrize("case", CONTRACT["cases"], ids=lambda case: case["name"])
def test_the_recipe_has_the_groups_of_each_case(case):
    """The operator file is the system recipe (<etc>/bootc-installer/recipe.json)."""
    finals = [{
        "disk": {"auto": {"disk": "/dev/vda"}, "filesystem": "xfs"},
        "hostname": "host", "selected_image": "registry.example/os/a:1",
        "user": {"username": "alice", "fullname": "Alice", "password": "pw",
                 "groups": list(account.DEFAULT_GROUPS)},
    }]
    system = dict(case["operator_recipe"]) if isinstance(case["operator_recipe"], dict) else {}
    recipe = Processor.gen_install_recipe("", finals, system)
    assert recipe["user"]["groups"] == case["groups"]
