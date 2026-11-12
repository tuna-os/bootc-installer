"""Unit tests for layouts/yes_no.py pure logic.

Uses __new__ + attribute injection (Python name-mangling) to test get_finals(),
should_show(), __on_response() and __on_info() without a
display.  gi.repository and bootc_installer.windows.dialog are stubbed at
import time so the @Gtk.Template decorators are no-ops.
"""

import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

class _StubWidget:
    def get_active(self):
        return False

    def set_visible(self, v):
        pass


class _Template:
    def __call__(self, *args, **kwargs):
        return lambda cls: cls

    def Child(self, *args, **kwargs):
        return None


def _build_gi_stubs():
    gi_mod = types.ModuleType("gi")
    repo_mod = types.ModuleType("gi.repository")

    gtk_mod = types.ModuleType("gi.repository.Gtk")
    gtk_mod.Template = _Template()
    gtk_mod.Box = _StubWidget
    gtk_mod.Switch = _StubWidget
    gtk_mod.Align = types.SimpleNamespace(CENTER=0)

    adw_mod = types.ModuleType("gi.repository.Adw")
    adw_mod.Bin = _StubWidget
    adw_mod.ActionRow = _StubWidget
    adw_mod.PreferencesGroup = _StubWidget

    gobject_mod = types.ModuleType("gi.repository.GObject")
    gobject_mod.Property = lambda *a, **kw: (lambda f: property(f))

    for name, mod in [("Gtk", gtk_mod), ("Adw", adw_mod), ("GObject", gobject_mod)]:
        setattr(repo_mod, name, mod)
        sys.modules[f"gi.repository.{name}"] = mod

    gi_mod.repository = repo_mod
    gi_mod.require_version = lambda *a, **kw: None
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repo_mod

    # Stub the BootcDialog dependency so it can be tracked per-test.
    _dialog_stub = types.ModuleType("bootc_installer.windows.dialog")
    _dialog_stub.BootcDialog = MagicMock(return_value=MagicMock())
    sys.modules["bootc_installer.windows.dialog"] = _dialog_stub


def _import_yes_no_fresh():
    _build_gi_stubs()
    sys.modules.pop("bootc_installer.layouts.yes_no", None)
    try:
        import bootc_installer.layouts as lp
        lp.__dict__.pop("yes_no", None)
    except Exception:
        pass
    return importlib.import_module("bootc_installer.layouts.yes_no")


_yn_mod = _import_yes_no_fresh()


# ---------------------------------------------------------------------------
# BootcLayoutYesNo
# ---------------------------------------------------------------------------

class TestYesNoGetFinals(unittest.TestCase):
    """get_finals() returns the correct vars/funcs structure."""

    def _make_obj(self, key="accepted", response=False, funcs=None):
        obj = object.__new__(_yn_mod.BootcLayoutYesNo)
        obj._BootcLayoutYesNo__key = key
        obj._BootcLayoutYesNo__response = response
        obj._BootcLayoutYesNo__step = {"final": funcs or []}
        return obj

    def test_response_false_reflected(self):
        finals = self._make_obj(response=False).get_finals()
        self.assertFalse(finals["vars"]["accepted"])

    def test_response_true_reflected(self):
        finals = self._make_obj(response=True).get_finals()
        self.assertTrue(finals["vars"]["accepted"])

    def test_custom_key(self):
        finals = self._make_obj(key="my_flag", response=True).get_finals()
        self.assertIn("my_flag", finals["vars"])
        self.assertTrue(finals["vars"]["my_flag"])

    def test_funcs_from_step(self):
        finals = self._make_obj(funcs=["process_yes"]).get_finals()
        self.assertEqual(finals["funcs"], ["process_yes"])

    def test_empty_funcs(self):
        self.assertEqual(self._make_obj().get_finals()["funcs"], [])

    def test_result_has_vars_and_funcs_keys(self):
        result = self._make_obj().get_finals()
        self.assertIn("vars", result)
        self.assertIn("funcs", result)


class TestYesNoShouldShow(unittest.TestCase):
    """should_show() always returns True regardless of context."""

    def _obj(self):
        return object.__new__(_yn_mod.BootcLayoutYesNo)

    def test_true_with_empty_context(self):
        self.assertTrue(self._obj().should_show({}))

    def test_true_with_populated_context(self):
        self.assertTrue(self._obj().should_show({"encryption": "none", "disk": "/dev/sda"}))


class TestYesNoOnResponse(unittest.TestCase):
    """__on_response() stores the answer and advances the wizard."""

    def _make_obj(self):
        obj = object.__new__(_yn_mod.BootcLayoutYesNo)
        obj._BootcLayoutYesNo__response = False
        obj._BootcLayoutYesNo__step = {"final": []}
        obj._BootcLayoutYesNo__window = MagicMock()
        return obj

    def test_stores_true(self):
        obj = self._make_obj()
        obj._BootcLayoutYesNo__on_response(None, True)
        self.assertTrue(obj._BootcLayoutYesNo__response)

    def test_stores_false(self):
        obj = self._make_obj()
        obj._BootcLayoutYesNo__response = True
        obj._BootcLayoutYesNo__on_response(None, False)
        self.assertFalse(obj._BootcLayoutYesNo__response)

    def test_advances_window(self):
        obj = self._make_obj()
        obj._BootcLayoutYesNo__on_response(None, True)
        obj._BootcLayoutYesNo__window.next.assert_called_once()


class TestYesNoOnInfo(unittest.TestCase):
    """__on_info() shows a dialog only when 'info' key is present in buttons."""

    def _make_obj(self, buttons):
        obj = object.__new__(_yn_mod.BootcLayoutYesNo)
        obj._BootcLayoutYesNo__window = MagicMock()
        obj._BootcLayoutYesNo__step = {"buttons": buttons, "final": []}
        return obj

    def _dialog_mock(self):
        # Use the module's own imported reference — sys.modules may have been
        # replaced by a later _build_gi_stubs() call.
        return _yn_mod.BootcDialog

    def test_no_info_key_returns_without_dialog(self):
        obj = self._make_obj({"yes": "Yes", "no": "No"})
        self._dialog_mock().reset_mock()
        obj._BootcLayoutYesNo__on_info(None)
        self._dialog_mock().assert_not_called()

    def test_info_key_present_shows_dialog(self):
        obj = self._make_obj(
            {
                "yes": "Yes",
                "no": "No",
                "info": {"title": "Details", "text": "Here is more info."},
            }
        )
        self._dialog_mock().reset_mock()
        obj._BootcLayoutYesNo__on_info(None)
        self._dialog_mock().assert_called_once()



if __name__ == "__main__":
    unittest.main()
