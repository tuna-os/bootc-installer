"""The first account: its supplementary groups.

The contract is shared/account/README.md, and shared/account/groups.json has
the list and the cases. An installed package cannot read shared/, so the
list is here too; tests/unit/test_gnome_account_groups.py holds the two
equal and runs each case of groups.json through resolve_groups().
"""

# fisherman removes each group that the image does not have, so one list is
# correct for all images: `wheel` is the admin group of Fedora and its
# family, `sudo` that of Debian and Ubuntu.
DEFAULT_GROUPS = ["wheel", "sudo", "docker", "incus-admin", "libvirt", "dialout"]


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
