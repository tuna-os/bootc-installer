"""Unit tests for views/confirm.py pure logic.

GTK is fully stubbed so BootcChoiceEntry / BootcConfirm can be imported
without a display.  BootcChoiceEntry is replaced with a MagicMock factory
after import so process_keyboards() and update() can execute.
"""

import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _build_gi_stubs():
    gi_mod = types.ModuleType("gi")
    repo_mod = types.ModuleType("gi.repository")

    class _Template:
        def __call__(self, *args, **kwargs):
            return lambda cls: cls

        def Child(self, *args, **kwargs):
            return MagicMock()

    class _StubBase:
        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    gtk_mod = types.ModuleType("gi.repository.Gtk")
    gtk_mod.Template = _Template()
    gtk_mod.Box = _StubBase
    # The hostname row's fisherman-validate message line.
    gtk_mod.Label = lambda *a, **kw: MagicMock()

    # FieldCheck schedules its checks with GLib; nothing runs them here.
    glib_mod = types.ModuleType("gi.repository.GLib")
    glib_mod.timeout_add = lambda ms, fn: 1
    glib_mod.source_remove = lambda source: None
    glib_mod.idle_add = lambda fn, *a: None

    adw_mod = types.ModuleType("gi.repository.Adw")
    adw_mod.Bin = _StubBase
    adw_mod.ActionRow = _StubBase
    adw_mod.ExpanderRow = _StubBase

    class _EntryRowStub(_StubBase):
        def __init__(self, *args, **kwargs):
            self._text = ""

        def set_text(self, t):
            self._text = t

        def get_text(self):
            return self._text

        def set_title(self, t):
            pass

        def set_show_apply_button(self, v):
            pass

        def connect(self, *a, **kw):
            return None

    adw_mod.EntryRow = _EntryRowStub

    gobject_mod = types.ModuleType("gi.repository.GObject")
    gobject_mod.Property = lambda *a, **kw: (lambda f: property(f))
    gobject_mod.SignalFlags = types.SimpleNamespace(RUN_FIRST=0)

    for name, mod in [
        ("Gtk", gtk_mod),
        ("Adw", adw_mod),
        ("GObject", gobject_mod),
        ("GLib", glib_mod),
    ]:
        setattr(repo_mod, name, mod)
        sys.modules[f"gi.repository.{name}"] = mod

    gi_mod.repository = repo_mod
    gi_mod.require_version = lambda *a, **kw: None
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repo_mod


_build_gi_stubs()

# Stub for core.system — NOT installed at module level to avoid contaminating
# test_system.py which imports the real bootc_installer.core.system.
# Tests that call update() install it via patch.dict in setUp().
_core_system_stub = types.ModuleType("bootc_installer.core.system")


class _Systeminfo:
    @staticmethod
    def gpu_display_string():
        return None  # No GPU — keeps tests deterministic.

    @staticmethod
    def gpu_icon_name():
        return "gpu-symbolic"


_core_system_stub.Systeminfo = _Systeminfo

# confirm.py only imports gi.repository at module load time (core.system is
# imported lazily inside update()).  So we can import it directly here.
import bootc_installer.views.confirm as confirm_mod  # noqa: E402

# Replace GTK-widget factories with simple MagicMock factories so
# process_keyboards() and update() can build active_widgets without GTK.
confirm_mod.BootcChoiceEntry = lambda title, subtitle, icon, **kw: MagicMock()
confirm_mod.BootcChoiceExpanderEntry = lambda title, subtitle, icon, **kw: MagicMock()


class TestKeyboardSummary(unittest.TestCase):
    """The Keyboard row is the recipe's `keyboard`: one XKB layout (#292)."""

    def test_layout_alone(self):
        self.assertEqual(confirm_mod.keyboard_summary({"layout": "us"}), "us")

    def test_layout_and_variant(self):
        self.assertEqual(confirm_mod.keyboard_summary(
            {"layout": "de", "variant": "nodeadkeys"}), "de+nodeadkeys")

    def test_no_selection_has_no_row(self):
        for value in (None, {}, {"variant": "intl"}, [{"layout": "us"}]):
            self.assertEqual(confirm_mod.keyboard_summary(value), "")


class TestSummaryHelpers(unittest.TestCase):
    def test_disk_summary_names_model_path_and_size(self):
        self.assertEqual(
            confirm_mod.disk_summary(
                {"disk": "/dev/sda", "pretty_size": "500 GB", "model": "Samsung SSD"}),
            "Samsung SSD (/dev/sda, 500 GB)")

    def test_disk_summary_without_model_shows_path(self):
        self.assertEqual(
            confirm_mod.disk_summary({"disk": "/dev/vda", "pretty_size": "20 GB"}),
            "/dev/vda (20 GB)")
        self.assertEqual(confirm_mod.disk_summary({"disk": "/dev/vda"}), "/dev/vda")

    def test_filesystem_label(self):
        self.assertEqual(confirm_mod.filesystem_label("xfs"), "XFS")
        self.assertEqual(confirm_mod.filesystem_label("btrfs"), "Btrfs")
        self.assertEqual(confirm_mod.filesystem_label("f2fs"), "f2fs")

    def test_recipe_image_follows_processor_order(self):
        self.assertEqual(confirm_mod.recipe_image({"imgref": "a", "images": [{"imgref": "b"}]}), "a")
        self.assertEqual(confirm_mod.recipe_image(
            {"images": [{"imgref": "b"}, {"imgref": "c", "default": True}]}), "c")
        self.assertEqual(confirm_mod.recipe_image({"images": [{"imgref": "b"}]}), "b")
        self.assertEqual(confirm_mod.recipe_image({}), "")


def _set_window(obj, recipe):
    """Give a __new__-built view the window update() reads the branding from.
    Set in the instance dict so it shadows whatever the GTK stubs put on the
    class."""
    window = MagicMock()
    window.recipe = recipe
    obj.__dict__["_BootcConfirm__window"] = window


class TestConfirmUpdate(unittest.TestCase):
    def setUp(self):
        # Install core.system stub only for the duration of this test so
        # that update()'s lazy `from bootc_installer.core.system import Systeminfo`
        # gets our no-GPU stub and not the real module.
        self._orig_core_system = sys.modules.get("bootc_installer.core.system")
        sys.modules["bootc_installer.core.system"] = _core_system_stub

    def tearDown(self):
        if self._orig_core_system is None:
            sys.modules.pop("bootc_installer.core.system", None)
        else:
            sys.modules["bootc_installer.core.system"] = self._orig_core_system

    def _make_obj(self):
        obj = confirm_mod.BootcConfirm.__new__(confirm_mod.BootcConfirm)
        obj.active_widgets = []
        obj.group_changes = MagicMock()
        obj.btn_confirm = MagicMock()
        obj.page_header = MagicMock()
        obj.row_warning = MagicMock()
        obj.group_warning = MagicMock()
        return obj

    def test_update_with_language_adds_widget(self):
        obj = self._make_obj()
        obj.update([{"language": "en_US.UTF-8"}])
        self.assertGreater(len(obj.active_widgets), 0)

    def test_update_with_timezone_adds_widget(self):
        obj = self._make_obj()
        obj.update([{"timezone": "America/New_York"}])
        self.assertGreater(len(obj.active_widgets), 0)

    def test_update_with_a_keyboard_adds_widget(self):
        obj = self._make_obj()
        obj.update([{"keyboard": {"layout": "de", "variant": "nodeadkeys"}}])
        self.assertGreater(len(obj.active_widgets), 0)

    def test_update_without_region_values_adds_no_region_rows(self):
        """A step with no selection sends no key: no row, as the recipe
        has no value."""
        obj = self._make_obj()
        obj.update([{}, {"keyboard": {}}, {"timezone": ""}, {"language": ""}])
        self.assertEqual(len(obj.active_widgets), 0)

    def test_update_with_users_adds_widget(self):
        obj = self._make_obj()
        # The user step emits `user` (defaults/user.py get_finals). This
        # test fed `users`, the key the view wrongly read (#313).
        obj.update([{"user": {"username": "jorge", "fullname": "Jorge Castro"}}])
        self.assertGreater(len(obj.active_widgets), 0)

    def test_update_without_an_account_adds_no_user_widget(self):
        obj = self._make_obj()
        obj.update([{"user": {"username": "", "fullname": "", "password": "", "groups": []}}])
        self.assertEqual(len(obj.active_widgets), 0)

    def test_update_with_disk_auto_adds_widget(self):
        obj = self._make_obj()
        obj.update([{"disk": {"auto": {"disk": "/dev/sda", "pretty_size": "100 GB"}}}])
        self.assertGreater(len(obj.active_widgets), 0)
    def test_update_with_disk_auto_warns_everything_erased_by_default(self):
        # #251: a non-removable (or unflagged) disk keeps the original,
        # unqualified erase warning.
        obj = self._make_obj()
        _set_window(obj, {})
        obj.update([{"disk": {"auto": {"disk": "/dev/sda", "pretty_size": "100 GB"}}}])
        obj.row_warning.set_title.assert_called_once()
        (warning,), _ = obj.row_warning.set_title.call_args
        self.assertIn("/dev/sda", warning)
        self.assertIn("erased", warning)
        self.assertNotIn("removable", warning)
        obj.group_warning.set_visible.assert_called_once_with(True)

    def test_update_with_removable_disk_warns_removable_drive(self):
        # #251: fisherman flags the auto disk "removable" (USB stick or
        # other external drive); the confirm page must say so, not just
        # "everything will be erased".
        obj = self._make_obj()
        _set_window(obj, {})
        obj.update([{"disk": {"auto": {
            "disk": "/dev/sdb", "pretty_size": "14.8 GiB", "removable": True,
        }}}])
        obj.row_warning.set_title.assert_called_once()
        (warning,), _ = obj.row_warning.set_title.call_args
        self.assertIn("/dev/sdb", warning)
        self.assertIn("removable", warning)

    def test_update_with_manual_partitioning_shows_no_erase_warning(self):
        # Manual partitioning may touch only part of a disk, so there is no
        # "erase_disk" and no row -- unchanged behaviour, guarded so the new
        # removable branch cannot start firing here by accident.
        obj = self._make_obj()
        _set_window(obj, {})
        obj.update([{"disk": {"/dev/sda1": {"fs": "fat32", "mp": "/boot/efi",
                                             "pretty_size": "500 MiB"}}}])
        obj.row_warning.set_title.assert_called_once_with("")
        obj.group_warning.set_visible.assert_called_once_with(False)

    def test_removable_warning_can_be_rebranded(self):
        obj = self._make_obj()
        _set_window(obj, {"branding": {
            "copy": {"confirm_warning_removable": "Careful: {disk} is external."}}})
        obj.update([{"disk": {"auto": {"disk": "/dev/sdc", "removable": True}}}])
        obj.row_warning.set_title.assert_called_once_with("Careful: /dev/sdc is external.")

    def test_removable_warning_empty_override_falls_back_not_hidden(self):
        # Same safety net as confirm_warning: a branding file cannot silence
        # the warning on a whole-disk erase, removable or not.
        obj = self._make_obj()
        _set_window(obj, {"branding": {
            "copy": {"confirm_warning_removable": ""}}})
        obj.update([{"disk": {"auto": {"disk": "/dev/sdc", "removable": True}}}])
        obj.row_warning.set_title.assert_called_once()
        (warning,), _ = obj.row_warning.set_title.call_args
        self.assertTrue(warning)
        obj.group_warning.set_visible.assert_called_once_with(True)


    def test_update_with_encryption_none_adds_widget(self):
        obj = self._make_obj()
        obj.update([{"encryption": {"type": "none"}}])
        self.assertGreater(len(obj.active_widgets), 0)

    def test_update_with_encryption_tpm2_adds_widget(self):
        obj = self._make_obj()
        obj.update([{"encryption": {"type": "tpm2-luks"}}])
        self.assertGreater(len(obj.active_widgets), 0)

    def test_update_with_hostname_adds_widget(self):
        obj = self._make_obj()
        obj.update([{"hostname": "my-machine"}])
        self.assertGreater(len(obj.active_widgets), 0)

    def test_update_with_selected_image_adds_widget(self):
        obj = self._make_obj()
        obj.update([{
            "selected_image": "ghcr.io/projectbluefin/bluefin:latest",
            "pretty_name": "Bluefin",
        }])
        self.assertGreater(len(obj.active_widgets), 0)

    def test_update_with_custom_image_adds_widget(self):
        obj = self._make_obj()
        obj.update([{"custom_image": "ghcr.io/myorg/myimage:latest"}])
        self.assertGreater(len(obj.active_widgets), 0)

    def test_update_sets_btn_confirm_label(self):
        obj = self._make_obj()
        obj.update([])
        obj.btn_confirm.set_label.assert_called_once()

    def test_update_uses_branding_quote_for_its_language(self):
        obj = self._make_obj()
        _set_window(obj, {"branding": {
            "name": "Marlin", "copy": {"confirm_subtitle": "plain", "confirm_button": "Onward"},
            "confirm_quotes": {"pt_BR": ["Linha"]}}})
        obj.update([{"language": "pt_BR.UTF-8"}])
        self.assertEqual(obj.page_header.subtitle, "Linha")
        obj.btn_confirm.set_label.assert_called_with("Onward")

    def test_update_uses_plain_subtitle_for_other_languages(self):
        obj = self._make_obj()
        _set_window(obj, {"branding": {
            "name": "Marlin", "copy": {"confirm_subtitle": "plain"},
            "confirm_quotes": {"pt_BR": ["Linha"]}}})
        obj.update([{"language": "en_US.UTF-8"}])
        self.assertEqual(obj.page_header.subtitle, "plain")

    def test_update_without_branding_names_no_product(self):
        obj = self._make_obj()
        _set_window(obj, {})
        obj.update([{"language": "en_US.UTF-8"}])
        self.assertEqual(obj.page_header.subtitle, "")
        for banned in ("Zavala", "Legend", "Bluefin"):
            self.assertNotIn(banned, str(obj.btn_confirm.set_label.call_args))

    def test_update_resets_active_widgets_on_repeat_call(self):
        obj = self._make_obj()
        obj.update([{"hostname": "host1"}])
        count_first = len(obj.active_widgets)
        obj.update([{"hostname": "host2"}])
        # Second call resets list; should have same widget count.
        self.assertEqual(len(obj.active_widgets), count_first)


def _import_BootcConfirm_fresh():
    """Return a freshly-imported confirm module with stubs active.

    Rebuilds gi stubs, pops the cached module, then reimports so the
    module-level GTK template decoration runs against our stub Adw.EntryRow.
    """
    import importlib

    _build_gi_stubs()
    # Pop both the submodule and any parent package cache so Python reimports.
    for key in list(sys.modules.keys()):
        if "bootc_installer.views.confirm" in key:
            del sys.modules[key]
    fresh = importlib.import_module("bootc_installer.views.confirm")
    fresh.BootcChoiceEntry = lambda title, subtitle, icon, **kw: MagicMock()
    fresh.BootcChoiceExpanderEntry = lambda title, subtitle, icon, **kw: MagicMock()
    return fresh


class TestHostnameEditableRow(unittest.TestCase):
    """Tests for the editable hostname EntryRow on the confirm screen."""

    def setUp(self):
        self._orig = sys.modules.get("bootc_installer.core.system")
        sys.modules["bootc_installer.core.system"] = _core_system_stub

    def tearDown(self):
        if self._orig is None:
            sys.modules.pop("bootc_installer.core.system", None)
        else:
            sys.modules["bootc_installer.core.system"] = self._orig

    def test_hostname_row_is_editable_entry(self):
        """Hostname appears as an editable Adw.EntryRow on the confirm screen."""
        mod = _import_BootcConfirm_fresh()
        confirm = mod.BootcConfirm.__new__(mod.BootcConfirm)
        confirm.group_changes = MagicMock()
        confirm.page_header = MagicMock()
        confirm.btn_confirm = MagicMock()

        finals = [{"hostname": "my-machine-a1b2"}]
        confirm.active_widgets = []
        confirm.update(finals)

        override = confirm.get_hostname_override()
        assert override == "my-machine-a1b2"

    def test_get_hostname_override_returns_none_when_no_hostname(self):
        """get_hostname_override() returns None when no hostname was in finals."""
        mod = _import_BootcConfirm_fresh()
        confirm = mod.BootcConfirm.__new__(mod.BootcConfirm)
        confirm.group_changes = MagicMock()
        confirm.page_header = MagicMock()
        confirm.btn_confirm = MagicMock()

        finals = [{"users": {"username": "jorge", "fullname": "Jorge"}}]
        confirm.active_widgets = []
        confirm.update(finals)

        override = confirm.get_hostname_override()
        assert override is None

    def test_hostname_user_edit_is_returned(self):
        """Editing the entry value after update() is reflected in get_hostname_override()."""
        mod = _import_BootcConfirm_fresh()
        confirm = mod.BootcConfirm.__new__(mod.BootcConfirm)
        confirm.group_changes = MagicMock()
        confirm.page_header = MagicMock()
        confirm.btn_confirm = MagicMock()
        confirm.active_widgets = []

        finals = [{"hostname": "original-host"}]
        confirm.update(finals)

        # Simulate the user typing a new hostname
        confirm._hostname_entry_row.set_text("edited-host")

        assert confirm.get_hostname_override() == "edited-host"

    def test_hostname_whitespace_returns_none(self):
        """Whitespace-only hostname is treated as no override."""
        mod = _import_BootcConfirm_fresh()
        confirm = mod.BootcConfirm.__new__(mod.BootcConfirm)
        confirm.group_changes = MagicMock()
        confirm.page_header = MagicMock()
        confirm.btn_confirm = MagicMock()
        confirm.active_widgets = []

        finals = [{"hostname": "original-host"}]
        confirm.update(finals)

        confirm._hostname_entry_row.set_text("   ")

        assert confirm.get_hostname_override() is None

    def test_get_hostname_override_before_update_is_safe(self):
        """Calling get_hostname_override() before update() returns None safely."""
        mod = _import_BootcConfirm_fresh()
        confirm = mod.BootcConfirm.__new__(mod.BootcConfirm)
        confirm.group_changes = MagicMock()
        confirm.page_header = MagicMock()
        confirm.btn_confirm = MagicMock()
        # Never call update() — mimics a code path that calls get_hostname_override early
        # Manually initialize as __init__ would
        confirm._hostname_entry_row = None

        result = confirm.get_hostname_override()
        assert result is None


class TestSourceCheck(unittest.TestCase):
    """The Selected image group (#266, #267): the shared reader's rows,
    Install held only by a blocked source, and a late reply dropped."""

    IMAGE = "registry.example/os:1"

    def _make_obj(self):
        obj = confirm_mod.BootcConfirm.__new__(confirm_mod.BootcConfirm)
        obj.group_source = MagicMock()
        obj.btn_confirm = MagicMock()
        obj._hostname_check = None
        _set_window(obj, {})
        added = []
        obj.group_source.add.side_effect = added.append
        rows = []

        class _Row:
            def __init__(self):
                self.title = self.subtitle = ""
                rows.append(self)

            def set_title(self, t):
                self.title = t

            def set_subtitle(self, t):
                self.subtitle = t

            def __getattr__(self, name):
                return lambda *a, **kw: None

        self._orig_row = confirm_mod.Adw.ActionRow
        confirm_mod.Adw.ActionRow = _Row
        self.addCleanup(setattr, confirm_mod.Adw, "ActionRow", self._orig_row)
        return obj, rows

    def _probe(self, **changes):
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "..", "shared", "probe",
                            "fixtures", "capabilities", "caps-matching-ostree-current.json")
        with open(path, encoding="utf-8") as fh:
            caps = json.load(fh)
        caps["source"]["ref"] = self.IMAGE
        caps["target"]["update_ref_from"] = "source"
        caps.update(changes)
        return {"protocol_version": 1, "capabilities": caps}

    def _req(self, **kw):
        from bootc_shared import source_check
        return source_check.request(source=self.IMAGE, **kw)

    def test_ready_reply_shows_rows_and_keeps_install(self):
        obj, rows = self._make_obj()
        obj._source_generation = 3
        obj._BootcConfirm__on_source_reply(3, self._req(), self._probe())
        titles = [r.title for r in rows]
        self.assertIn(confirm_mod.copy_text.text(obj._BootcConfirm__window, "source_check_ready"), titles)
        obj.btn_confirm.set_sensitive.assert_called_with(True)

    def test_blocked_reply_holds_install(self):
        obj, _rows = self._make_obj()
        obj._source_generation = 1
        obj._BootcConfirm__on_source_reply(1, self._req(features=["unified_storage"]), self._probe())
        obj.btn_confirm.set_sensitive.assert_called_with(False)

    def test_late_reply_is_dropped(self):
        obj, rows = self._make_obj()
        obj._source_generation = 5
        obj._BootcConfirm__on_source_reply(4, self._req(), self._probe())
        self.assertEqual(rows, [])
        obj.btn_confirm.set_sensitive.assert_not_called()

    def test_reply_for_another_source_is_dropped(self):
        obj, rows = self._make_obj()
        obj._source_generation = 1
        obj._BootcConfirm__on_source_reply(1, self._req(), {"protocol_version": 1, "capabilities": dict(
            self._probe()["capabilities"], source={"selected": True, "ref": "other/os:2"})})
        self.assertEqual(rows, [])

    def test_failed_probe_is_not_a_green_check(self):
        obj, rows = self._make_obj()
        obj._source_generation = 1
        obj._BootcConfirm__on_source_reply(1, self._req(), None)
        window = obj._BootcConfirm__window
        titles = [r.title for r in rows]
        self.assertIn(confirm_mod.copy_text.text(window, "source_check_unavailable"), titles)
        self.assertNotIn(confirm_mod.copy_text.text(window, "source_check_ready"), titles)
        obj.btn_confirm.set_sensitive.assert_called_with(True)


class TestSourceReuse(unittest.TestCase):
    """The install source (#267): this computer's system from its bootc
    storage, offered as a second choice and never the default."""

    UPDATE_REF = "ghcr.io/example/os:stable"

    def _probe(self, live=False):
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "..", "shared", "probe",
                            "fixtures", "bootc-store", "store-inaccessible.json")
        with open(path, encoding="utf-8") as fh:
            store = json.load(fh)
        return {"protocol_version": 1, "live": {"is_live": live}, "bootc_store": store}

    def _make_obj(self):
        obj = confirm_mod.BootcConfirm.__new__(confirm_mod.BootcConfirm)
        obj.group_reuse = MagicMock()
        obj.btn_confirm = MagicMock()
        obj._hostname_check = None
        _set_window(obj, {})
        rows = []

        class _Row:
            def __init__(self):
                self.title = self.subtitle = ""
                rows.append(self)

            def set_title(self, t):
                self.title = t

            def set_subtitle(self, t):
                self.subtitle = t

            def __getattr__(self, name):
                return lambda *a, **kw: None

        for owner, name, value in ((confirm_mod.Adw, "ActionRow", _Row),
                                   (confirm_mod.Gtk, "CheckButton", MagicMock),
                                   (confirm_mod.Gtk, "Align", MagicMock())):
            self.addCleanup(setattr, owner, name, getattr(owner, name, None))
            setattr(owner, name, value)
        self.checks = []
        obj._reuse_check = types.SimpleNamespace(submit=self.checks.append)
        return obj, rows

    def _recipe(self):
        return {"disk": "/dev/vda", "image": self.UPDATE_REF, "targetImgref": self.UPDATE_REF,
                "filesystem": "xfs", "encryption": {"type": "luks-passphrase", "passphrase": "s"}}

    def test_offered_but_never_the_default(self):
        obj, rows = self._make_obj()
        obj._BootcConfirm__update_reuse(self._probe(), self._recipe())
        window = obj._BootcConfirm__window
        titles = [r.title for r in rows]
        self.assertEqual(titles, [confirm_mod.copy_text.text(window, "source_reuse_download"),
                                  confirm_mod.copy_text.text(window, "source_reuse_local")])
        self.assertFalse(obj.reuse_selected)
        self.assertEqual(obj.apply_source(self._recipe()), self._recipe())
        obj.group_reuse.set_visible.assert_called_with(True)

    def test_never_on_live_media(self):
        obj, rows = self._make_obj()
        obj._BootcConfirm__update_reuse(self._probe(live=True), self._recipe())
        self.assertEqual(rows, [])
        obj.group_reuse.set_visible.assert_called_with(False)

    def test_the_choice_writes_source_reuse_and_is_checked(self):
        obj, _rows = self._make_obj()
        obj._BootcConfirm__update_reuse(self._probe(), self._recipe())
        obj._reuse_selected = True
        obj._BootcConfirm__update_reuse(self._probe(), self._recipe())
        recipe = obj.apply_source(self._recipe())
        self.assertEqual(recipe["image"], "")
        self.assertEqual(recipe["targetImgref"], self.UPDATE_REF)
        self.assertEqual(recipe["sourceReuse"]["digest"], "sha256:" + "1" * 64)
        self.assertIn("bootc_store_reuse", recipe["experimental"])
        fragment = self.checks[-1]
        self.assertEqual(fragment["sourceReuse"], recipe["sourceReuse"])
        self.assertNotIn("encryption", fragment)

    def test_a_validate_code_shows_its_copy_line_and_holds_install(self):
        obj, rows = self._make_obj()
        obj._BootcConfirm__update_reuse(self._probe(), self._recipe())
        obj._reuse_selected = True
        obj._BootcConfirm__on_reuse_checked(
            [{"code": "source_reuse_source_moved", "field": "sourceReuse", "message": "x"}], None)
        window = obj._BootcConfirm__window
        self.assertIn(confirm_mod.copy_text.text(window, "validate_source_reuse_source_moved"),
                      [r.title for r in rows])
        obj.btn_confirm.set_sensitive.assert_called_with(False)

    def test_a_different_item_drops_the_choice(self):
        obj, _rows = self._make_obj()
        obj._BootcConfirm__update_reuse(self._probe(), self._recipe())
        obj._reuse_selected = True
        probe = self._probe()
        probe["bootc_store"]["items"][0]["digest"] = "sha256:" + "2" * 64
        obj._BootcConfirm__update_reuse(probe, self._recipe())
        self.assertFalse(obj.reuse_selected)



class TestInstallPlan(unittest.TestCase):
    """The install plan (tuna-os/fisherman#371): `fisherman plan --json -`
    of the recipe that the install uses, shown on the page, and its disk
    identity bound into the recipe at confirmation. Without a plan the page
    and the recipe are as before."""

    SECRET = "plan-sentinel-passphrase"
    GOLDEN = os.path.join(os.path.dirname(__file__), "..", "..", "fisherman", "fisherman",
                          "cmd", "fisherman", "testdata", "plan")

    def _golden(self, name):
        from bootc_shared import plan as install_plan
        path = os.path.join(self.GOLDEN, name + ".golden")
        if not os.path.exists(path):
            self.skipTest("no fisherman submodule")
        with open(path, encoding="utf-8") as fh:
            return install_plan.parse(fh.read().replace("@DIR@", "/dev").replace(
                "@PLAN_DIGEST@", "sha256:" + "ab" * 32))

    def _recipe(self, disk="/dev/sda"):
        return {"disk": disk, "image": "ghcr.io/example/os:stable", "hostname": "host",
                "encryption": {"type": "luks-passphrase", "passphrase": self.SECRET}}

    def _make_obj(self):
        obj = confirm_mod.BootcConfirm.__new__(confirm_mod.BootcConfirm)
        obj.group_plan = MagicMock()
        obj._hostname_entry_row = None
        _set_window(obj, {})
        rows = []

        class _Row:
            def __init__(self):
                self.title = self.subtitle = ""
                rows.append(self)

            def set_title(self, t):
                self.title = t

            def set_subtitle(self, t):
                self.subtitle = t

            def __getattr__(self, name):
                return lambda *a, **kw: None

        self.addCleanup(setattr, confirm_mod.Adw, "ActionRow", confirm_mod.Adw.ActionRow)
        confirm_mod.Adw.ActionRow = _Row
        # The worker runs at once, and its idle callback with it.
        self.addCleanup(setattr, confirm_mod.GLib, "idle_add", confirm_mod.GLib.idle_add)
        confirm_mod.GLib.idle_add = lambda fn, *a: fn(*a)
        obj._plan_start = lambda fn: fn()
        self.requests = []
        return obj, rows

    def _answer(self, obj, answer):
        def request(recipe):
            self.requests.append(recipe)
            return answer
        obj._plan_request = request

    def test_a_plan_shows_the_disk_and_what_is_erased(self):
        obj, rows = self._make_obj()
        self._answer(obj, (self._golden("grub2-plain"), None))
        obj._BootcConfirm__start_plan(self._recipe())
        titles = [r.title for r in rows]
        self.assertEqual(titles[0], "Installs to Fixture Disk")
        self.assertIn("serial number FIXTURE-SDA-SERIAL", rows[0].subtitle)
        self.assertIn("Everything on /dev/sda is erased.", titles)
        obj.group_plan.set_visible.assert_called_with(True)
        obj.group_plan.set_title.assert_called_with(
            confirm_mod.copy_text.text(obj._BootcConfirm__window, "confirm_plan_title"))
        # The recipe that was asked about is the install's, passphrase and all.
        self.assertEqual(self.requests, [self._recipe()])

    def test_confirmation_binds_the_recipe_to_the_planned_disk(self):
        obj, _rows = self._make_obj()
        self._answer(obj, (self._golden("grub2-plain"), None))
        obj._BootcConfirm__start_plan(self._recipe())
        bound = obj.bind_disk(self._recipe())
        self.assertEqual(bound["diskIdentity"], {
            "serial": "FIXTURE-SDA-SERIAL", "wwn": "0x5000c500a1b2c3d4",
            "sizeBytes": 500107862016})
        # Another disk than the plan's is not bound.
        self.assertNotIn("diskIdentity", obj.bind_disk(self._recipe("/dev/sdb")))

    def test_confirmation_copies_the_plan_binding(self):
        """A fisherman with `plan.binding` (tuna-os/fisherman#472): the
        recipe carries it as `planBinding`, beside `diskIdentity`."""
        digest = "sha256:" + "cd" * 32
        answer = self._golden("grub2-plain")
        answer["plan"]["binding"] = {"digest": digest, "read_image": False}
        obj, _rows = self._make_obj()
        self._answer(obj, (answer, None))
        obj._BootcConfirm__start_plan(self._recipe())
        bound = obj.bind_disk(self._recipe())
        self.assertEqual(bound["planBinding"], {"digest": digest, "readImage": False})
        self.assertIn("diskIdentity", bound)
        self.assertNotIn("planBinding", obj.bind_disk(self._recipe("/dev/sdb")))

    def test_a_plan_without_a_binding_leaves_plan_binding_out(self):
        answer = self._golden("grub2-plain")
        answer["plan"].pop("binding", None)
        obj, _rows = self._make_obj()
        self._answer(obj, (answer, None))
        obj._BootcConfirm__start_plan(self._recipe())
        bound = obj.bind_disk(self._recipe())
        self.assertNotIn("planBinding", bound)
        self.assertIn("diskIdentity", bound)

    def test_a_disk_without_serial_binds_its_size_and_says_so(self):
        obj, rows = self._make_obj()
        self._answer(obj, (self._golden("loop-image"), None))
        obj._BootcConfirm__start_plan(self._recipe("/dev/loop0"))
        self.assertEqual(rows[0].title, "Installs to unknown")
        self.assertIn("serial number unknown", rows[0].subtitle)
        self.assertIn(confirm_mod.copy_text.text(obj._BootcConfirm__window, "confirm_plan_unbound"),
                      [r.title for r in rows])
        self.assertEqual(obj.bind_disk(self._recipe("/dev/loop0"))["diskIdentity"],
                         {"sizeBytes": 8589934592})

    def test_no_plan_leaves_the_page_and_the_recipe_as_before(self):
        for answer in ((None, "fisherman plan failed (exit 2): unknown command"),
                       (self._golden("invalid"), None)):
            with self.subTest(answer=answer[1]):
                obj, rows = self._make_obj()
                self._answer(obj, answer)
                with self.assertLogs("Installer::Confirm", level="INFO") as logs:
                    obj._BootcConfirm__start_plan(self._recipe())
                self.assertEqual(rows, [])
                obj.group_plan.set_visible.assert_called_with(False)
                self.assertIsNone(obj.install_plan)
                self.assertEqual(obj.bind_disk(self._recipe()), self._recipe())
                self.assertNotIn("planBinding", obj.bind_disk(self._recipe()))
                self.assertNotIn(self.SECRET, "\n".join(logs.output))

    def test_a_late_reply_is_dropped(self):
        obj, rows = self._make_obj()
        obj._plan_generation = 4
        obj._BootcConfirm__on_plan_reply(3, (self._golden("grub2-plain"), None))
        self.assertEqual(rows, [])
        self.assertIsNone(obj.install_plan)

    def test_a_new_visit_forgets_the_old_plan(self):
        obj, _rows = self._make_obj()
        self._answer(obj, (self._golden("grub2-plain"), None))
        obj._BootcConfirm__start_plan(self._recipe())
        self.assertIsNotNone(obj.install_plan)
        obj._BootcConfirm__clear_plan()
        self.assertEqual(obj.bind_disk(self._recipe()), self._recipe())

    def test_the_plan_is_asked_unprivileged_with_the_recipe_on_stdin(self):
        from bootc_shared import plan as install_plan

        from bootc_installer.utils import fisherman_runner
        calls = []

        class _Proc:
            returncode = 0
            stderr = ""
            stdout = json.dumps({"protocol_version": 1, "valid": True, "errors": [],
                                 "plan": {"target": {"layout": "manual"}, "destroys": []}})

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return _Proc()

        with patch.object(fisherman_runner, "IN_FLATPAK", False), \
                patch.object(install_plan.subprocess, "run", fake_run):
            result, error = confirm_mod.request_plan(self._recipe())
        self.assertIsNone(error)
        self.assertTrue(result["valid"])
        argv, kwargs = calls[0]
        self.assertEqual(argv[-3:], ["plan", "--json", "-"])
        self.assertNotIn("pkexec", argv)
        self.assertNotIn(self.SECRET, " ".join(argv))
        self.assertEqual(json.loads(kwargs["input"])["encryption"]["passphrase"], self.SECRET)

    def test_a_flatpak_that_cannot_stage_has_no_plan(self):
        from bootc_installer.utils import fisherman_runner
        with patch.object(fisherman_runner, "IN_FLATPAK", True), \
                patch.object(fisherman_runner, "stage_on_host", lambda: False):
            result, error = confirm_mod.request_plan(self._recipe())
        self.assertIsNone(result)
        self.assertIn("stage", error)

    def test_the_hostname_typed_here_is_in_the_planned_recipe(self):
        obj, _rows = self._make_obj()
        row = confirm_mod.Adw.EntryRow()
        row.set_text("typed-host")
        obj._hostname_entry_row = row
        self.assertEqual(obj._BootcConfirm__with_hostname(self._recipe())["hostname"],
                         "typed-host")


if __name__ == "__main__":
    unittest.main()
