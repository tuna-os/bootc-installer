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

from tuna_installer_xfce import app, core, pages  # noqa: E402


class _Leaf:
    """A catalog leaf as core.ImageLeaf resolves it: `filesystems` is what
    the user may pick, `filesystem` what is selected first."""

    def __init__(self, filesystem, filesystems=None, imgref="registry.example/os:1"):
        self.imgref = imgref
        self.filesystem = filesystem
        self.filesystems = list(filesystems or ([filesystem] if filesystem else []))
        self.composefs = False


class _Win:
    def __init__(self, leaf=None):
        self.leaf = leaf

    def refresh_nav(self):
        pass

    def selected_leaf(self):
        return self.leaf

    def layout_source(self):
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
    page = pages.SetupPage(_Win(_Leaf("btrfs", ["btrfs", "ext4"])))
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


def _offered(page):
    return [row[1] for row in page.fs_combo.get_model()]


def test_the_choices_are_the_images_own():
    page = pages.SetupPage(_Win(_Leaf("", ["btrfs", "ext4"])))
    page.on_enter()
    assert _offered(page) == ["btrfs", "ext4"]
    # No `filesystem`: the first of `filesystems` is selected.
    assert page.fs_combo.get_active_id() == "btrfs"


def test_one_filesystem_is_the_only_choice():
    page = pages.SetupPage(_Win(_Leaf("xfs")))
    page.on_enter()
    assert _offered(page) == ["xfs"]


def test_an_image_that_names_none_gets_the_frontends_list():
    page = pages.SetupPage(_Win(_Leaf("")))
    page.on_enter()
    assert _offered(page) == list(pages.FILESYSTEMS)
    assert page.fs_combo.get_active_id() == "xfs"


def test_a_different_image_does_not_keep_the_choice_made_before():
    win = _Win(_Leaf("btrfs", ["btrfs", "ext4"], imgref="registry.example/a:1"))
    page = pages.SetupPage(win)
    page.on_enter()
    page.fs_combo.set_active_id("ext4")
    assert page.default_filesystem("btrfs") == "ext4"
    win.leaf = _Leaf("xfs", imgref="registry.example/b:1")
    page.on_enter()
    assert _offered(page) == ["xfs"]
    assert page.default_filesystem("xfs") == "xfs"


def test_composefs_reaches_the_live_check():
    leaf = _Leaf("btrfs")
    leaf.composefs = True
    page = pages.SetupPage(_Win(leaf))
    assert page.partial_recipe()["composeFsBackend"] is True
    assert "composeFsBackend" not in pages.SetupPage(_Win(_Leaf("xfs"))).partial_recipe()


def test_install_this_system_takes_the_live_images_layout():
    """"Install this system" on composefs-native live media (tunaOS grouper):
    the operator recipe's ext4 is selected, not this frontend's xfs, and the
    live check sees composefs (#343)."""
    live = core.LiveSystem({"bootloader": "systemd", "composeFsBackend": True,
                            "filesystem": "ext4"})
    page = pages.SetupPage(_Win(live))
    page.on_enter()
    assert _offered(page) == ["ext4"]
    assert page.default_filesystem(live.filesystem) == "ext4"
    assert page.partial_recipe() == {"filesystem": "ext4", "encryption": {"type": "none"},
                                     "composeFsBackend": True}


def test_the_window_sends_the_live_layout_to_fisherman(monkeypatch, tmp_path):
    """The whole path: "install this system" selected, the operator recipe
    on disk, and the recipe the window builds for fisherman."""
    import json
    import types

    operator = tmp_path / "recipe.json"
    operator.write_text(json.dumps({"bootloader": "systemd", "composeFsBackend": True,
                                    "filesystem": "ext4"}))
    monkeypatch.setattr(core, "operator_recipe_path", lambda in_flatpak=None: str(operator))
    source = types.SimpleNamespace(selection=lambda: {"live": True})
    win = types.SimpleNamespace(pages={"source": source}, needs_user_creation=lambda: False,
                                refresh_nav=lambda: None)
    win.selected_leaf = lambda: app.InstallerWindow.selected_leaf(win)
    win.layout_source = lambda: app.InstallerWindow.layout_source(win)
    setup = pages.SetupPage(win)
    setup.on_enter()
    identity = types.SimpleNamespace(get_text=lambda: "")
    win.pages.update(
        setup=setup,
        destination=types.SimpleNamespace(selected_disk=lambda: {"path": "/dev/vda"}),
        identity=types.SimpleNamespace(hostname=identity, username=identity,
                                       fullname=identity, password=identity))
    recipe = app.InstallerWindow.build_recipe(win)
    assert recipe["image"] == ""
    assert (recipe["bootloader"], recipe["composeFsBackend"], recipe["filesystem"]) == (
        "systemd", True, "ext4")
