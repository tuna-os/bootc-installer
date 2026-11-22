# test_daemon.py - Unit tests for the fishermand Varlink backend
# SPDX-License-Identifier: GPL-3.0-or-later
#
# tuna_installer_xfce.daemon speaks to fishermand (tuna-os/fisherman#512);
# core routes probe/validate/plan through it when the daemon backend is on.
# The mock-daemon tests at the end need build/fishermand and are skipped
# without it.

import os

import pytest

from tuna_installer_xfce import app, core, daemon

# conftest's autouse fixture replaces core.request_plan with a stub for
# every test; capture the real one at import so the backend test below can
# exercise the daemon branch.
_REAL_REQUEST_PLAN = core.request_plan

# ─── socket resolution ───────────────────────────────────────────────────


class TestResolveSockets:
    def test_defaults_are_the_systemd_paths(self):
        sockets = daemon.resolve_sockets()
        assert sockets["fisherman"] == "/run/fisherman/io.tunaos.Fisherman"
        assert sockets["sysinstall"] == "/run/systemd/io.systemd.SysInstall"
        assert sockets["cryptenroll"] == "/run/systemd/io.systemd.CryptEnroll"
        assert sockets["shutdown"] == "/run/systemd/io.systemd.Shutdown"

    def test_socket_dir_uses_interface_names(self):
        sockets = daemon.resolve_sockets(socket_dir="/tmp/x")
        assert sockets["fisherman"] == "/tmp/x/io.tunaos.Fisherman"
        assert sockets["sysinstall"] == "/tmp/x/io.systemd.SysInstall"

    def test_env_var_is_a_socket_dir(self, monkeypatch):
        monkeypatch.setenv(daemon.SOCKET_DIR_ENV, "/tmp/y")
        assert (daemon.resolve_sockets()["fisherman"]
                == "/tmp/y/io.tunaos.Fisherman")

    def test_explicit_paths_win(self, monkeypatch):
        monkeypatch.setenv(daemon.SOCKET_DIR_ENV, "/tmp/y")
        sockets = daemon.resolve_sockets(socket_dir="/tmp/x",
                                         fisherman="/tmp/z/custom")
        assert sockets["fisherman"] == "/tmp/z/custom"
        assert sockets["sysinstall"] == "/tmp/x/io.systemd.SysInstall"

    def test_unknown_sockets_fail(self):
        with pytest.raises(ValueError):
            daemon.resolve_sockets(bogus="/tmp/z")


# ─── recipe mapping ──────────────────────────────────────────────────────

FULL = {"disk": "/dev/sda",
        "encryption": {"type": "tpm2-luks-passphrase", "passphrase": "s3cret"},
        "user": {"username": "tuna", "fullname": "Tuna Test",
                 "password": "hunter2!", "groups": ["wheel", "audio"]},
        "hostname": "tuna-box", "locale": "de_DE.UTF-8",
        "keyboard": {"layout": "de"}, "timezone": "Europe/Berlin",
        "filesystem": "btrfs", "image": "ghcr.io/x/y:z"}


class TestRecipeToConfig:
    def test_maps_types_and_groups(self):
        config = daemon.recipe_to_config(FULL, install_mode="erase")
        assert config == {
            "disk": "/dev/sda", "installMode": "erase",
            "encryption": {"type": "tpm2_luks_passphrase", "passphrase": "s3cret"},
            "user": {"username": "tuna", "fullName": "Tuna Test",
                     "password": "hunter2!", "admin": True},
            "hostname": "tuna-box"}

    def test_defaults_are_unencrypted(self):
        assert daemon.recipe_to_config({}) == {"encryption": {"type": "none"}}

    def test_no_admin_without_wheel(self):
        user = {"username": "u", "groups": ["audio"]}
        config = daemon.recipe_to_config({"user": user})
        assert config["user"]["admin"] is False

    def test_filesystem_and_image_do_not_travel(self):
        config = daemon.recipe_to_config(FULL)
        assert "filesystem" not in config and "image" not in config

class TestRecipeToTarget:
    def test_maps_account_and_region(self):
        assert daemon.recipe_to_target(FULL) == {
            "user": {"username": "tuna", "fullName": "Tuna Test",
                     "password": "hunter2!", "admin": True},
            "hostname": "tuna-box", "locale": "de_DE.UTF-8",
            "keymap": "de", "timeZone": "Europe/Berlin"}

    def test_empty_recipe_sends_nothing(self):
        assert daemon.recipe_to_target({}) == {}


# ─── legacy shape ────────────────────────────────────────────────────────

GATES = [{"id": "ram", "ok": False}, {"id": "cpu", "ok": True},
         {"id": "firmware", "ok": True}]
PROBE = {"protocolVersion": 1,
         "disks": [{"path": "/dev/nvme0n1", "sizeBytes": 512110190592,
                    "sizeLabel": "476.9 GiB", "model": "Mock NVMe",
                    "vendor": "Mockware", "transport": "nvme",
                    "removable": False, "eligible": True,
                    "freeBytes": 512110190592, "minimalSizeBytes": 1,
                    "intelRst": False, "existingData": {"operatingSystems": []}}],
         "tpm": {"present": True, "version": "2.0", "usable": True},
         "intelRst": {"detected": True, "affectedDisks": ["/dev/nvme0n1"]},
         "live": {"isLive": True, "liveImage": "ghcr.io/tuna-os/mock:live"}}


class TestProbeToLegacy:
    def test_disks_have_legacy_labels(self):
        (disk,) = daemon.probe_to_legacy(PROBE, [])["disks"]
        assert (disk["path"], disk["size_label"],
                disk["transport_label"]) == ("/dev/nvme0n1", "476.9 GiB", "NVMe")
        assert disk["removable"] is False

    def test_gates_become_unmet(self):
        legacy = daemon.probe_to_legacy(PROBE, GATES)
        assert legacy["system"]["unmet"] == ["ram"]
        assert legacy["tpm"]["usable"] is True
        assert legacy["live"] == {"is_live": True,
                                  "live_image": "ghcr.io/tuna-os/mock:live"}
        assert legacy["intel_rst"] == {"detected": True,
                                       "affected_disks": ["/dev/nvme0n1"]}

    def test_uefi_gate_missing_means_uefi(self):
        legacy = daemon.probe_to_legacy(PROBE, [{"id": "ram", "ok": True}])
        assert legacy["system"]["uefi"] is True
        assert legacy["system"]["unmet"] == []

    def test_gate_to_unmet_ignores_ok_and_unknown(self):
        assert daemon.gate_to_unmet(
            GATES + [{"id": "gpu", "ok": False}]) == ["ram"]


# ─── event translation ───────────────────────────────────────────────────

class TestDaemonEventToLine:
    def test_step_started_becomes_a_step_line(self):
        line = daemon.daemon_event_to_line(
            {"event": "step_started", "stepId": "partition",
             "stepIndex": 1, "totalSteps": 10, "overallPct": 20,
             "message": "Partitioning"})
        assert line["type"] == "step"
        assert (line["step"], line["overall_pct"]) == (2, 20)

    def test_failed_carries_reason_as_code(self):
        line = daemon.daemon_event_to_line(
            {"event": "failed", "stepId": "partition",
             "message": "repart broke", "reason": "repart_failed",
             "nextAction": "retry"})
        assert line["type"] == "error"
        assert line["code"] == "repart_failed"
        assert line["cleanup"] == "retry"

    def test_complete_is_100(self):
        line = daemon.daemon_event_to_line({"event": "complete"})
        assert line["type"] == "complete" and line["overall_pct"] == 100

    def test_terminal_kinds(self):
        assert daemon.is_terminal({"event": "complete"})
        assert daemon.is_terminal({"event": "failed"})
        assert not daemon.is_terminal({"event": "progress"})


# ─── backend switch ──────────────────────────────────────────────────────

@pytest.fixture
def recipe_backend(monkeypatch):
    monkeypatch.delenv(core.BACKEND_ENV, raising=False)
    core.set_backend("recipe")
    yield
    monkeypatch.delenv(core.BACKEND_ENV, raising=False)
    core.set_backend("recipe")
    core.reset_daemon()


class TestBackend:
    def test_default_is_recipe(self, recipe_backend):
        assert core.backend() == "recipe"

    def test_unknown_backend_fails(self, recipe_backend, monkeypatch):
        with pytest.raises(ValueError):
            core.set_backend("varlink")
        monkeypatch.setenv(core.BACKEND_ENV, "varlink")
        with pytest.raises(ValueError):
            core.backend()

    def test_env_wins_over_flag(self, recipe_backend, monkeypatch):
        core.set_backend("daemon")
        monkeypatch.setenv(core.BACKEND_ENV, "recipe")
        assert core.backend() == "recipe"

    def test_daemon_backend_needs_no_plan_or_source(self, recipe_backend,
                                                    monkeypatch):
        core.set_backend("daemon")
        monkeypatch.setattr(core, "request_plan", _REAL_REQUEST_PLAN)
        assert core.request_plan({}) == (None, "fishermand has no install plan")
        assert core.probe_source([]) is None


class TestParseBackend:
    def test_splits_the_flag_out(self):
        chosen, rest = app.parse_backend(["--backend=daemon", "--g-fatal-x"])
        assert chosen == "daemon" and rest == ["--g-fatal-x"]

    def test_absent_flag_is_none(self):
        assert app.parse_backend(["--g-fatal-x"]) == (None, ["--g-fatal-x"])

    def test_unknown_value_fails(self):
        with pytest.raises(SystemExit):
            app.parse_backend(["--backend=soap"])
