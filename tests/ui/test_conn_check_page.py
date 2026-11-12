"""The connection-check page with its real template: offline, it offers
the desktop's own network settings next to Check Again, as the other four
frontends do."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

from bootc_installer.defaults import conn_check
from bootc_installer.widgets.page_header import BootcPageHeader  # noqa: F401


class _SyncRunAsync:
    def __init__(self, task_func, callback=None, *args, **kwargs):
        callback(task_func(*args, **kwargs), None)


def _offline_page():
    carousel = Adw.Carousel()
    window = SimpleNamespace(carousel=carousel, next=MagicMock(), back=MagicMock())
    page = conn_check.BootcDefaultConnCheck(window, {}, "conn-check", {"num": 0})
    carousel.append(page)
    with patch.object(conn_check, "RunAsync", _SyncRunAsync), patch.object(
            conn_check.socket, "create_connection", side_effect=OSError("offline")):
        page._run_check()
    return page, window


def test_offline_offers_network_settings_and_check_again():
    page, window = _offline_page()
    window.next.assert_not_called()
    assert page.btn_network_settings.get_visible()
    assert page.btn_network_settings.get_label() == "Network settings"
    assert page.btn_recheck.get_visible()


def test_network_settings_runs_the_hosts_tool():
    page, _window = _offline_page()
    with patch.object(conn_check.subprocess, "Popen") as popen:
        page.btn_network_settings.emit("clicked")
    popen.assert_called_once()
    assert popen.call_args.args[0] == conn_check.network_settings_argv()


def test_check_again_hides_both_buttons_while_it_checks():
    page, _window = _offline_page()
    with patch.object(conn_check, "RunAsync", lambda *a, **kw: None):
        page.btn_recheck.emit("clicked")
    assert not page.btn_network_settings.get_visible()
    assert not page.btn_recheck.get_visible()
