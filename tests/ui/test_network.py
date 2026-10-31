"""GTK integration coverage for the network step with a mocked NetworkManager."""

import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib


def _pump():
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)


class _FakeAccessPoint:
    def __init__(self, ssid, strength, *, flags=0, wpa_flags=0, rsn_flags=0):
        self._ssid = types.SimpleNamespace(get_data=lambda: ssid.encode("utf-8"))
        self._strength = strength
        self._flags = flags
        self._wpa_flags = wpa_flags
        self._rsn_flags = rsn_flags

    def get_ssid(self):
        return self._ssid

    def get_strength(self):
        return self._strength

    def get_flags(self):
        return self._flags

    def get_wpa_flags(self):
        return self._wpa_flags

    def get_rsn_flags(self):
        return self._rsn_flags


class _FakeDevice:
    def __init__(self, device_type, *, state, speed=0, active=None, access_points=()):
        self._device_type = device_type
        self._state = state
        self._speed = speed
        self._active = active
        self._access_points = list(access_points)
        self.signal_handlers = []
        self.scan_requests = 0

    def is_real(self):
        return True

    def get_device_type(self):
        return self._device_type

    def get_state(self):
        return self._state

    def get_speed(self):
        return self._speed

    def get_active_connection(self):
        return self._active

    def get_access_points(self):
        return list(self._access_points)

    def connect(self, signal, callback):
        self.signal_handlers.append((signal, callback))

    def get_last_scan(self):
        return 0

    def request_scan_async(self):
        self.scan_requests += 1


class _FakeClient:
    def __init__(self, devices):
        self.devices = list(devices)
        self.signal_handlers = []

    def get_devices(self):
        return list(self.devices)

    def connect(self, signal, callback):
        self.signal_handlers.append((signal, callback))


_NETWORK_MODULE = "bootc_installer.defaults.network"
_client_factory = None


def _make_fake_nm():
    fake_nm = types.ModuleType("gi.repository.NM")
    fake_nm.DeviceType = SimpleNamespace(ETHERNET=object(), WIFI=object())
    fake_nm.DeviceState = SimpleNamespace(
        ACTIVATED=100,
        NEED_AUTH=60,
        PREPARE=40,
        CONFIG=50,
        IP_CONFIG=70,
        IP_CHECK=80,
        SECONDARIES=90,
        DISCONNECTED=30,
        DEACTIVATING=110,
        FAILED=120,
        UNKNOWN=0,
        UNMANAGED=10,
        UNAVAILABLE=20,
    )

    class Client:
        @staticmethod
        def new():
            return _client_factory()

    fake_nm.Client = Client
    return fake_nm


_FAKE_NM = _make_fake_nm()


def _load_network(monkeypatch, client_factory):
    """Return network.py bound to a fake NM namespace with real GTK.

    The module is imported at most once per process: re-executing it would
    re-register its @Gtk.Template GObject types (WirelessRow, ...) and fail.
    """
    monkeypatch.setattr(sys.modules[__name__], "_client_factory", client_factory)
    network_module = sys.modules.get(_NETWORK_MODULE)
    if network_module is None:
        from gi import repository

        with monkeypatch.context() as import_patch:
            import_patch.setattr(repository, "NM", _FAKE_NM, raising=False)
            import_patch.setitem(sys.modules, "gi.repository.NM", _FAKE_NM)
            network_module = importlib.import_module(_NETWORK_MODULE)
    monkeypatch.setattr(network_module, "NM", _FAKE_NM)
    return network_module, _FAKE_NM


def test_network_page_renders_mocked_wired_and_wireless_devices(monkeypatch):
    """Real templates render device rows without a D-Bus NetworkManager."""
    # Constants mirror NetworkManager's libnm values used by network.py.
    open_ap = _FakeAccessPoint("Guest", 25)
    home_ap = _FakeAccessPoint("Home", 65, flags=1, wpa_flags=1, rsn_flags=1)
    stronger_home_ap = _FakeAccessPoint("Home", 90, flags=1, wpa_flags=1, rsn_flags=1)
    active_connection = SimpleNamespace(get_id=lambda: "Home")

    # The client is assigned after the fake NM constants are available.
    client = None
    network_module, fake_nm = _load_network(monkeypatch, lambda: client)
    ethernet = _FakeDevice(
        fake_nm.DeviceType.ETHERNET,
        state=fake_nm.DeviceState.ACTIVATED,
        speed=1000,
    )
    wifi = _FakeDevice(
        fake_nm.DeviceType.WIFI,
        state=fake_nm.DeviceState.ACTIVATED,
        active=active_connection,
        access_points=(open_ap, home_ap, stronger_home_ap),
    )
    client = _FakeClient((ethernet, wifi))

    window = SimpleNamespace(carousel=MagicMock(), next=MagicMock())
    step = {"num": 3}
    with patch.object(network_module, "RunAsync") as run_async:
        page = network_module.BootcDefaultNetwork(
            window,
            {"name": "Test OS"},
            "network",
            step,
        )

    _pump()

    rows = page._BootcDefaultNetwork__wireless_children
    assert page.wired_group.get_visible()
    assert page.wireless_group.get_visible()
    assert not page.advanced_group.get_visible()
    assert page.has_eth_connection
    assert page.has_wifi_connection
    assert set(rows) == {"Home", "Guest"}
    assert run_async.call_count == 1

    home = rows["Home"][0]
    guest = rows["Guest"][0]
    assert home.get_title() == "Home"
    assert home.signal_strength == 90
    assert home.signal_icon.get_icon_name() == (
        "network-wireless-signal-excellent-symbolic"
    )
    assert home.secure_icon.get_visible()
    assert home.secure_icon.get_tooltip_text() == "Secure network (WPA)"
    assert home.connected_label.get_visible()
    assert guest.get_title() == "Guest"
    assert guest.signal_icon.get_icon_name() == "network-wireless-signal-weak-symbolic"
    assert not guest.secure_icon.get_visible()
    assert not guest.connected_label.get_visible()
    assert [row.ssid for row in page._BootcDefaultNetwork__sorted_wireless_children] == [
        "Home",
        "Guest",
    ]

    page._BootcDefaultNetwork__try_skip_page(None, step["num"])
    window.next.assert_called_once_with()
    assert client.signal_handlers
    assert wifi.signal_handlers == [("state-changed", page._BootcDefaultNetwork__on_state_changed)]


def test_network_page_keeps_next_hidden_without_connection(monkeypatch):
    """An unavailable network must not enable or skip the page."""
    client = None
    network_module, fake_nm = _load_network(monkeypatch, lambda: client)
    ethernet = _FakeDevice(
        fake_nm.DeviceType.ETHERNET,
        state=fake_nm.DeviceState.UNAVAILABLE,
    )
    wifi = _FakeDevice(
        fake_nm.DeviceType.WIFI,
        state=fake_nm.DeviceState.DISCONNECTED,
    )
    client = _FakeClient((ethernet, wifi))

    window = SimpleNamespace(carousel=MagicMock(), next=MagicMock())
    step = {"num": 3}
    with patch.object(network_module, "RunAsync") as run_async:
        page = network_module.BootcDefaultNetwork(
            window,
            {"name": "Test OS"},
            "network",
            step,
        )

    assert page.wired_group.get_visible()
    assert page.wireless_group.get_visible()
    assert not page.has_eth_connection
    assert not page.has_wifi_connection
    assert not page.btn_next.get_visible()
    assert not page.btn_next.get_sensitive()

    page._BootcDefaultNetwork__try_skip_page(None, step["num"])
    page._BootcDefaultNetwork__try_skip_page(None, step["num"] + 1)
    window.next.assert_not_called()
    assert run_async.call_count == 1
