"""The confirm page helps an offline user connect (#301).

It used to say "connect and press Recheck" and stop there. It now offers a
Network settings button that opens the desktop's own tool on the host, and
it still holds the Install button while the image cannot be downloaded.
"""

import os
import subprocess
import sys
import types

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import core, pages  # noqa: E402
from tuna_installer_xfce import locale as locale_checks  # noqa: E402


class _Win:
    def __init__(self):
        self.pages = {
            "destination": types.SimpleNamespace(
                selected_disk=lambda: {"path": "/dev/vdz", "title": "Disk"}),
            "source": types.SimpleNamespace(live_image=""),
        }

    def refresh_nav(self):
        pass

    def build_recipe(self):
        return {"disk": "/dev/vdz", "filesystem": "xfs", "encryption": {"type": "none"},
                "hostname": "box", "image": "quay.io/example/os:1",
                "targetImgref": "quay.io/example/os:1"}

    def check_connectivity(self):
        return True

    def describe_connectivity(self):
        return True, False

    def source_and_target(self):
        return "quay.io/example/os:1", "quay.io/example/os:1"


def _confirm():
    page = pages.ConfirmPage(_Win())
    page.show_all()
    return page


def test_online_shows_no_network_row():
    page = _confirm()
    page._on_net_result(True, False)
    assert page.can_continue()
    assert not page.net_settings.get_visible()
    assert not page.net_recheck.get_visible()
    assert not page.net_row.get_visible()


def test_offline_holds_install_and_offers_network_settings_and_recheck():
    page = _confirm()
    page._on_net_result(False, False)
    assert not page.can_continue()
    assert page.net_row.get_visible()
    assert page.net_settings.get_visible()
    assert page.net_settings.get_label() == "Network settings"
    assert page.net_recheck.get_visible()


def test_network_settings_opens_the_hosts_tool(monkeypatch):
    opened = []
    monkeypatch.setattr(core, "open_network_settings", lambda: opened.append(1) or "tool")
    page = _confirm()
    page._on_net_result(False, False)
    page.net_settings.clicked()
    assert opened == [1]
    assert page.net_row.get_children()[1].get_text() == page.NO_NETWORK


def test_a_host_with_no_tool_says_so(monkeypatch):
    monkeypatch.setattr(core, "open_network_settings", lambda: "")
    page = _confirm()
    page._on_net_result(False, False)
    page.net_settings.clicked()
    assert page.NO_NETWORK_TOOL in page.net_row.get_children()[1].get_text()
    assert not page.can_continue()


def test_the_check_probes_the_registry_of_the_image(monkeypatch):
    monkeypatch.delenv("TUNA_INSTALLER_DRY_RUN", raising=False)
    asked = []

    def has_connectivity(timeout=5, imgref=""):
        asked.append(imgref)
        return True

    class _Thread:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(locale_checks, "has_connectivity", has_connectivity)
    monkeypatch.setattr(pages.threading, "Thread", _Thread)
    page = _confirm()
    page._check_network()
    assert asked == ["quay.io/example/os:1"]


def _host(monkeypatch, present):
    """Stand in for the host: `present` are the tools it has."""
    spawned, looked = [], []

    def host_run(argv, **kwargs):
        looked.append(argv[-1])
        return types.SimpleNamespace(returncode=0 if argv[-1] in present else 1)

    monkeypatch.setattr(core, "host_run", host_run)
    monkeypatch.setattr(core, "host_spawn", spawned.append)
    return spawned, looked


def test_the_first_tool_the_host_has_is_opened(monkeypatch):
    spawned, looked = _host(monkeypatch, {"systemsettings", "cosmic-settings"})
    assert core.open_network_settings() == "systemsettings"
    assert spawned == [["systemsettings", "kcm_networkmanagement"]]
    assert looked == ["nm-connection-editor", "gnome-control-center", "systemsettings"]


def test_xfces_own_tool_is_tried_first(monkeypatch):
    spawned, _ = _host(monkeypatch, {tool[0] for tool in core.NETWORK_TOOLS})
    assert core.open_network_settings() == "nm-connection-editor"
    assert spawned == [["nm-connection-editor"]]


def test_no_tool_is_an_empty_answer_not_an_error(monkeypatch):
    spawned, _ = _host(monkeypatch, set())
    assert core.open_network_settings() == ""
    assert spawned == []

    def broken(argv, **kwargs):
        raise OSError("no sh")

    monkeypatch.setattr(core, "host_run", broken)
    assert core.open_network_settings() == ""


def test_the_tool_runs_on_the_host_from_a_flatpak(monkeypatch):
    started = []
    monkeypatch.setattr(core, "IN_FLATPAK", True)
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: started.append(argv))
    core.host_spawn(["nm-connection-editor"])
    assert started == [["flatpak-spawn", "--host", "nm-connection-editor"]]
