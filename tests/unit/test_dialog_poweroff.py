"""Unit tests for windows/dialog_poweroff.py's host systemctl helper.

The dialog's rows used to call a bare `systemctl`, which does not exist in
the flatpak sandbox; every row raised FileNotFoundError out of its signal
handler. gi.repository is stubbed at import time.
"""

import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock

from bootc_installer.utils.host import Scope
from tests.unit.fake_host import MISSING, OK, FakeExecutor


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

    gtk_mod = types.ModuleType("gi.repository.Gtk")
    gtk_mod.Template = _Template()

    adw_mod = types.ModuleType("gi.repository.Adw")
    adw_mod.Window = _Stub

    glib_mod = MagicMock()

    for name, mod in [("Gtk", gtk_mod), ("Adw", adw_mod), ("GLib", glib_mod)]:
        setattr(repo_mod, name, mod)
        sys.modules[f"gi.repository.{name}"] = mod

    gi_mod.repository = repo_mod
    gi_mod.require_version = lambda *a, **kw: None
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repo_mod


def _import_fresh():
    _build_gi_stubs()
    sys.modules.pop("bootc_installer.windows.dialog_poweroff", None)
    return importlib.import_module("bootc_installer.windows.dialog_poweroff")


_mod = _import_fresh()


class HostSystemctlTests(unittest.TestCase):
    def test_the_dialog_uses_the_host_actions_helper(self):
        from bootc_installer.utils import host_actions
        self.assertIs(_mod._host_systemctl, host_actions.host_systemctl)

    def test_wraps_in_flatpak_spawn_inside_the_sandbox(self):
        ex = FakeExecutor([OK], in_flatpak=True)
        self.assertTrue(_mod._host_systemctl("reboot", "--firmware-setup", executor=ex))
        kind, cmd, scope, timeout, argv = ex.calls[0]
        self.assertEqual(
            argv, ["flatpak-spawn", "--host", "systemctl", "reboot", "--firmware-setup"])
        self.assertIs(scope, Scope.HOST)
        self.assertIsNone(timeout)

    def test_runs_directly_outside_the_sandbox(self):
        ex = FakeExecutor([OK], in_flatpak=False)
        _mod._host_systemctl("poweroff", executor=ex)
        self.assertEqual(ex.calls[0][4], ["systemctl", "poweroff"])

    def test_missing_binary_is_logged_not_raised(self):
        self.assertFalse(_mod._host_systemctl("reboot", executor=FakeExecutor([MISSING])))


if __name__ == "__main__":
    unittest.main()
