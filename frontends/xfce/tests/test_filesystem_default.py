"""The catalog's default filesystem reaches the recipe.

The Advanced combo was created with "xfs" active and default_filesystem()
returned `get_active_id() or leaf_default`, so the active id always won and
an image whose catalog entry says btrfs was installed on xfs. The combo now
follows the catalog default until the person picks something.
"""

import os
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import pages  # noqa: E402


class _Leaf:
    def __init__(self, filesystem):
        self.filesystem = filesystem


class _Win:
    def __init__(self, leaf=None):
        self.leaf = leaf

    def refresh_nav(self):
        pass

    def selected_leaf(self):
        return self.leaf


def test_catalog_default_applies_when_untouched():
    page = pages.SetupPage(_Win(_Leaf("btrfs")))
    assert page.default_filesystem("btrfs") == "btrfs"


def test_combo_shows_the_catalog_default_on_enter():
    page = pages.SetupPage(_Win(_Leaf("btrfs")))
    page.on_enter()
    assert page.fs_combo.get_active_id() == "btrfs"
    # Showing it is not choosing it: a different image still wins.
    assert page.default_filesystem("ext4") == "ext4"


def test_the_persons_choice_wins():
    page = pages.SetupPage(_Win(_Leaf("btrfs")))
    page.on_enter()
    page.fs_combo.set_active_id("ext4")
    assert page.default_filesystem("btrfs") == "ext4"
    # Re-entering the page does not undo it.
    page.on_enter()
    assert page.fs_combo.get_active_id() == "ext4"


def test_no_catalog_default_falls_back_to_xfs():
    page = pages.SetupPage(_Win(None))
    page.on_enter()
    assert page.fs_combo.get_active_id() == "xfs"
    assert page.default_filesystem("") == "xfs"
