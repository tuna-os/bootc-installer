"""Unit tests for image.py helpers — no GTK required."""
import importlib
import json
import os
import sys
import types
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Stub out gi.repository so image.py can be imported without a display.
for _mod in ("gi", "gi.repository", "gi.repository.Adw", "gi.repository.Gdk",
             "gi.repository.Gio", "gi.repository.GLib", "gi.repository.Gtk"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# Patch Gio.resources_lookup_data so _load_manifest() uses our fixture manifest.
_FIXTURE_MANIFEST = {
    "fallback_flatpaks": ["org.mozilla.firefox"],
    "default_image": "",
    "images": [
        {
            "name": "Aurora",
            "icon": "resource:///org/bootcinstaller/Installer/images/aurora.svg",
            "children": [
                {
                    "name": "Stable",
                    "imgref": "ghcr.io/ublue-os/aurora:stable",
                    "desc": "Stable build",
                },
                {
                    "name": "Aurora DX",
                    "children": [
                        {
                            "name": "Stable",
                            "imgref": "ghcr.io/ublue-os/aurora-dx:stable",
                            "desc": "DX stable",
                        },
                    ],
                },
            ],
        },
        {
            "name": "Bluefin",
            "icon": "resource:///org/bootcinstaller/Installer/images/bluefin.png",
            "children": [
                {
                    "name": "Latest",
                    "imgref": "ghcr.io/ublue-os/bluefin:latest",
                    "icon": "resource:///org/bootcinstaller/Installer/images/bluefin-lts.png",
                },
            ],
        },
        {
            "name": "NoIcon",
            "children": [
                {
                    "name": "Leaf",
                    "imgref": "ghcr.io/example/noicon:latest",
                },
            ],
        },
    ],
}


_mock_gio_data = MagicMock()
_mock_gio_data.get_data.return_value = json.dumps(_FIXTURE_MANIFEST).encode()
sys.modules["gi.repository"].Gio.resources_lookup_data.return_value = _mock_gio_data
sys.modules["gi.repository"].Gio.ResourceLookupFlags.NONE = 0


def _build_gi_stubs():
    gi_mod = types.ModuleType("gi")
    repo_mod = types.ModuleType("gi.repository")

    class _Template:
        def __call__(self, *args, **kwargs):
            return lambda cls: cls

        def Child(self, *args, **kwargs):
            return None

    class _Stub:
        pass

    template = _Template()
    stubs = {}
    for lib in ("Gtk", "Adw", "Gio"):
        stub = types.ModuleType(f"gi.repository.{lib}")
        stub.Template = template
        stub.Bin = _Stub
        setattr(repo_mod, lib, stub)
        sys.modules[f"gi.repository.{lib}"] = stub
        stubs[lib] = stub

    stubs["Gtk"].Image = _Stub
    stubs["Gtk"].CheckButton = _Stub
    stubs["Gtk"].SelectionMode = type("SelectionMode", (), {"NONE": 0})
    stubs["Adw"].ActionRow = _Stub
    stubs["Adw"].ExpanderRow = _Stub

    class _ResourceLookupFlags:
        NONE = 0

    data = MagicMock()
    data.get_data.return_value = json.dumps(_FIXTURE_MANIFEST).encode()
    stubs["Gio"].ResourceLookupFlags = _ResourceLookupFlags
    stubs["Gio"].resources_lookup_data = MagicMock(return_value=data)

    gi_mod.repository = repo_mod
    gi_mod.require_version = lambda *args, **kwargs: None
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repo_mod



def _import_image_fresh():
    _build_gi_stubs()
    sys.modules.pop("bootc_installer.defaults.image", None)
    try:
        import bootc_installer.defaults as defaults_pkg

        defaults_pkg.__dict__.pop("image", None)
    except Exception:
        pass
    return importlib.import_module("bootc_installer.defaults.image")


import bootc_installer.defaults.image as image_mod  # noqa: E402
from bootc_installer.defaults.image import (  # noqa: E402
    _count_leaves,
    _find_icon_for_imgref,
    _imgref_to_pretty_name,
    _load_manifest,
    _make_icon,
    _resolve_aliases,
)


class TestFindIconForImgref(unittest.TestCase):

    def test_direct_child_inherits_parent_icon(self):
        icon = _find_icon_for_imgref("ghcr.io/ublue-os/aurora:stable")
        self.assertEqual(icon, "resource:///org/bootcinstaller/Installer/images/aurora.svg")

    def test_nested_child_inherits_grandparent_icon(self):
        icon = _find_icon_for_imgref("ghcr.io/ublue-os/aurora-dx:stable")
        self.assertEqual(icon, "resource:///org/bootcinstaller/Installer/images/aurora.svg")

    def test_leaf_with_own_icon_overrides_parent(self):
        # Bluefin:latest has its own icon (bluefin-lts.png) which overrides parent's
        icon = _find_icon_for_imgref("ghcr.io/ublue-os/bluefin:latest")
        self.assertEqual(icon, "resource:///org/bootcinstaller/Installer/images/bluefin-lts.png")

    def test_missing_imgref_returns_none(self):
        icon = _find_icon_for_imgref("ghcr.io/does/not/exist:latest")
        self.assertIsNone(icon)

    def test_empty_imgref_returns_none(self):
        icon = _find_icon_for_imgref("")
        self.assertIsNone(icon)

    def test_node_with_no_icon_returns_none(self):
        icon = _find_icon_for_imgref("ghcr.io/example/noicon:latest")
        self.assertIsNone(icon)


class TestDistroInfoDefaultImageIcon(unittest.TestCase):
    """Verify the distro_info pattern used by builder.py."""

    def test_no_default_image_gives_none_icon(self):
        icon = _find_icon_for_imgref("")
        self.assertIsNone(icon)

    def test_default_image_with_icon_resolves(self):
        icon = _find_icon_for_imgref("ghcr.io/ublue-os/aurora:stable")
        self.assertIsNotNone(icon)
        self.assertTrue(icon.startswith("resource://"))


class TestResolveAliases(unittest.TestCase):
    """Unit tests for the @alias resolution helper."""

    def test_string_value_replaced(self):
        aliases = {"brew_url": "https://example.com/flatpaks.Brewfile"}
        manifest = {"images": [{"name": "Foo", "flatpaks": "@brew_url"}]}
        _resolve_aliases(manifest, aliases)
        self.assertEqual(manifest["images"][0]["flatpaks"], "https://example.com/flatpaks.Brewfile")

    def test_list_value_replaced(self):
        aliases = {"foo": "bar"}
        obj = ["@foo", "baz", "@foo"]
        _resolve_aliases(obj, aliases)
        self.assertEqual(obj, ["bar", "baz", "bar"])

    def test_non_alias_string_left_unchanged(self):
        aliases = {"foo": "bar"}
        manifest = {"name": "NoAlias", "flatpaks": "https://example.com/file"}
        _resolve_aliases(manifest, aliases)
        self.assertEqual(manifest["flatpaks"], "https://example.com/file")

    def test_unknown_alias_left_as_is(self):
        aliases = {"known": "value"}
        manifest = {"key": "@unknown"}
        _resolve_aliases(manifest, aliases)
        self.assertEqual(manifest["key"], "@unknown")

    def test_nested_dict_resolved(self):
        aliases = {"url": "https://host/path"}
        manifest = {"a": {"b": {"flatpaks": "@url"}}}
        _resolve_aliases(manifest, aliases)
        self.assertEqual(manifest["a"]["b"]["flatpaks"], "https://host/path")

    def test_empty_aliases_no_change(self):
        aliases = {}
        manifest = {"key": "@something"}
        _resolve_aliases(manifest, aliases)
        self.assertEqual(manifest["key"], "@something")


class TestPrettyNameHelpers(unittest.TestCase):

    def test_imgref_to_pretty_name_hyphenated_slug(self):
        self.assertEqual(
            _imgref_to_pretty_name("ghcr.io/ublue-os/bluefin-dx:latest"),
            "Bluefin DX",
        )

    def test_imgref_to_pretty_name_single_word(self):
        self.assertEqual(
            _imgref_to_pretty_name("ghcr.io/ublue-os/aurora:stable"),
            "Aurora",
        )

    def test_imgref_to_pretty_name_underscores_become_hyphens(self):
        self.assertEqual(
            _imgref_to_pretty_name("ghcr.io/example/bluefin_dx:latest"),
            "Bluefin DX",
        )

    def test_imgref_to_pretty_name_empty_string(self):
        self.assertEqual(_imgref_to_pretty_name(""), "")

    def test_imgref_to_pretty_name_invalid_imgref_returns_as_is(self):
        self.assertEqual(_imgref_to_pretty_name("bluefin"), "bluefin")


class TestCountLeaves(unittest.TestCase):

    def test_empty_list_has_no_leaves(self):
        self.assertEqual(_count_leaves([]), 0)

    def test_flat_list_counts_all_leaves(self):
        nodes = [
            {"name": "A", "imgref": "ghcr.io/example/a:latest"},
            {"name": "B", "imgref": "ghcr.io/example/b:latest"},
            {"name": "C", "imgref": "ghcr.io/example/c:latest"},
        ]
        self.assertEqual(_count_leaves(nodes), 3)

    def test_nested_groups_count_recursively(self):
        nodes = [
            {
                "name": "Group",
                "children": [
                    {"name": "A", "imgref": "ghcr.io/example/a:latest"},
                    {
                        "name": "Nested",
                        "children": [
                            {"name": "B", "imgref": "ghcr.io/example/b:latest"},
                            {"name": "C", "imgref": "ghcr.io/example/c:latest"},
                        ],
                    },
                ],
            },
        ]
        self.assertEqual(_count_leaves(nodes), 3)

    def test_mixed_groups_and_leaves(self):
        nodes = [
            {"name": "Top", "imgref": "ghcr.io/example/top:latest"},
            {
                "name": "Group",
                "children": [
                    {"name": "Child", "imgref": "ghcr.io/example/child:latest"},
                ],
            },
            {"name": "EmptyGroup", "children": []},
        ]
        self.assertEqual(_count_leaves(nodes), 2)


class TestNoFlatpakDownload(unittest.TestCase):
    """shared/catalog/README.md: a frontend does not download a Flatpak list.
    The page used to fetch and parse a Brewfile from a web server."""

    def test_the_module_has_no_network_code(self):
        self.assertFalse(hasattr(image_mod, "_fetch_remote_flatpak_list"))
        self.assertFalse(hasattr(image_mod, "urllib"))
        with open(image_mod.__file__, encoding="utf-8") as stream:
            source = stream.read()
        for word in ("urllib", "urlopen", "requests", "fallback_flatpaks"):
            self.assertNotIn(word, source)


class TestLoadManifestOverrides(unittest.TestCase):
    """The catalog files, in the contract's order: the system file, its
    legacy name, the per-user file, then the package's own catalog."""

    def setUp(self):
        self.mod = _import_image_fresh()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.system = os.path.join(root, "etc", "bootc-installer", "images.json")
        self.legacy = os.path.join(root, "etc", "tuna-installer", "images.json")
        self.user = os.path.join(root, "config", "bootc-installer", "images.json")
        patcher = patch.object(self.mod.catalog, "default_search_paths",
                               return_value=[self.system, self.legacy, self.user])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bundled = {"images": [{"imgref": "bundled"}]}
        data = MagicMock()
        data.get_data.return_value = json.dumps(self.bundled).encode()
        self.mod.Gio.resources_lookup_data = MagicMock(return_value=data)

    def _write(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(content if isinstance(content, str) else json.dumps(content))

    def test_the_system_file_wins_over_the_user_file(self):
        """#298: a file in a home directory must not replace the catalog an
        ISO ships. The user file used to be first."""
        self._write(self.system, {"images": [{"imgref": "system"}]})
        self._write(self.user, {"images": [{"imgref": "user"}]})
        self.assertEqual(self.mod._load_manifest()["images"], [{"imgref": "system"}])
        self.mod.Gio.resources_lookup_data.assert_not_called()

    def test_the_legacy_path_is_read(self):
        self._write(self.legacy, {"images": [{"imgref": "legacy"}]})
        self._write(self.user, {"images": [{"imgref": "user"}]})
        self.assertEqual(self.mod._load_manifest()["images"], [{"imgref": "legacy"}])

    def test_the_system_file_wins_over_the_legacy_file(self):
        self._write(self.system, {"images": [{"imgref": "system"}]})
        self._write(self.legacy, {"images": [{"imgref": "legacy"}]})
        self.assertEqual(self.mod._load_manifest()["images"], [{"imgref": "system"}])

    def test_the_user_file_is_used_when_there_is_no_system_file(self):
        self._write(self.user, {"images": [{"imgref": "user"}]})
        self.assertEqual(self.mod._load_manifest()["images"], [{"imgref": "user"}])
        self.mod.Gio.resources_lookup_data.assert_not_called()

    def test_a_file_that_does_not_parse_does_not_stop_the_search(self):
        self._write(self.system, "{not-json}")
        self._write(self.user, {"images": [{"imgref": "user"}]})
        self.assertEqual(self.mod._load_manifest()["images"], [{"imgref": "user"}])

    def test_a_file_that_is_not_a_catalog_does_not_stop_the_search(self):
        self._write(self.system, {"name": "no images list"})
        self._write(self.legacy, [1, 2])
        self.assertEqual(self.mod._load_manifest(), self.bundled)

    def test_the_bundled_catalog_is_used_when_no_file_is_there(self):
        self.assertEqual(self.mod._load_manifest(), self.bundled)

    def test_a_catalog_needs_no_fallback_flatpaks_key(self):
        self._write(self.system, {"images": []})
        self.assertEqual(self.mod._load_manifest(), {"images": []})

    def test_installed_path_when_the_gresource_fails(self):
        self.mod.Gio.resources_lookup_data = MagicMock(side_effect=Exception("gresource missing"))
        installed = {"images": [{"imgref": "installed"}]}

        def load(path):
            return installed if path == "/app/share/bootc-installer/images.json" else None

        with patch.object(self.mod.catalog, "load", side_effect=load):
            self.assertEqual(self.mod._load_manifest(), installed)

    def test_dev_path_when_the_gresource_and_installed_paths_fail(self):
        self.mod.Gio.resources_lookup_data = MagicMock(side_effect=Exception("gresource missing"))
        dev = {"images": [{"imgref": "dev"}]}

        def load(path):
            return dev if path.endswith("fisherman/data/images.json") else None

        with patch.object(self.mod.catalog, "load", side_effect=load):
            self.assertEqual(self.mod._load_manifest(), dev)

    def test_empty_catalog_when_all_sources_fail(self):
        self.mod.Gio.resources_lookup_data = MagicMock(side_effect=Exception("gresource missing"))
        with patch.object(self.mod.catalog, "load", return_value=None):
            self.assertEqual(self.mod._load_manifest(), {"images": []})


class TestMakeIcon(unittest.TestCase):

    def test_make_icon_returns_none_for_blank_spec(self):
        with patch.object(image_mod.Gtk, "Image", create=True) as image_cls:
            self.assertIsNone(_make_icon(""))
            image_cls.assert_not_called()

    def test_make_icon_loads_resource_icons(self):
        image = MagicMock()
        with patch.object(image_mod.Gtk, "Image", return_value=image, create=True):
            result = _make_icon("resource:///org/bootcinstaller/Installer/images/foo.svg", size=24)
        self.assertIs(result, image)
        image.set_pixel_size.assert_called_once_with(24)
        image.set_from_resource.assert_called_once_with("/org/bootcinstaller/Installer/images/foo.svg")

    def test_make_icon_loads_filesystem_icons(self):
        image = MagicMock()
        with patch.object(image_mod.Gtk, "Image", return_value=image, create=True):
            result = _make_icon("/usr/share/icons/foo.svg")
        self.assertIs(result, image)
        image.set_from_file.assert_called_once_with("/usr/share/icons/foo.svg")

    def test_make_icon_loads_icon_theme_names(self):
        image = MagicMock()
        with patch.object(image_mod.Gtk, "Image", return_value=image, create=True):
            result = _make_icon("computer-symbolic")
        self.assertIs(result, image)
        image.set_from_icon_name.assert_called_once_with("computer-symbolic")

    def test_make_icon_returns_none_when_loading_fails(self):
        image = MagicMock()
        image.set_from_resource.side_effect = RuntimeError("bad icon")
        with patch.object(image_mod.Gtk, "Image", return_value=image, create=True):
            self.assertIsNone(_make_icon("resource:///bad.svg"))


class TestBootcDefaultImagePureLogic(unittest.TestCase):

    def setUp(self):
        self.mod = _import_image_fresh()
        self.cls = self.mod.BootcDefaultImage

    def _leaf(self, **fields):
        node = {"name": "Example", "imgref": "ghcr.io/example/default:latest", **fields}
        return self.mod.catalog.leaves({"images": [node]})[0]

    def _make_widget(self):
        widget = object.__new__(self.cls)
        widget.row_custom = MagicMock()
        widget.image_url_entry = MagicMock()
        widget.btn_next = MagicMock()
        widget._BootcDefaultImage__update_btn_next = MagicMock()
        widget._BootcDefaultImage__radio_anchor = MagicMock()
        leaf = self._leaf(
            flatpaks=["org.default.App"], flatpak_var_path="/var/lib/flatpak",
            needs_user_creation=True, composefs=True, image_type="ostree",
            bootloader="grub2", filesystem="xfs", filesystems=["xfs", "btrfs"],
            default_hostname="example-host")
        widget._BootcDefaultImage__selected_leaf = leaf
        widget._BootcDefaultImage__selected_imgref = leaf["imgref"]
        widget._BootcDefaultImage__selected_carousel = ["slide1"]
        widget._BootcDefaultImage__selected_icon = "computer-symbolic"
        widget._BootcDefaultImage__selected_pretty_name = "Example"
        return widget

    def test_on_check_toggled_selects_the_leaf(self):
        widget = self._make_widget()
        check = MagicMock()
        check.get_active.return_value = True
        widget.row_custom.get_expanded.return_value = True
        leaf = self.mod.catalog.leaves({"images": [{
            "name": "New", "imgref": "ghcr.io/example/new:latest",
            "flatpaks": "https://example.test/flatpaks.txt",
            "needs_user_creation": False, "bootloader": "systemd",
            "filesystem": "btrfs", "flatpak_var_path": "/var/lib/custom-flatpak",
            "default_hostname": "new-host"}]})[0]

        self.cls._BootcDefaultImage__on_check_toggled(
            widget, check, leaf, "computer-symbolic", ["slide2"])

        self.assertEqual(widget._BootcDefaultImage__selected_imgref, "ghcr.io/example/new:latest")
        self.assertIs(widget._BootcDefaultImage__selected_leaf, leaf)
        self.assertEqual(widget._BootcDefaultImage__selected_pretty_name, "New")
        self.assertEqual(widget._BootcDefaultImage__selected_carousel, ["slide2"])
        widget.row_custom.set_expanded.assert_called_once_with(False)
        widget._BootcDefaultImage__update_btn_next.assert_called_once_with()

        widget.row_custom.get_expanded.return_value = False
        finals = self.cls.get_finals(widget)
        # A URL is not a list the installer can read offline: no key.
        self.assertNotIn("flatpaks", finals)
        self.assertFalse(finals["needs_user_creation"])
        self.assertEqual(finals["default_hostname"], "new-host")
        self.assertEqual(finals["supported_filesystems"], ["btrfs"])
        self.assertEqual(finals["image_filesystem"], "btrfs")

    def test_an_unchecked_row_changes_nothing(self):
        widget = self._make_widget()
        check = MagicMock()
        check.get_active.return_value = False
        before = widget._BootcDefaultImage__selected_leaf
        self.cls._BootcDefaultImage__on_check_toggled(widget, check, self._leaf(name="Other"))
        self.assertIs(widget._BootcDefaultImage__selected_leaf, before)

    def test_on_custom_toggled_resets_selection_for_custom_image(self):
        widget = self._make_widget()
        expander = MagicMock()
        expander.get_expanded.return_value = True

        self.cls._BootcDefaultImage__on_custom_toggled(widget, expander, None)

        widget._BootcDefaultImage__radio_anchor.set_active.assert_called_once_with(True)
        self.assertIsNone(widget._BootcDefaultImage__selected_imgref)
        self.assertIsNone(widget._BootcDefaultImage__selected_leaf)
        self.assertIsNone(widget._BootcDefaultImage__selected_icon)
        self.assertIsNone(widget._BootcDefaultImage__selected_carousel)
        self.assertIsNone(widget._BootcDefaultImage__selected_pretty_name)
        # An image that is not in the catalog gets an account (#288).
        self.assertTrue(self.cls.selected_needs_user_creation.fget(widget))
        widget._BootcDefaultImage__update_btn_next.assert_called_once_with()

    def test_needs_user_creation_follows_the_selected_leaf(self):
        widget = self._make_widget()
        widget._BootcDefaultImage__selected_leaf = self._leaf(needs_user_creation=False)
        self.assertFalse(self.cls.selected_needs_user_creation.fget(widget))
        widget._BootcDefaultImage__selected_leaf = self._leaf()
        self.assertTrue(self.cls.selected_needs_user_creation.fget(widget))

    def test_update_btn_next_uses_custom_url_validation(self):
        widget = self._make_widget()
        widget.row_custom.get_expanded.return_value = True
        widget.image_url_entry.get_text.return_value = "ghcr.io/example/custom:latest"

        self.cls._BootcDefaultImage__update_btn_next(widget)

        widget.btn_next.set_sensitive.assert_called_once_with(True)

    def test_on_url_changed_marks_invalid_custom_url(self):
        widget = self._make_widget()
        entry = MagicMock()
        entry.get_text.return_value = "not-a-valid-image"
        widget._BootcDefaultImage__update_btn_next = MagicMock()

        self.cls._BootcDefaultImage__on_url_changed(widget, entry)

        entry.add_css_class.assert_called_once_with("error")
        entry.remove_css_class.assert_not_called()
        widget._BootcDefaultImage__update_btn_next.assert_called_once_with()

    def test_should_show_skip_screen_and_leaf_count_helpers(self):
        widget = self._make_widget()
        self.assertFalse(self.cls.should_show(widget, {"leaf_count": 1}))
        self.assertTrue(self.cls.should_show(widget, {"leaf_count": 2}))
        self.assertEqual(self.cls.leaf_count.fget(widget), 4)
        self.assertFalse(self.cls.skip_screen.fget(widget))

    def test_get_finals_for_selected_catalog_image(self):
        widget = self._make_widget()
        widget.row_custom.get_expanded.return_value = False

        finals = self.cls.get_finals(widget)

        self.assertEqual(finals["selected_image"], "ghcr.io/example/default:latest")
        self.assertEqual(finals["pretty_name"], "Example")
        self.assertEqual(finals["flatpaks"], ["org.default.App"])
        self.assertEqual(finals["flatpak_var_path"], "/var/lib/flatpak")
        self.assertEqual(finals["carousel"], ["slide1"])
        self.assertTrue(finals["needs_user_creation"])
        self.assertTrue(finals["composefs_backend"])
        self.assertEqual(finals["image_type"], "ostree")
        self.assertEqual(finals["bootloader"], "grub2")
        # The leaf offers a choice of filesystems, so the image decides
        # nothing: the disk page starts at `default_filesystem`.
        self.assertEqual(finals["image_filesystem"], "")
        self.assertEqual(finals["default_filesystem"], "xfs")
        self.assertEqual(finals["icon"], "computer-symbolic")
        self.assertEqual(finals["default_hostname"], "example-host")
        self.assertEqual(finals["supported_filesystems"], ["xfs", "btrfs"])

    def test_get_finals_with_nothing_selected(self):
        widget = self._make_widget()
        widget.row_custom.get_expanded.return_value = False
        widget._BootcDefaultImage__selected_leaf = None
        finals = self.cls.get_finals(widget)
        self.assertIsNone(finals["selected_image"])
        self.assertNotIn("flatpaks", finals)
        self.assertTrue(finals["needs_user_creation"])

    def test_get_finals_for_custom_image(self):
        widget = self._make_widget()
        widget.row_custom.get_expanded.return_value = True
        widget.image_url_entry.get_text.return_value = "ghcr.io/example/custom-dx:stable"

        finals = self.cls.get_finals(widget)

        self.assertEqual(finals["custom_image"], "ghcr.io/example/custom-dx:stable")
        self.assertEqual(finals["pretty_name"], "Custom DX")
        # No list of the installer's own (it sent `fallback_flatpaks`), and
        # an account: the catalog does not have this image.
        self.assertNotIn("flatpaks", finals)
        self.assertIsNone(finals["carousel"])
        self.assertTrue(finals["needs_user_creation"])
        self.assertFalse(finals["composefs_backend"])
        self.assertEqual(finals["image_type"], "bootc")
        self.assertEqual(finals["bootloader"], "")
        self.assertEqual(finals["image_filesystem"], "")
        self.assertIsNone(finals["icon"])


class TestImagesCatalogIntegrity(unittest.TestCase):
    """Regression tests for fisherman/data/images.json content."""

    _CATALOG_PATH = os.path.join(
        os.path.dirname(__file__), "..", "..", "fisherman", "data", "images.json"
    )

    def _all_names_and_descs(self, node):
        """Yield every name/desc string in the tree recursively."""
        if isinstance(node, dict):
            if "name" in node:
                yield node["name"]
            if "desc" in node:
                yield node["desc"]
            if "subtitle" in node:
                yield node["subtitle"]
            if "title" in node:
                yield node["title"]
            for child in node.get("children", []):
                yield from self._all_names_and_descs(child)
        elif isinstance(node, list):
            for item in node:
                yield from self._all_names_and_descs(item)

    def _load_catalog(self):
        with open(self._CATALOG_PATH) as f:
            return json.load(f)

    def _all_imgrefs(self, nodes, registry_ctx=""):
        """Yield every effective imgref in the tree, resolving registry+tag nodes."""
        for n in nodes:
            registry = n.get("registry", registry_ctx)
            if "imgref" in n:
                yield n["imgref"]
            elif "tag" in n and registry:
                yield f"{registry}:{n['tag']}"
            yield from self._all_imgrefs(n.get("children", []), registry)

    def test_no_bare_ampersand_in_names(self):
        """Names must not contain bare & — it breaks Pango markup rendering."""
        catalog = self._load_catalog()
        bad = [s for s in self._all_names_and_descs(catalog) if "&" in s and "&amp;" not in s]
        self.assertEqual(bad, [], f"Bare & found in catalog strings: {bad}")

    def test_no_gaming_label_in_names(self):
        """GDX images are Nvidia+CUDA, not 'Gaming'."""
        catalog = self._load_catalog()
        bad = [s for s in self._all_names_and_descs(catalog) if "Gaming" in s]
        self.assertEqual(bad, [], f"'Gaming' label found (use Nvidia+CUDA): {bad}")

    def test_default_image_present_and_valid(self):
        """If default_image is set it must exist as a leaf in the tree.

        An absent or empty default_image is valid — the tree starts fully
        collapsed with nothing pre-selected (btn_next disabled until the
        user picks an image).  Distros can override via their own images.json.
        """
        catalog = self._load_catalog()
        default = catalog.get("default_image", "")
        if not default:
            return  # fully-collapsed mode — no default required

        found = list(self._all_imgrefs(catalog.get("images", [])))
        self.assertIn(default, found,
                      f"default_image {default!r} is not a leaf imgref in the tree")

    def test_aliases_resolve_without_unknown_refs(self):
        """Every @alias_name in the catalog must have a corresponding alias definition."""
        catalog = self._load_catalog()
        aliases = catalog.get("aliases", {})

        def _collect_alias_refs(obj):
            if isinstance(obj, dict):
                for key, val in obj.items():
                    if key == "aliases":
                        continue  # skip the definitions dict itself
                    yield from _collect_alias_refs(val)
            elif isinstance(obj, list):
                for item in obj:
                    yield from _collect_alias_refs(item)
            elif isinstance(obj, str) and obj.startswith("@"):
                yield obj[1:]

        unknown = [name for name in _collect_alias_refs(catalog) if name not in aliases]
        self.assertEqual(unknown, [], f"Unknown alias references in images.json: {unknown}")

    def test_registry_tag_nodes_produce_valid_imgrefs(self):
        """Every ``tag`` node must have a ``registry`` in scope (itself or ancestor)."""
        catalog = self._load_catalog()

        def _check(nodes, registry_ctx=""):
            for n in nodes:
                registry = n.get("registry", registry_ctx)
                if "tag" in n and "imgref" not in n:
                    self.assertTrue(
                        registry,
                        f"Node '{n.get('name')}' has 'tag' but no registry in scope"
                    )
                    imgref = f"{registry}:{n['tag']}"
                    self.assertIn(":", imgref,
                                  f"Composed imgref '{imgref}' missing colon")
                _check(n.get("children", []), registry)

        _check(catalog.get("images", []))


if __name__ == "__main__":
    unittest.main()



class TestCatalogPrettyName(unittest.TestCase):
    def test_catalog_name_precedes_source_family_slug(self):
        self.assertEqual(image_mod._catalog_pretty_name("  Example Remix  ", "localhost/base:latest"), "Example Remix")

    def test_absent_empty_and_invalid_names_fall_back(self):
        for name in (None, "", "   ", 42):
            with self.subTest(name=name):
                self.assertEqual(image_mod._catalog_pretty_name(name, "localhost/base:latest"), "Base")
