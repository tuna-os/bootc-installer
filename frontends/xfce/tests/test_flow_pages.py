# test_flow_pages.py - wipe-or-free, daemon disk list, forced erase, done states
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The install-path screens: the disk list from SysInstall fit, the choice
# between free space and the whole disk, the forced-erase countdown, and
# the done page's Try again / Not now / reboot-failed states.

import types

import pytest

from tuna_installer_xfce import app, core, pages


@pytest.fixture
def win():
    return types.SimpleNamespace(
        region=pages.RegionState(), install_mode="erase",
        refresh_nav=lambda: None)


def _disk(**over):
    row = {"path": "/dev/nvme0n1", "title": "Mock NVMe",
           "size_label": "476.9 GiB", "transport_label": "NVMe",
           "removable": False, "eligible": True,
           "fit": "enough_free_space", "minimal_size_bytes": 1,
           "free_bytes": 512110190592,
           "existing_data": {"operatingSystems": ["Windows"],
                             "partitions": [{"path": "/dev/nvme0n1p1"}],
                             "hasPartitionTable": True, "hasLuks": False}}
    row.update(over)
    return row


class _Daemon:
    def __init__(self, rows=(), error=None):
        self._rows = rows
        self._error = error

    def probe(self):
        return {"disks": [
            {"path": r["path"], "sizeBytes": 1, "sizeLabel": r["size_label"],
             "model": "", "vendor": "", "transport": "",
             "removable": False, "eligible": True,
             "freeBytes": r["free_bytes"],
             "minimalSizeBytes": r["minimal_size_bytes"],
             "intelRst": False, "existingData": r["existing_data"]}
            for r in self._rows]}

    def list_candidates(self):
        if self._error is not None:
            from tuna_installer_xfce import daemon as daemon_client
            raise daemon_client.DaemonError(self._error)
        yield from ({"node": r["path"], "fit": r["fit"]} for r in self._rows)


@pytest.fixture
def daemon_backend(monkeypatch):
    monkeypatch.setattr(core, "backend", lambda: "daemon")
    yield
    core.reset_daemon()


class TestDaemonDiskView:
    def test_eligible_disk_selectable(self, monkeypatch, daemon_backend):
        monkeypatch.setattr(core, "get_daemon", lambda: _Daemon([_disk()]))
        rows, error = core.daemon_disk_view()
        assert error is None
        assert len(rows) == 1
        assert rows[0]["eligible"] is True
        assert rows[0]["fit"] == "enough_free_space"

    def test_too_small_disk_listed_unusable(self, monkeypatch, daemon_backend):
        small = _disk(path="/dev/sdb", eligible=False, fit="disk_too_small",
                      free_bytes=8589934592, minimal_size_bytes=21474836480,
                      existing_data={})
        monkeypatch.setattr(core, "get_daemon", lambda: _Daemon([small]))
        (row,), error = core.daemon_disk_view()
        assert error is None
        assert row["eligible"] is False
        assert row["minimal_size_bytes"] == 21474836480

    def test_probe_failure_is_an_error(self, monkeypatch, daemon_backend):
        from tuna_installer_xfce import daemon as daemon_client

        def fail():
            raise daemon_client.DaemonError("gone")

        monkeypatch.setattr(core, "get_daemon", fail)
        rows, error = core.daemon_disk_view()
        assert rows == [] and error == "gone"


class TestDestinationDaemon:
    def test_unusable_disks_sit_in_a_second_list(self, monkeypatch,
                                                 daemon_backend, win):
        small = _disk(path="/dev/sdb", eligible=False, fit="disk_too_small",
                      free_bytes=8589934592, minimal_size_bytes=21474836480,
                      existing_data={})
        monkeypatch.setattr(core, "get_daemon",
                            lambda: _Daemon([_disk(), small]))
        page = pages.DestinationPage(win)
        page.show_all()
        page.on_enter()
        assert page.selected_disk()["path"] == "/dev/nvme0n1"
        assert page.can_continue()

    def test_empty_state_offers_rescan_and_power_off(self, monkeypatch,
                                                     daemon_backend, win):
        monkeypatch.setattr(core, "get_daemon", lambda: _Daemon([]))
        page = pages.DestinationPage(win)
        page.show_all()
        page.on_enter()
        assert not page.can_continue()


class TestWipePage:
    def _win(self, disk):
        return types.SimpleNamespace(
            region=pages.RegionState(), install_mode="erase",
            refresh_nav=lambda: None,
            pages={"destination": types.SimpleNamespace(
                selected_disk=lambda: disk)})

    def test_tight_disk_skips(self, daemon_backend):
        page = pages.WipePage(self._win(_disk(free_bytes=0)))
        assert page.should_show() is False

    def test_data_and_free_space_shows(self, daemon_backend):
        page = pages.WipePage(self._win(_disk()))
        assert page.should_show() is True
        assert page.get_accessible().get_name() == "Existing data found"
        page.show_all()
        page.on_enter()
        assert "Windows" in page.detail.get_text()

    def test_empty_disk_skips(self, daemon_backend):
        page = pages.WipePage(self._win(_disk(existing_data={})))
        assert page.should_show() is False


    def test_recipe_backend_skips(self, monkeypatch, win):
        monkeypatch.setattr(core, "backend", lambda: "recipe")
        page = pages.WipePage(win)
        assert page.should_show() is False

    def test_choice_sets_install_mode(self, daemon_backend):
        win = self._win(_disk())
        page = pages.WipePage(win)
        page.show_all()
        page.on_enter()
        page.wipe_radio.set_active(True)
        assert win.install_mode == "erase"
        page.free_radio.set_active(True)
        assert win.install_mode == "free_space"


class TestForcedErase:
    def _confirm(self, fit):
        win = types.SimpleNamespace(
            region=pages.RegionState(), refresh_nav=lambda: None,
            pages={"destination": types.SimpleNamespace(
                selected_disk=lambda: _disk(fit=fit))})
        return pages.ConfirmPage(win)

    def test_plain_disk_needs_no_dialog(self, monkeypatch):
        monkeypatch.setattr(core, "backend", lambda: "daemon")
        assert self._confirm("enough_free_space").forced_erase() is False

    @pytest.mark.parametrize("fit", list(core.FORCED_FITS))
    def test_forced_fit_needs_the_countdown(self, monkeypatch, fit):
        monkeypatch.setattr(core, "backend", lambda: "daemon")
        assert self._confirm(fit).forced_erase() is True

    def test_recipe_never_forces(self, monkeypatch):
        monkeypatch.setattr(core, "backend", lambda: "recipe")
        assert self._confirm("insufficient_free_space").forced_erase() is False

    def test_cancel_stays_on_confirm(self, monkeypatch):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        monkeypatch.setattr(core, "backend", lambda: "daemon")
        page = self._confirm("insufficient_free_space")
        monkeypatch.setattr(
            pages.gates, "CountdownEraseDialog",
            lambda *a, **k: types.SimpleNamespace(
                run=lambda: Gtk.ResponseType.CANCEL, destroy=lambda: None))
        assert page.confirm_advance() is False

    def test_countdown_dialog_starts_locked(self):
        import gi
        gi.require_version("Gtk", "3.0")

        dialog = pages.gates.CountdownEraseDialog(None, "/dev/vda")
        assert not dialog.erase_btn.get_sensitive()
        assert "3" in dialog.erase_btn.get_label()
        dialog.destroy()


class TestDoneStates:
    def _done(self):
        return pages.DonePage(types.SimpleNamespace(trawl=types.SimpleNamespace(
            set_fill=lambda _f: None), _enter=lambda _i: None))

    def test_try_again_goes_back_to_confirm(self):
        seen = []
        win = types.SimpleNamespace(
            _enter=seen.append,
            pages={"confirm": object()})
        page = pages.DonePage(win)
        page.show_all()
        page.set_result(False, "tail")
        assert page.try_btn.get_visible()
        page._on_try_again()
        assert seen == [app.PAGE_ORDER.index("confirm")]

    def test_not_now_only_when_installed(self):
        page = self._done()
        page.show_all()
        page.set_result(True, "")
        assert page.not_now_btn.get_visible()
        assert not page.try_btn.get_visible()
        assert page.not_now_btn.get_label() == "Not now"
        assert page.get_accessible().get_name() == "Done"
        page.set_result(False, "tail", cancelled=True)
        assert not page.not_now_btn.get_visible()
        assert page.try_btn.get_visible()
        assert page.try_btn.get_label() == "Try again"

    def test_reboot_failure_shows_inline(self, monkeypatch):
        monkeypatch.setattr(core, "backend", lambda: "recipe")

        def fail(_argv):
            raise OSError("inhibited")

        monkeypatch.setattr(core, "host_run", fail)
        page = self._done()
        page.show_all()
        page.set_result(True, "")
        page._on_reboot()
        assert page.reboot_error.get_text()
