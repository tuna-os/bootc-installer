"""Unit tests for the pure-Python logic in defaults/network.py.

network.py imports GTK and NetworkManager (NM) at the module level.
We stub out gi.repository before importing so these tests run without
a display or D-Bus connection.
"""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── Stub out gi.repository ────────────────────────────────────────────────────

def _build_gi_stubs():
    gi_mod = types.ModuleType("gi")
    gi_mod._stubbed = True
    repo_mod = types.ModuleType("gi.repository")

    class _Template:
        def __call__(self, *args, **kwargs):
            return lambda cls: cls

        def Child(self, *args, **kwargs):
            return None

    _template_instance = _Template()

    class _Stub:
        pass

    class _FakeNMClient:
        @staticmethod
        def new():
            return _FakeNMClient()

        def get_devices(self):
            return []

        def connect(self, *args, **kwargs):
            pass

    class _FakeNM:
        Template = _template_instance
        Client = _FakeNMClient
        DeviceType = type("DeviceType", (), {
            "ETHERNET": 1,
            "WIFI": 2,
        })
        DeviceState = type("DeviceState", (), {
            "ACTIVATED": 100,
            "NEED_AUTH": 60,
            "PREPARE": 40,
            "CONFIG": 50,
            "IP_CONFIG": 70,
            "IP_CHECK": 80,
            "SECONDARIES": 90,
            "DISCONNECTED": 30,
            "DEACTIVATING": 110,
            "FAILED": 120,
            "UNKNOWN": 0,
            "UNMANAGED": 10,
            "UNAVAILABLE": 20,
        })
        Device = _Stub
        DeviceWifi = _Stub
        DeviceEthernet = _Stub

    from unittest.mock import MagicMock as _MagicMock
    net_stubs = {}
    for lib in ("Gtk", "Adw", "GLib", "Gio", "Gdk", "NMA4"):
        stub = types.ModuleType(f"gi.repository.{lib}")
        stub.Template = _template_instance
        stub.Bin = _Stub
        stub.Box = _Stub
        stub.Label = _Stub
        stub.Spinner = _Stub
        stub.ActionRow = _Stub
        stub.PreferencesRow = _Stub
        stub.SwitchRow = _Stub
        stub.Orientation = type("Orientation", (), {"HORIZONTAL": 0, "VERTICAL": 1})
        stub.Align = type("Align", (), {"CENTER": 0, "FILL": 1, "START": 2})
        setattr(repo_mod, lib, stub)
        sys.modules[f"gi.repository.{lib}"] = stub
        net_stubs[lib] = stub

    # Adw needs Window for dialog_credits.BootcCreditsWindow(Adw.Window)
    net_stubs["Adw"].Window = _Stub
    net_stubs["Adw"].ExpanderRow = _Stub
    net_stubs["Adw"].PreferencesGroup = _Stub

    # Gio needs ResourceLookupFlags for progress.py GResource lookups
    class _ResourceLookupFlags:
        NONE = 0
    net_stubs["Gio"].ResourceLookupFlags = _ResourceLookupFlags
    net_stubs["Gio"].resources_lookup_data = _MagicMock()
    net_stubs["Gio"].bus_get_sync = _MagicMock()
    net_stubs["Gio"].BusType = types.SimpleNamespace(SYSTEM=0)
    net_stubs["Gio"].DBusCallFlags = types.SimpleNamespace(NONE=0)
    net_stubs["Gio"].File = _MagicMock()

    repo_mod.NM = _FakeNM
    sys.modules["gi.repository.NM"] = _FakeNM

    gi_mod.repository = repo_mod
    gi_mod.require_version = lambda *a, **kw: None
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repo_mod

    # Remove cached bootc_installer modules that were loaded with old stubs.
    for mod_name in list(sys.modules):
        if "bootc_installer" in mod_name and "network" in mod_name:
            del sys.modules[mod_name]


_build_gi_stubs()

from gi.repository import NM

from bootc_installer.defaults.network import (
    AP_SECURITY_TYPES,
    NM_802_11_AP_FLAGS_PRIVACY,
    NM_802_11_AP_SEC_KEY_MGMT_OWE,
    NM_802_11_AP_SEC_KEY_MGMT_OWE_TM,
    NM_802_11_AP_SEC_KEY_MGMT_SAE,
    NM_802_11_AP_SEC_NONE,
    BootcDefaultNetwork,
    WirelessRow,
)

# ── AP_SECURITY_TYPES lookup table ───────────────────────────────────────────────

class TestSecurityTypes:
    """The AP_SECURITY_TYPES map controls which WiFi networks display a lock icon."""

    def test_wpa_is_secure(self):
        secure, _ = AP_SECURITY_TYPES["wpa"]
        assert secure is True

    def test_wpa2_is_secure(self):
        secure, _ = AP_SECURITY_TYPES["wpa2"]
        assert secure is True

    def test_sae_wpa3_is_secure(self):
        secure, _ = AP_SECURITY_TYPES["sae"]
        assert secure is True

    def test_wep_is_insecure(self):
        secure, _ = AP_SECURITY_TYPES["wep"]
        assert secure is False

    def test_none_is_insecure(self):
        # "none" uses (None, None) — open network, no explicit security flag
        secure, _label = AP_SECURITY_TYPES.get("none", (False, ""))
        assert secure is None  # open network

    def test_all_entries_have_label(self):
        for key, (_, label) in AP_SECURITY_TYPES.items():
            if label is not None:
                assert isinstance(label, str) and label, f"Empty label for {key!r}"


# ── get_finals ────────────────────────────────────────────────────────────────

class TestNetworkGetFinals:
    """Network step contributes nothing to the fisherman recipe."""

    def test_get_finals_returns_empty_dict(self):
        from types import SimpleNamespace
        step = SimpleNamespace()
        result = BootcDefaultNetwork.get_finals(step)
        assert result == {}


# ── WirelessRow.__get_security ──────────────────────────────────────────────
# Bypasses __init__/refresh_ui (which touch stubbed-out widget children) by
# building the instance with object.__new__ and only setting the .ap the
# private method actually reads. Mirrors gnome-control-center's security
# classification logic that PyGObject-libnm doesn't expose directly.

class _FakeAP:
    def __init__(self, flags=0, wpa_flags=0, rsn_flags=0, ssid=None, strength=50):
        self._flags = flags
        self._wpa_flags = wpa_flags
        self._rsn_flags = rsn_flags
        self._ssid = ssid
        self._strength = strength

    def get_flags(self):
        return self._flags

    def get_wpa_flags(self):
        return self._wpa_flags

    def get_rsn_flags(self):
        return self._rsn_flags

    def get_strength(self):
        return self._strength

    def get_ssid(self):
        return self._ssid


def _make_wireless_row(ap, device=None):
    row = object.__new__(WirelessRow)
    row.ap = ap
    row.device = device
    return row


class TestWirelessRowSecurity:
    def _security(self, ap):
        return _make_wireless_row(ap)._WirelessRow__get_security()

    def test_open_network(self):
        ap = _FakeAP(flags=0, wpa_flags=NM_802_11_AP_SEC_NONE, rsn_flags=NM_802_11_AP_SEC_NONE)
        assert self._security(ap) == AP_SECURITY_TYPES["none"]

    def test_wep_network(self):
        ap = _FakeAP(
            flags=NM_802_11_AP_FLAGS_PRIVACY,
            wpa_flags=NM_802_11_AP_SEC_NONE,
            rsn_flags=NM_802_11_AP_SEC_NONE,
        )
        assert self._security(ap) == AP_SECURITY_TYPES["wep"]

    def test_wpa_network(self):
        ap = _FakeAP(flags=NM_802_11_AP_FLAGS_PRIVACY, wpa_flags=1, rsn_flags=1)
        assert self._security(ap) == AP_SECURITY_TYPES["wpa"]

    def test_sae_wpa3_network(self):
        ap = _FakeAP(
            flags=NM_802_11_AP_FLAGS_PRIVACY,
            wpa_flags=0,
            rsn_flags=NM_802_11_AP_SEC_KEY_MGMT_SAE,
        )
        assert self._security(ap) == AP_SECURITY_TYPES["sae"]

    def test_owe_network(self):
        ap = _FakeAP(
            flags=NM_802_11_AP_FLAGS_PRIVACY,
            wpa_flags=0,
            rsn_flags=NM_802_11_AP_SEC_KEY_MGMT_OWE,
        )
        assert self._security(ap) == AP_SECURITY_TYPES["owe"]

    def test_owe_transition_mode_network(self):
        ap = _FakeAP(
            flags=NM_802_11_AP_FLAGS_PRIVACY,
            wpa_flags=0,
            rsn_flags=NM_802_11_AP_SEC_KEY_MGMT_OWE_TM,
        )
        assert self._security(ap) == AP_SECURITY_TYPES["owe_tm"]

    def test_falls_back_to_wpa2(self):
        # Mixed wpa/rsn (one set, one NONE) skips the open/WEP/WPA branches
        # and carries no SAE/OWE rsn bits, so it lands on the wpa2 default.
        ap = _FakeAP(flags=NM_802_11_AP_FLAGS_PRIVACY, wpa_flags=1, rsn_flags=0)
        assert self._security(ap) == AP_SECURITY_TYPES["wpa2"]


class TestWirelessRowProperties:
    def test_ssid_decodes_bytes(self):
        fake_ssid = types.SimpleNamespace(get_data=lambda: b"MyNetwork")
        row = _make_wireless_row(_FakeAP(ssid=fake_ssid))
        assert row.ssid == "MyNetwork"

    def test_ssid_empty_when_none(self):
        row = _make_wireless_row(_FakeAP(ssid=None))
        assert row.ssid == ""

    def test_signal_strength_reads_ap(self):
        row = _make_wireless_row(_FakeAP(strength=73))
        assert row.signal_strength == 73

    def test_connected_true_when_active_connection_matches_ssid(self):
        fake_ssid = types.SimpleNamespace(get_data=lambda: b"Home")
        ap = _FakeAP(ssid=fake_ssid)
        active_conn = types.SimpleNamespace(get_id=lambda: "Home")
        device = types.SimpleNamespace(get_active_connection=lambda: active_conn)
        row = _make_wireless_row(ap, device=device)
        assert row.connected is True

    def test_connected_false_when_no_active_connection(self):
        fake_ssid = types.SimpleNamespace(get_data=lambda: b"Home")
        ap = _FakeAP(ssid=fake_ssid)
        device = types.SimpleNamespace(get_active_connection=lambda: None)
        row = _make_wireless_row(ap, device=device)
        assert row.connected is False

    def test_connected_false_when_active_connection_is_different_ssid(self):
        fake_ssid = types.SimpleNamespace(get_data=lambda: b"Home")
        ap = _FakeAP(ssid=fake_ssid)
        active_conn = types.SimpleNamespace(get_id=lambda: "OtherNetwork")
        device = types.SimpleNamespace(get_active_connection=lambda: active_conn)
        row = _make_wireless_row(ap, device=device)
        assert row.connected is False


# ── BootcDefaultNetwork.__device_status ─────────────────────────────────────
# The method reads only its `conn` argument (not self), so it can be called
# unbound without constructing the widget-backed instance at all.

class _FakeDevice:
    def __init__(self, state, speed=100):
        self._state = state
        self._speed = speed

    def get_state(self):
        return self._state

    def get_speed(self):
        return self._speed


_device_status = BootcDefaultNetwork._BootcDefaultNetwork__device_status


class TestDeviceStatus:
    def test_activated_is_connected(self):
        status, connected = _device_status(None, _FakeDevice(NM.DeviceState.ACTIVATED))
        assert connected is True
        assert status == "Connected"

    def test_need_auth(self):
        status, connected = _device_status(None, _FakeDevice(NM.DeviceState.NEED_AUTH))
        assert connected is False
        assert status == "Authentication required"

    def test_connecting_states_grouped(self):
        for state in (
            NM.DeviceState.PREPARE,
            NM.DeviceState.CONFIG,
            NM.DeviceState.IP_CONFIG,
            NM.DeviceState.IP_CHECK,
            NM.DeviceState.SECONDARIES,
        ):
            status, connected = _device_status(None, _FakeDevice(state))
            assert connected is False
            assert status == "Connecting"

    def test_disconnected(self):
        status, connected = _device_status(None, _FakeDevice(NM.DeviceState.DISCONNECTED))
        assert status == "Disconnected"
        assert connected is False

    def test_deactivating(self):
        status, _connected = _device_status(None, _FakeDevice(NM.DeviceState.DEACTIVATING))
        assert status == "Disconnecting"

    def test_failed(self):
        status, _connected = _device_status(None, _FakeDevice(NM.DeviceState.FAILED))
        assert status == "Connection Failed"

    def test_unmanaged(self):
        status, _connected = _device_status(None, _FakeDevice(NM.DeviceState.UNMANAGED))
        assert status == "Unmanaged"

    def test_unavailable(self):
        status, _connected = _device_status(None, _FakeDevice(NM.DeviceState.UNAVAILABLE))
        assert status == "Unavailable"

    def test_unknown_state_falls_through_to_default(self):
        status, _connected = _device_status(None, _FakeDevice(NM.DeviceState.UNKNOWN))
        assert status == "Status Unknown"

    def test_unrecognized_state_hits_wildcard(self):
        status, connected = _device_status(None, _FakeDevice(9999))
        assert status == "Unknown"
        assert connected is False


# ── BootcDefaultNetwork.__sorted_wireless_children ──────────────────────────
# Sort order: connected first, then strongest signal, then alphabetical ssid.

class _FakeRow:
    def __init__(self, ssid, signal_strength, connected):
        self.ssid = ssid
        self.signal_strength = signal_strength
        self.connected = connected


class TestSortedWirelessChildren:
    def _sorted(self, rows_by_ssid):
        instance = object.__new__(BootcDefaultNetwork)
        instance._BootcDefaultNetwork__wireless_children = {
            ssid: (row, False) for ssid, row in rows_by_ssid.items()
        }
        return instance._BootcDefaultNetwork__sorted_wireless_children

    def test_connected_network_sorts_first(self):
        rows = {
            "Weak": _FakeRow("Weak", 90, False),
            "Home": _FakeRow("Home", 10, True),
        }
        result = self._sorted(rows)
        assert [r.ssid for r in result] == ["Home", "Weak"]

    def test_stronger_signal_sorts_first_when_neither_connected(self):
        rows = {
            "Far": _FakeRow("Far", 20, False),
            "Near": _FakeRow("Near", 90, False),
        }
        result = self._sorted(rows)
        assert [r.ssid for r in result] == ["Near", "Far"]

    def test_alphabetical_tiebreak_is_descending(self):
        # multisort's specs all pass reverse=True, including for "ssid" —
        # so the alphabetical tiebreak sorts Z-to-A, not A-to-Z.
        rows = {
            "Zeta": _FakeRow("Zeta", 50, False),
            "Alpha": _FakeRow("Alpha", 50, False),
        }
        result = self._sorted(rows)
        assert [r.ssid for r in result] == ["Zeta", "Alpha"]
