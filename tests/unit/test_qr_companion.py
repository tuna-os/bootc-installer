import sys
import types
from unittest.mock import MagicMock

def _build_gi_stubs():
    """Build headless stubs for Adw and Gtk to run tests without a display."""
    class _StubBin:
        def __init__(self, *args, **kwargs):
            pass
        def append(self, widget):
            pass
        def set_child(self, widget):
            pass
        def set_valign(self, val):
            pass
        def set_halign(self, val):
            pass
        def set_margin_top(self, val):
            pass
        def set_margin_bottom(self, val):
            pass
        def set_margin_start(self, val):
            pass
        def set_margin_end(self, val):
            pass
        def set_title(self, val):
            pass
        def set_icon_name(self, val):
            pass
        def set_description(self, val):
            pass
        def set_pixel_size(self, val):
            pass
        def set_use_markup(self, val):
            pass
        def add_css_class(self, val):
            pass
        def set_markup(self, val):
            pass
        def set_from_file(self, val):
            pass
        def set_from_icon_name(self, val):
            pass
        def connect(self, signal, callback, *args):
            pass

    gtk_mod = types.ModuleType("gi.repository.Gtk")
    class _Align:
        CENTER = "center"
    class _Orientation:
        VERTICAL = "vertical"
        HORIZONTAL = "horizontal"
    gtk_mod.Align = _Align
    gtk_mod.Orientation = _Orientation
    gtk_mod.Box = _StubBin
    gtk_mod.Image = _StubBin
    gtk_mod.Label = _StubBin
    gtk_mod.Button = _StubBin

    adw_mod = types.ModuleType("gi.repository.Adw")
    adw_mod.Bin = _StubBin
    adw_mod.StatusPage = _StubBin

    sys.modules["gi.repository.Gtk"] = gtk_mod
    sys.modules["gi.repository.Adw"] = adw_mod
    
    # Mock GLib
    glib_mock = MagicMock()
    sys.modules["gi.repository.GLib"] = glib_mock
    
    # Mock Gio
    gio_mock = MagicMock()
    sys.modules["gi.repository.Gio"] = gio_mock

    # Setup gi parent modules
    gi_mod = types.ModuleType("gi")
    repo_mod = types.ModuleType("gi.repository")
    repo_mod.Gtk = gtk_mod
    repo_mod.Adw = adw_mod
    repo_mod.GLib = glib_mock
    repo_mod.Gio = gio_mock
    gi_mod.repository = repo_mod
    gi_mod.require_version = lambda *a, **kw: None
    
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repo_mod

def test_qr_companion_step_lifecycle():
    """Verify the GUI companion step parses contexts, skips, and resolves finals cleanly."""
    _build_gi_stubs()
    
    window_mock = MagicMock()
    carousel_mock = MagicMock()
    window_mock.carousel = carousel_mock
    
    distro_info = {}
    step = {"num": 2}
    
    # Reload step module cleanly
    sys.modules.pop("bootc_installer.defaults.qr_companion", None)
    from bootc_installer.defaults.qr_companion import BootcDefaultQrCompanion
    
    step_widget = BootcDefaultQrCompanion(window_mock, distro_info, "qr_companion", step)
    
    assert step_widget.step_id == "qr_companion"
    assert step_widget.should_show({}) is True
    
    # Test get_finals when no configuration has been received yet
    window_mock.companion_config = None
    assert step_widget.get_finals() == {}
    
    # Test get_finals when configuration has been populated from phone
    window_mock.companion_config = {
        "fullname": "John Doe",
        "username": "johndoe",
        "password": "mypassword",
        "hostname": "test-host",
        "sshkey": "ssh-rsa ABC"
    }
    assert step_widget.get_finals() == {
        "hostname": "test-host"
    }


def test_page_says_unavailable_when_the_server_cannot_use_https():
    """#185: no certificate, no server, and the page says so instead of
    showing a link to nothing."""
    from unittest.mock import patch

    _build_gi_stubs()
    window_mock = MagicMock()
    sys.modules.pop("bootc_installer.defaults.qr_companion", None)
    from bootc_installer.defaults import qr_companion as mod

    widget = mod.BootcDefaultQrCompanion(window_mock, {}, "qr_companion", {"num": 2})
    widget.link_label = MagicMock()
    widget.qr_image = MagicMock()
    server = MagicMock()
    server.start.return_value = False
    with patch.object(mod, "CompanionServer", return_value=server):
        widget._BootcDefaultQrCompanion__start_companion()

    text = widget.link_label.set_text.call_args[0][0]
    assert "unavailable" in text
    widget.link_label.set_markup.assert_not_called()
    assert widget._BootcDefaultQrCompanion__server is None
