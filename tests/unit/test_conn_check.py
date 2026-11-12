"""Unit tests for defaults/conn_check.py without a GTK display."""

import importlib
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class _Template:
    def __call__(self, *args, **kwargs):
        return lambda cls: cls

    def Child(self, *args, **kwargs):
        return None

    def Callback(self, *args, **kwargs):
        return lambda func: func


class _StubBin:
    pass


def _build_gi_stubs():
    gi_mod = types.ModuleType("gi")
    repo_mod = types.ModuleType("gi.repository")

    gtk_mod = types.ModuleType("gi.repository.Gtk")
    gtk_mod.Template = _Template()
    gtk_mod.Box = _StubBin

    adw_mod = types.ModuleType("gi.repository.Adw")
    adw_mod.Bin = _StubBin

    glib_mod = types.ModuleType("gi.repository.GLib")
    glib_mod.idle_add = MagicMock(return_value=1)

    for name, module in {
        "Gtk": gtk_mod,
        "Adw": adw_mod,
        "GLib": glib_mod,
    }.items():
        setattr(repo_mod, name, module)
        sys.modules[f"gi.repository.{name}"] = module

    gi_mod.repository = repo_mod
    gi_mod.require_version = lambda *args, **kwargs: None
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repo_mod


def _import_conn_check_fresh():
    _build_gi_stubs()
    sys.modules.pop("bootc_installer.defaults.conn_check", None)
    try:
        import bootc_installer.defaults as defaults_pkg

        defaults_pkg.__dict__.pop("conn_check", None)
    except Exception:
        pass
    return importlib.import_module("bootc_installer.defaults.conn_check")


class _SyncRunAsync:
    def __init__(self, task_func, callback=None, *args, **kwargs):
        result = task_func(*args, **kwargs)
        if callback is not None:
            callback(result, None)


class TestConnCheckShouldShow(unittest.TestCase):
    def test_should_show_returns_false_for_offline_install(self):
        mod = _import_conn_check_fresh()
        self.assertFalse(
            mod.BootcDefaultConnCheck.should_show(object(), {"offline_install": True})
        )

    def test_should_show_returns_true_for_normal_install(self):
        mod = _import_conn_check_fresh()
        self.assertTrue(mod.BootcDefaultConnCheck.should_show(object(), {}))


class _Carousel:
    """The pages of a wizard and which one is shown."""

    def __init__(self, pages, position=0):
        self.pages = pages
        self.position = position

    def get_position(self):
        return float(self.position)

    def get_nth_page(self, index):
        return self.pages[int(index)]


class TestConnCheckAsyncLogic(unittest.TestCase):
    """The page is at carousel index 2. The recipe's step number is 5: the
    two differ whenever an earlier step is not shown, which is the case
    the old `idx != step_num` test got wrong."""

    def _step(self, mod):
        cls = mod.BootcDefaultConnCheck
        step = cls.__new__(cls)
        pages = ["welcome", "companion", step, "image"]
        self.carousel = _Carousel(pages)
        step._BootcDefaultConnCheck__window = SimpleNamespace(
            next=MagicMock(), back=MagicMock(), carousel=self.carousel)
        step._BootcDefaultConnCheck__step_num = 5
        step._BootcDefaultConnCheck__last_index = 0
        step._BootcDefaultConnCheck__going_back = False
        step._BootcDefaultConnCheck__check_run = 0
        step.page_header = SimpleNamespace(icon_name=None, title=None, subtitle=None)
        step.btn_recheck = MagicMock()
        step.btn_network_settings = MagicMock()
        return step

    def _show(self, step, index):
        self.carousel.position = index
        step._BootcDefaultConnCheck__on_page_changed(self.carousel, float(index))

    def test_conn_check_ignores_other_carousel_pages(self):
        mod = _import_conn_check_fresh()
        step = self._step(mod)

        with patch.object(mod, "RunAsync") as run_async:
            self._show(step, 1)
            self._show(step, 3)

        run_async.assert_not_called()
        step._BootcDefaultConnCheck__window.next.assert_not_called()

    def test_conn_check_runs_on_its_own_page_whatever_the_step_number(self):
        mod = _import_conn_check_fresh()
        step = self._step(mod)
        mock_sock = MagicMock()

        with patch.object(mod, "RunAsync", _SyncRunAsync), patch.object(
            mod.socket, "create_connection", return_value=mock_sock
        ) as create_conn:
            self._show(step, 1)
            self._show(step, 2)

        step._BootcDefaultConnCheck__window.next.assert_called_once_with()
        step._BootcDefaultConnCheck__window.back.assert_not_called()
        create_conn.assert_called()
        mock_sock.close.assert_called_once()
        step.btn_recheck.set_visible.assert_not_called()

    def test_conn_check_failure_updates_header_and_reveals_retry(self):
        mod = _import_conn_check_fresh()
        step = self._step(mod)

        # Both fallback targets fail → connection check returns False.
        with patch.object(mod, "RunAsync", _SyncRunAsync), patch.object(
            mod.socket, "create_connection", side_effect=OSError("offline")
        ):
            self._show(step, 2)

        step._BootcDefaultConnCheck__window.next.assert_not_called()
        self.assertEqual(
            step.page_header.icon_name, "network-wired-disconnected-symbolic"
        )
        self.assertEqual(step.page_header.title, "No Internet Connection!")
        self.assertEqual(
            step.page_header.subtitle,
            "Installer requires an active internet connection",
        )
        step.btn_recheck.set_visible.assert_called_once_with(True)
        step.btn_network_settings.set_visible.assert_called_once_with(True)

    def test_network_settings_opens_the_hosts_tool(self):
        """The offline page offers the desktop's own network settings, as
        the other four frontends do."""
        mod = _import_conn_check_fresh()
        step = self._step(mod)
        with patch.object(mod.subprocess, "Popen") as popen:
            step._BootcDefaultConnCheck__on_btn_network_settings_clicked(MagicMock())
        argv = popen.call_args.args[0]
        self.assertEqual(argv, mod.network_settings_argv())
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_check_again_hides_network_settings_until_the_answer(self):
        mod = _import_conn_check_fresh()
        step = self._step(mod)
        with patch.object(mod, "RunAsync", lambda *a, **kw: None):
            step._BootcDefaultConnCheck__on_btn_recheck_clicked(MagicMock())
        step.btn_network_settings.set_visible.assert_called_once_with(False)

    def test_the_registry_of_the_selected_image_is_probed_first(self):
        """bootc_shared.network: the image's own registry, then ghcr.io,
        then the route probe. GNOME used to probe ghcr.io for every image."""
        mod = _import_conn_check_fresh()
        step = self._step(mod)
        asked = []
        step._BootcDefaultConnCheck__window.image_to_download = (
            lambda page: asked.append(page) or "quay.io/example/os:1")
        tried = []

        def connect(address, timeout):
            tried.append(address)
            if address[0] == "quay.io":
                raise OSError("blocked")
            return MagicMock()

        with patch.object(mod, "RunAsync", _SyncRunAsync), patch.dict(
            os.environ, {}, clear=True
        ), patch.object(mod.socket, "create_connection", side_effect=connect):
            self._show(step, 2)

        self.assertEqual(asked, [step])
        self.assertEqual(tried, [("quay.io", 443), ("ghcr.io", 443)])
        step._BootcDefaultConnCheck__window.next.assert_called_once_with()

    def test_without_an_image_the_shared_targets_are_probed(self):
        mod = _import_conn_check_fresh()
        step = self._step(mod)
        tried = []

        def connect(address, timeout):
            tried.append(address)
            raise OSError("offline")

        for answer in (None, lambda page: 7, lambda page: 1 / 0):
            tried.clear()
            if answer is not None:
                step._BootcDefaultConnCheck__window.image_to_download = answer
            with patch.object(mod, "RunAsync", _SyncRunAsync), patch.dict(
                os.environ, {}, clear=True
            ), patch.object(mod.socket, "create_connection", side_effect=connect):
                self._show(step, 2)
            self.assertEqual(tried, [("ghcr.io", 443), ("8.8.8.8", 53)])

    def test_an_empty_skip_variable_does_not_turn_the_check_off(self):
        mod = _import_conn_check_fresh()
        step = self._step(mod)
        with patch.object(mod, "RunAsync", _SyncRunAsync), patch.dict(
            os.environ, {"VANILLA_SKIP_CONN_CHECK": ""}, clear=True
        ), patch.object(mod.socket, "create_connection",
                        return_value=MagicMock()) as create_conn:
            self._show(step, 2)
        create_conn.assert_called()

    def test_conn_check_skip_env_bypasses_network_request(self):
        mod = _import_conn_check_fresh()
        step = self._step(mod)

        with patch.object(mod, "RunAsync", _SyncRunAsync), patch.dict(
            os.environ, {"VANILLA_SKIP_CONN_CHECK": "1"}, clear=False
        ), patch.object(mod.socket, "create_connection") as create_conn:
            self._show(step, 2)

        step._BootcDefaultConnCheck__window.next.assert_called_once_with()
        create_conn.assert_not_called()

    def test_back_from_a_later_page_keeps_going_back(self):
        """Back from the image page reaches this page, the check passes,
        and the wizard goes back once more. It used to go forward again."""
        mod = _import_conn_check_fresh()
        step = self._step(mod)

        with patch.object(mod, "RunAsync", _SyncRunAsync), patch.object(
            mod.socket, "create_connection", return_value=MagicMock()
        ):
            self._show(step, 3)
            self._show(step, 2)

        step._BootcDefaultConnCheck__window.back.assert_called_once_with()
        step._BootcDefaultConnCheck__window.next.assert_not_called()
        step.btn_recheck.set_visible.assert_not_called()

    def test_answer_that_arrives_after_the_user_left_is_dropped(self):
        mod = _import_conn_check_fresh()
        step = self._step(mod)
        pending = []

        class _Deferred:
            def __init__(self, task_func, callback=None, *a, **kw):
                pending.append((task_func, callback))

        with patch.object(mod, "RunAsync", _Deferred), patch.object(
            mod.socket, "create_connection", return_value=MagicMock()
        ):
            self._show(step, 2)
            self._show(step, 1)          # the user pressed Back meanwhile
            task, callback = pending[0]
            callback(task(), None)

        step._BootcDefaultConnCheck__window.next.assert_not_called()
        step._BootcDefaultConnCheck__window.back.assert_not_called()

    def test_check_again_goes_forward(self):
        mod = _import_conn_check_fresh()
        step = self._step(mod)

        with patch.object(mod, "RunAsync", _SyncRunAsync), patch.object(
            mod.socket, "create_connection", side_effect=OSError("offline")
        ):
            self._show(step, 3)
            self._show(step, 2)          # back, and offline: the page stays
        with patch.object(mod, "RunAsync", _SyncRunAsync), patch.object(
            mod.socket, "create_connection", return_value=MagicMock()
        ):
            step._BootcDefaultConnCheck__on_btn_recheck_clicked(MagicMock())

        step._BootcDefaultConnCheck__window.next.assert_called_once_with()
        step._BootcDefaultConnCheck__window.back.assert_not_called()


class TestNetworkSettingsCommand(unittest.TestCase):
    def test_in_a_flatpak_the_command_runs_on_the_host(self):
        mod = _import_conn_check_fresh()
        argv = mod.network_settings_argv(in_flatpak=True)
        self.assertEqual(argv[:2], ["flatpak-spawn", "--host"])
        self.assertEqual(argv[2:4], ["sh", "-c"])
        self.assertEqual(mod.network_settings_argv(in_flatpak=False),
                         ["sh", "-c", mod.NETWORK_SETTINGS_SCRIPT])

    def test_gnome_settings_first_then_the_other_desktops(self):
        mod = _import_conn_check_fresh()
        script = mod.NETWORK_SETTINGS_SCRIPT
        order = [script.index(tool) for tool in (
            "gnome-control-center wifi", "nm-connection-editor",
            "systemsettings kcm_networkmanagement", "cosmic-settings network")]
        self.assertEqual(order, sorted(order))
        self.assertTrue(script.endswith("else exit 127; fi"))

    def test_a_command_that_cannot_start_is_not_an_error(self):
        mod = _import_conn_check_fresh()
        with patch.object(mod.subprocess, "Popen", side_effect=OSError("no flatpak-spawn")):
            self.assertFalse(mod.open_network_settings(in_flatpak=True))
        with patch.object(mod.subprocess, "Popen") as popen:
            self.assertTrue(mod.open_network_settings(in_flatpak=True))
        self.assertEqual(popen.call_args.args[0][:2], ["flatpak-spawn", "--host"])


if __name__ == "__main__":
    unittest.main()
