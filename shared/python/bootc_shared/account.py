"""The first account: its supplementary groups.

The contract is shared/account/README.md. The default list and the cases
are in shared/account/groups.json; this module reads the list from that
file, so a Python frontend has no literal to keep equal.
"""

import json

from . import _data


def default_groups():
    """`default_groups` of shared/account/groups.json.

    fisherman removes each group that the image does not have, so one list
    is correct for all images: `wheel` is the admin group of Fedora and its
    family, `sudo` that of Debian and Ubuntu.
    """
    return [group for group in _data.load_json("account/groups.json")["default_groups"]
            if isinstance(group, str)]


# Read one time, at import: a build that did not install the file fails
# when the frontend starts, not when the user reaches the account page.
# Copy it (list(DEFAULT_GROUPS)) before you change it.
DEFAULT_GROUPS = default_groups()


def resolve_groups(operator_recipe, default=None) -> list:
    """The groups of the first account.

    `operator_recipe` is <etc>/bootc-installer/recipe.json as an object, or
    None. When its `user.groups` is a list of strings, that list replaces
    the default, and [] means no supplementary group. Any other value, or
    no file, gives the default list (`default`, else DEFAULT_GROUPS).
    """
    user = operator_recipe.get("user") if isinstance(operator_recipe, dict) else None
    groups = user.get("groups") if isinstance(user, dict) else None
    if isinstance(groups, list) and all(isinstance(group, str) for group in groups):
        return list(groups)
    return list(DEFAULT_GROUPS if default is None else default)


def operator_recipe_path(in_flatpak) -> str:
    """The ISO builder's recipe.json: the host's /etc, also in a Flatpak."""
    etc = "/run/host/etc" if in_flatpak else "/etc"
    return f"{etc}/bootc-installer/recipe.json"


def read_operator_recipe(path):
    """The operator's recipe as an object, or None when there is no file
    that can be read as JSON."""
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return None
