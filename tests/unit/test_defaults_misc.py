import importlib
import os
import sys
import types
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class _Template:
    def __call__(self, *args, **kwargs):
        return lambda cls: cls

    def Child(self, *args, **kwargs):
        return None

    def Callback(self, *args, **kwargs):
        return lambda func: func


@contextmanager
def _import_with_gi_stubs(module_name):
    managed = [
        "gi",
        "gi.repository",
        "gi.repository.Adw",
        "gi.repository.Gio",
        "gi.repository.GLib",
        "gi.repository.GObject",
        "gi.repository.Gdk",
        "gi.repository.Gtk",
        module_name,
        "bootc_installer.utils.run_async",
    ]
    saved = {name: sys.modules.get(name) for name in managed}

    for name in managed:
        sys.modules.pop(name, None)

    template = _Template()
    gi_mod = types.ModuleType("gi")
    repo_mod = types.ModuleType("gi.repository")

    gtk_mod = types.ModuleType("gi.repository.Gtk")
    gtk_mod.Template = template
    gtk_mod.Box = object

    adw_mod = types.ModuleType("gi.repository.Adw")
    adw_mod.Bin = object
    adw_mod.ActionRow = object

    gio_mod = types.ModuleType("gi.repository.Gio")
    gio_mod.Settings = type("Settings", (), {"new": staticmethod(lambda _schema: MagicMock())})

    glib_mod = types.ModuleType("gi.repository.GLib")
    glib_mod.SOURCE_REMOVE = False
    glib_mod.idle_add = lambda *args, **kwargs: 1

    gdk_mod = types.ModuleType("gi.repository.Gdk")
    gdk_mod.Display = type("Display", (), {"get_default": staticmethod(lambda: None)})

    gobject_mod = types.ModuleType("gi.repository.GObject")
    gobject_mod.SignalFlags = type("SignalFlags", (), {"RUN_FIRST": 1})

    for name, module in {
        "Gtk": gtk_mod,
        "Adw": adw_mod,
        "Gio": gio_mod,
        "GLib": glib_mod,
        "GObject": gobject_mod,
        "Gdk": gdk_mod,
    }.items():
        setattr(repo_mod, name, module)
        sys.modules[f"gi.repository.{name}"] = module

    gi_mod.repository = repo_mod
    gi_mod.require_version = lambda *args, **kwargs: None
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repo_mod

    try:
        yield importlib.import_module(module_name)
    finally:
        for name in managed:
            sys.modules.pop(name, None)
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module


class TestConnCheckShouldShow:
    def test_should_show_when_not_offline(self):
        with _import_with_gi_stubs("bootc_installer.defaults.conn_check") as mod:
            assert mod.BootcDefaultConnCheck.should_show(SimpleNamespace(), {}) is True

    def test_should_hide_for_offline_install(self):
        with _import_with_gi_stubs("bootc_installer.defaults.conn_check") as mod:
            assert mod.BootcDefaultConnCheck.should_show(
                SimpleNamespace(), {"offline_install": True}
            ) is False
