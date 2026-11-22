# test_new_pages.py - try-or-install, network, prerelease, eula, rst
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The screens the XFCE frontend was missing (tuna-os/bootc-installer#446):
# each has its page, its skip rule, and its spec id in the readiness stamp.

import types

import pytest

from tuna_installer_xfce import app, core, pages


@pytest.fixture
def win():
    return types.SimpleNamespace(
        region=pages.RegionState(), refresh_nav=lambda: None,
        describe_connectivity=lambda: (False, True),
        source_and_target=lambda: ("", ""))


class TestTryOrInstall:
    def test_try_quits_the_app(self, win):
        quit_calls = []
        application = types.SimpleNamespace(quit=lambda: quit_calls.append(1))
        toplevel = types.SimpleNamespace(get_application=lambda: application)
        page = pages.WelcomePage(win)
        page.get_toplevel = lambda: toplevel
        page.try_btn.clicked()
        assert quit_calls == [1]

    def test_spec_names_and_stamp(self):
        assert app.spec_page("welcome") == "try-or-install"
        assert app.spec_page("no-such-page") == "unknown"

    def test_welcome_reports_welcome_for_atspi(self, win):
        page = pages.WelcomePage(win)
        assert page.get_accessible().get_name() == "Welcome"
        assert page.try_btn.get_accessible().get_name().startswith("Try ")


class TestSkipNavigation:
    def _window(self, shown):
        names = list(app.PAGE_ORDER)
        fake_pages = {}
        for name in names:
            page = types.SimpleNamespace()
            page.should_show = (lambda n: lambda: n in shown)(name)
            fake_pages[name] = page
        return types.SimpleNamespace(
            pages=fake_pages, index=names.index("welcome"),
            stack=types.SimpleNamespace(
                set_visible_child_name=lambda _n: None),
            trawl=types.SimpleNamespace(set_step=lambda _i: None),
            refresh_nav=lambda: None)

    def test_go_skips_hidden_pages(self):
        shown = set(app.PAGE_ORDER) - {"language", "keyboard"}
        win = self._window(shown)

        def fake_enter(i):
            win.index = max(0, min(len(app.PAGE_ORDER) - 1, i))

        win._enter = fake_enter
        app.InstallerWindow.go(win, +1)
        assert app.PAGE_ORDER[win.index] == "timezone"
        app.InstallerWindow.go(win, +1)
        assert app.PAGE_ORDER[win.index] == "network"
        app.InstallerWindow.go(win, -1)
        assert app.PAGE_ORDER[win.index] == "timezone"
        app.InstallerWindow.go(win, -1)
        assert app.PAGE_ORDER[win.index] == "welcome"


class TestNetworkPage:
    def test_skipped_when_nothing_downloads(self, win):
        assert pages.NetworkPage(win).should_show() is False

    def test_shown_when_a_download_is_needed(self, win):
        win.describe_connectivity = lambda: (True, False)
        page = pages.NetworkPage(win)
        assert page.should_show() is True
        assert page.get_accessible().get_name() == "Network"

    def test_blocks_until_online(self, win):
        win.describe_connectivity = lambda: (True, False)
        page = pages.NetworkPage(win)
        page._set(False, "offline")
        assert not page.can_continue()
        page._set(True, "")
        assert page.can_continue()


class TestPrereleasePage:
    def test_stable_skips(self, monkeypatch):
        monkeypatch.setenv("SETUP_OVERRIDE_OS_RELEASE_TYPE", "stable")
        monkeypatch.delenv("SETUP_OVERRIDE_OS_EXPERIMENT", raising=False)
        assert core.show_prerelease() is False
        assert pages.PrereleasePage(types.SimpleNamespace(
            refresh_nav=lambda: None)).should_show() is False

    def test_prerelease_and_experiment_show(self, monkeypatch):
        for value in ("pre-release", "experiment"):
            monkeypatch.setenv("SETUP_OVERRIDE_OS_RELEASE_TYPE", value)
            assert core.show_prerelease() is True

    def test_unknown_counts_as_stable(self, monkeypatch):
        monkeypatch.setenv("SETUP_OVERRIDE_OS_RELEASE_TYPE", "rolling")
        assert core.show_prerelease() is False

    def test_experiment_text_is_shown(self, monkeypatch):
        monkeypatch.setenv("SETUP_OVERRIDE_OS_RELEASE_TYPE", "experiment")
        monkeypatch.setenv("SETUP_OVERRIDE_OS_EXPERIMENT",
                           "Tuna experiment 7: do not feed.")
        page = pages.PrereleasePage(types.SimpleNamespace(
            refresh_nav=lambda: None))
        assert page.should_show() is True


class TestEulaPage:
    def test_missing_eula_skips(self, monkeypatch, tmp_path):
        monkeypatch.setenv(core.EULA_ENV, str(tmp_path / "nope.xml"))
        assert core.find_eula() == ""
        assert pages.EulaPage(types.SimpleNamespace(
            refresh_nav=lambda: None)).should_show() is False

    def test_present_eula_gates_next(self, monkeypatch, tmp_path):
        eula = tmp_path / "eula.xml"
        eula.write_text("Be excellent to each other.")
        monkeypatch.setenv(core.EULA_ENV, str(eula))
        page = pages.EulaPage(types.SimpleNamespace(
            refresh_nav=lambda: None))
        assert page.should_show() is True
        assert not page.can_continue()
        page.accept.set_active(True)
        assert page.can_continue()
        assert page.get_accessible().get_name() == "Terms of use"


class TestRstPage:
    def test_no_rst_skips(self, monkeypatch):
        monkeypatch.setattr(core, "rst_detected", lambda: False)
        assert pages.RstPage(types.SimpleNamespace(
            refresh_nav=lambda: None)).should_show() is False

    def test_rst_warns_and_continues(self, monkeypatch):
        monkeypatch.setattr(core, "rst_detected", lambda: True)
        page = pages.RstPage(types.SimpleNamespace(refresh_nav=lambda: None))
        assert page.should_show() is True
        assert page.get_accessible().get_name() == "Intel RST"
        assert page.can_continue()

    def test_daemon_rst_comes_from_probe(self, monkeypatch):
        monkeypatch.setattr(core, "backend", lambda: "daemon")
        daemon = types.SimpleNamespace(
            probe=lambda: {"intelRst": {"detected": True}})
        monkeypatch.setattr(core, "get_daemon", lambda: daemon)
        assert core.rst_detected() is True

    def test_unreachable_daemon_is_no_rst(self, monkeypatch):
        from tuna_installer_xfce import daemon as daemon_client

        monkeypatch.setattr(core, "backend", lambda: "daemon")

        def fail():
            raise daemon_client.DaemonError("gone")

        monkeypatch.setattr(core, "get_daemon", fail)
        assert core.rst_detected() is False
