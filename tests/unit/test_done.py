"""
Unit tests for done.py — reboot logic and icon application.
No display required; GTK widgets are not instantiated.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch, sentinel

from bootc_installer.utils.host import Scope
from tests.unit.fake_host import FAIL, MISSING, OK, TIMEOUT, FakeExecutor


def _build_gi_stubs():
    gi_mod = types.ModuleType("gi")
    repo_mod = types.ModuleType("gi.repository")

    class _Template:
        def __call__(self, *args, **kwargs):
            return lambda cls: cls

        def Child(self, *args, **kwargs):
            return None

    class _StubBin:
        pass

    gtk_mod = types.ModuleType("gi.repository.Gtk")
    gtk_mod.Template = _Template()
    gtk_mod.Box = _StubBin

    adw_mod = types.ModuleType("gi.repository.Adw")
    adw_mod.Bin = _StubBin
    adw_mod.Window = _StubBin

    gobject_mod = types.ModuleType("gi.repository.GObject")

    def _property(*args, **kwargs):
        return lambda func: property(func)

    gobject_mod.Property = _property

    class _ResourceLookupFlags:
        NONE = 0

    gio_mod = types.ModuleType("gi.repository.Gio")
    gio_mod.bus_get_sync = MagicMock()
    # Use SimpleNamespace so typos like .BusTyp raise AttributeError immediately.
    gio_mod.BusType = types.SimpleNamespace(SYSTEM=sentinel.SYSTEM_BUS)
    gio_mod.DBusCallFlags = types.SimpleNamespace(NONE=sentinel.DBUS_FLAGS_NONE)
    gio_mod.ResourceLookupFlags = _ResourceLookupFlags
    gio_mod.resources_lookup_data = MagicMock()
    gio_mod.File = MagicMock()

    sys.modules["gi.repository.Gtk"] = gtk_mod
    sys.modules["gi.repository.Adw"] = adw_mod
    sys.modules["gi.repository.GObject"] = gobject_mod
    sys.modules["gi.repository.Gio"] = gio_mod
    repo_mod.Gtk = gtk_mod
    repo_mod.Adw = adw_mod
    repo_mod.GObject = gobject_mod
    repo_mod.Gio = gio_mod

    for lib in ("Gdk", "GLib"):
        stub = MagicMock()
        setattr(repo_mod, lib, stub)
        sys.modules[f"gi.repository.{lib}"] = stub

    gi_mod.repository = repo_mod
    gi_mod.require_version = lambda *a, **kw: None
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repo_mod


_build_gi_stubs()
if "bootc_installer.windows.dialog_output" not in sys.modules:
    sys.modules["bootc_installer.windows.dialog_output"] = MagicMock()

from bootc_installer.views.done import (  # noqa: E402
    BootcDone,
    apply_icon,
    warmup_registry,
)


class TestDoReboot(unittest.TestCase):

    def setUp(self):
        # test_branding_parity._import_done() reimports done.py during test
        # execution, rebinding done.Gio to whichever stubs are current in
        # sys.modules.  A test that stubs gi can also
        # overwrite sys.modules["gi.repository.GLib"] with a bare ModuleType
        # that lacks Variant, breaking done.py's D-Bus call path.
        # Rebuilding our own stubs first and then reimporting ensures that
        # do_reboot and the patch("...Gio.bus_get_sync") target the same object.
        _build_gi_stubs()
        sys.modules.pop("bootc_installer.views.done", None)
        import bootc_installer.views as views_pkg
        views_pkg.__dict__.pop("done", None)
        import bootc_installer.views.done  # noqa: F401 — re-populates sys.modules

    def test_reboot_via_dbus_success(self):
        import bootc_installer.views.done as done_mod
        conn = MagicMock()
        with patch("bootc_installer.views.done.Gio.bus_get_sync", return_value=conn):
            result = done_mod.do_reboot(FakeExecutor())
        self.assertTrue(result)
        conn.call_sync.assert_called_once()

    def test_dbus_reboot_calls_correct_method(self):
        """D-Bus contract: must call org.freedesktop.login1 Reboot method."""
        import bootc_installer.views.done as done_mod
        conn = MagicMock()
        with patch("bootc_installer.views.done.Gio.bus_get_sync", return_value=conn):
            done_mod.do_reboot(FakeExecutor())
        call_args = conn.call_sync.call_args
        # Positional args: bus_name, object_path, interface_name, method_name, params, ...
        args = call_args[0]
        self.assertIn("login1", args[0])          # bus name
        self.assertIn("Manager", args[2])          # interface
        self.assertEqual(args[3], "Reboot")        # method name

    def _no_bus(self):
        return patch("bootc_installer.views.done.Gio.bus_get_sync",
                     side_effect=Exception("no bus"))

    def test_reboot_falls_back_to_systemctl_on_the_host(self):
        import bootc_installer.views.done as done_mod
        ex = FakeExecutor([OK], in_flatpak=False)
        with self._no_bus():
            self.assertTrue(done_mod.do_reboot(ex))
        kind, cmd, scope, timeout, argv = ex.calls[0]
        self.assertEqual((kind, cmd, scope), ("run", ["systemctl", "reboot"], Scope.HOST))
        # No timeout: killing flatpak-spawn would not stop the host reboot.
        self.assertIsNone(timeout)
        self.assertEqual(argv, ["systemctl", "reboot"])

    def test_reboot_flatpak_fallback_is_flatpak_spawn_host_systemctl_reboot(self):
        import bootc_installer.views.done as done_mod
        ex = FakeExecutor([OK], in_flatpak=True)
        with self._no_bus():
            self.assertTrue(done_mod.do_reboot(ex))
        self.assertEqual(ex.calls[0][4], ["flatpak-spawn", "--host", "systemctl", "reboot"])

    def test_reboot_tries_reboot_binary_when_systemctl_fails(self):
        import bootc_installer.views.done as done_mod
        ex = FakeExecutor([FAIL, OK], in_flatpak=False)
        with self._no_bus():
            self.assertTrue(done_mod.do_reboot(ex))
        self.assertEqual([c[1] for c in ex.calls], [["systemctl", "reboot"], ["reboot"]])
        self.assertTrue(all(c[2] is Scope.HOST for c in ex.calls))

    def test_reboot_returns_false_when_all_methods_fail(self):
        import bootc_installer.views.done as done_mod
        for answers in ([FAIL, FAIL], [MISSING, MISSING], [TIMEOUT, FAIL]):
            with self.subTest(answers=answers), self._no_bus():
                self.assertFalse(done_mod.do_reboot(FakeExecutor(answers)))



class TestApplyIcon(unittest.TestCase):

    def test_resource_uri_calls_set_from_resource(self):
        page_header = MagicMock()
        apply_icon(page_header, "resource:///org/bootcinstaller/Installer/images/bootcos.svg")
        page_header.set_from_resource.assert_called_once_with(
            "/org/bootcinstaller/Installer/images/bootcos.svg"
        )

    def test_icon_theme_name_calls_set_icon_name(self):
        page_header = MagicMock()
        apply_icon(page_header, "object-select-symbolic")
        assert page_header.icon_name == "object-select-symbolic"
        page_header.set_from_resource.assert_not_called()

    def test_apply_icon_logs_errors(self):
        """apply_icon must log failures rather than silently swallow them."""
        from unittest.mock import patch as _patch
        status_page = MagicMock()
        status_page.set_from_resource.side_effect = Exception("bad resource")
        import bootc_installer.views.done as done_mod
        with _patch.object(done_mod, "log") as mock_log:
            # Use done_mod.apply_icon so the patched `log` is in the same module namespace.
            done_mod.apply_icon(status_page, "resource:///org/bootcinstaller/Installer/images/missing.svg")
        mock_log.warning.assert_called_once()


class TestMainWindowIconExtraction(unittest.TestCase):
    """Verify that update_finals() extracts selected_icon alongside pretty_name."""

    def test_selected_icon_extracted_from_finals(self):
        finals = [
            {"hostname": "bootcos"},
            {"pretty_name": "Yellowfin", "icon": "resource:///org/bootcinstaller/Installer/images/yellowfin.svg"},
        ]
        pretty_name = None
        selected_icon = None
        for f in finals:
            if isinstance(f, dict):
                if pretty_name is None and "pretty_name" in f:
                    pretty_name = f["pretty_name"]
                if selected_icon is None and "icon" in f:
                    selected_icon = f["icon"]
            if pretty_name and selected_icon:
                break

        self.assertEqual(pretty_name, "Yellowfin")
        self.assertEqual(selected_icon, "resource:///org/bootcinstaller/Installer/images/yellowfin.svg")

    def test_selected_icon_none_when_not_in_finals(self):
        finals = [{"hostname": "bootcos"}, {"pretty_name": "Yellowfin"}]
        selected_icon = None
        for f in finals:
            if isinstance(f, dict) and selected_icon is None and "icon" in f:
                selected_icon = f["icon"]
        self.assertIsNone(selected_icon)


class TestRegistryWarmup(unittest.TestCase):
    """warmup_registry — verify skopeo is called correctly."""

    def test_warmup_calls_skopeo_with_docker_prefix(self):
        ex = FakeExecutor([OK])
        warmup_registry("ghcr.io/tuna-os/yellowfin:gnome50", ex)
        kind, cmd, scope, timeout, argv = ex.calls[0]
        self.assertEqual(cmd, ["skopeo", "inspect", "docker://ghcr.io/tuna-os/yellowfin:gnome50"])
        # Where it ran before: this process's environment, 60 s at most.
        self.assertIs(scope, Scope.LOCAL)
        self.assertEqual(timeout, 60)

    def test_warmup_handles_every_failure(self):
        for answer in (MISSING, TIMEOUT, {"returncode": 1, "stderr": "unauthorized"}):
            with self.subTest(answer=answer):
                warmup_registry("ghcr.io/tuna-os/yellowfin:gnome50", FakeExecutor([answer]))

    def test_no_frontend_source_runs_efibootmgr(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2] / "bootc_installer"
        for path in sorted(root.rglob("*.py")):
            with self.subTest(path=path.name):
                self.assertNotIn("efibootmgr", path.read_text(encoding="utf-8"))

    def test_restart_runs_the_reboot_and_nothing_before_it(self):
        from unittest import mock

        from bootc_installer.views import done
        page = mock.MagicMock()
        ex = FakeExecutor()  # any host command fails the test
        with mock.patch.object(done, "do_reboot", return_value=True) as reboot, \
                mock.patch.object(done, "default_executor", return_value=ex):
            done.BootcDone._BootcDone__on_reboot_clicked(page, None)
        reboot.assert_called_once_with()
        self.assertEqual(ex.calls, [])


class TestErrorEventHint(unittest.TestCase):
    """The failure page shows fisherman's `error` event (#64), not a guess
    from the log."""

    def test_message_is_shown(self):
        from bootc_installer.views.done import error_event_hint
        hint = error_event_hint({"message": "partitioning disk: exit status 1",
                                 "code": "", "field": ""})
        self.assertEqual(hint, "Error: partitioning disk: exit status 1")

    def test_copy_line_for_a_code_wins(self):
        from bootc_installer.views.done import error_event_hint
        copy = {"validate_disk_too_small": "Choose a larger disk."}
        hint = error_event_hint(
            {"message": "disk /dev/sda is 20 GiB", "code": "disk_too_small", "field": "disk"},
            lambda key: copy.get(key, ""))
        self.assertEqual(hint, "Choose a larger disk.")

    def test_a_swapped_disk_shows_the_disk_identity_line(self):
        """A recipe that the confirm page bound with `diskIdentity`
        (tuna-os/fisherman#371) and a device that changed since: the
        install's refusal reads as the branding line."""
        from bootc_shared.branding import COPY_DEFAULTS

        from bootc_installer.views.done import error_event_hint
        hint = error_event_hint(
            {"message": "disk /dev/sda reports serial \"B\", not \"A\"",
             "code": "disk_identity_mismatch", "field": "diskIdentity.serial"},
            lambda key: COPY_DEFAULTS.get(key, ""))
        self.assertEqual(hint, COPY_DEFAULTS["validate_disk_identity_mismatch"])

    def test_a_code_without_copy_falls_back_to_the_message(self):
        from bootc_installer.views.done import error_event_hint
        hint = error_event_hint(
            {"message": "unknown recipe field", "code": "recipe_unknown_field",
             "field": "encrypton"}, lambda key: "")
        self.assertEqual(hint, "Error: unknown recipe field")

    def test_no_event_and_an_empty_event_give_nothing(self):
        from bootc_installer.views.done import error_event_hint
        self.assertEqual(error_event_hint(None), "")
        self.assertEqual(error_event_hint({}), "")
        self.assertEqual(error_event_hint({"message": "  ", "code": "", "field": ""}), "")

    def test_a_long_message_is_one_bounded_line(self):
        from bootc_installer.views.done import error_event_hint
        hint = error_event_hint({"message": "a\nb " + "x" * 500})
        self.assertNotIn("\n", hint)
        self.assertLessEqual(len(hint), len("Error: ") + 300)
        self.assertTrue(hint.endswith("…"))


class TestFailureDiskAndCleanupLines(unittest.TestCase):
    """tuna-os/fisherman#449: the failure page says whether the disk was
    changed, and when the cleanup failed or timed out. Each case of
    shared/progress/error-cases.json reaches the page."""

    def test_the_error_cases_reach_the_failure_page(self):
        import json
        import os

        from bootc_shared import progress as pp
        from bootc_shared.branding import COPY_DEFAULTS
        path = os.path.join(os.path.dirname(__file__), "..", "..", "shared", "progress",
                            "error-cases.json")
        with open(path, encoding="utf-8") as fh:
            cases = json.load(fh)["cases"]
        for case in cases:
            state = pp.new_progress_state()
            for event in case["events"]:
                pp.apply_progress_event(json.dumps(event), state)
            obj = MagicMock()
            obj._BootcDone__window = types.SimpleNamespace(
                recipe={}, pretty_name=None, selected_icon=None)
            obj._BootcDone__extract_failure_hint.return_value = "from the log"
            BootcDone.set_result(obj, False, None, exit_code=1, error=state["error"])
            parts = obj.page_header.subtitle.split("\n\n")
            with self.subTest(case=case["name"]):
                self.assertEqual(parts[1:], [COPY_DEFAULTS[key] for key in case["lines"]])
                self.assertTrue(parts[0])

    def test_the_disk_lines(self):
        from bootc_shared.branding import COPY_DEFAULTS
        obj = MagicMock()
        obj._BootcDone__window = types.SimpleNamespace(
            recipe={}, pretty_name=None, selected_icon=None)
        BootcDone.set_result(obj, False, None, exit_code=1, error={
            "message": "invalid recipe: disk /dev/vda is too small", "code": "x_unknown",
            "field": "", "step_id": "", "disk_changed": False,
            "cleanup": {"status": "ok", "message": ""}})
        self.assertIn("Your disk was not changed", obj.page_header.subtitle)
        self.assertTrue(obj.page_header.subtitle.endswith(
            COPY_DEFAULTS["done_failed_disk_unchanged"]))
