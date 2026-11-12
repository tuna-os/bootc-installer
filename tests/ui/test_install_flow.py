"""The install flow on the real BootcWindow, with the recipe.json the Flatpak ships.

These tests cover the seams where the bugs of #307, #308, #309 and #299
were. The older tests replaced `on_installation_confirmed` with a mock, or
built one page alone, so they could not see them (#321). Here the window,
its pages and their signal connections are the shipped ones. The one thing
replaced is FishermanSession: no test starts a root process.

    xvfb-run -a python3 -m pytest tests/ui/test_install_flow.py -q
"""

import itertools
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib

from bootc_installer.main import BootcInstaller
from bootc_installer.views import progress as progress_mod
from bootc_installer.windows.main_window import BootcWindow

_REPO = Path(__file__).resolve().parents[2]
_RECIPE_PATH = _REPO / "recipe.json"


def _pump():
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


def _wait(condition, timeout=5.0):
    """Run the main loop until `condition()` is true. The timers of the
    progress page are the real ones (200, 300 and 500 ms)."""
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def _settle(seconds):
    _wait(lambda: False, timeout=seconds)


class _FakeSession:
    """Stands in for FishermanSession: counts launches, and exits when the
    test says so. Everything else about the progress page is real."""

    created: ClassVar[list] = []

    def __init__(self, recipe, **kwargs):
        self.recipe = recipe
        self.log_path = kwargs.get("log_path", "")
        self.exit_code = None
        self.launches = 0
        self.reads = 0
        self.terminated = 0
        self.cancel_requests = 0
        self.scrubbed = []
        # What fisherman wrote that the poller has not read yet.
        self.pending_lines = []
        _FakeSession.created.append(self)

    def launch(self):
        self.launches += 1
        return ["fake-fisherman", "-"]

    def poll_process(self):
        return self.exit_code

    def open_log_for_tailing(self):
        return True

    def read_new_lines(self):
        self.reads += 1
        return []

    def drain_remaining(self):
        lines, self.pending_lines = self.pending_lines, []
        return lines

    def scrub_log(self, known_key=""):
        self.scrubbed.append(known_key)
        return True

    def request_cancel(self):
        self.cancel_requests += 1
        # The wrapper dies of the SIGTERM; fisherman itself exits 130.
        self.exit_code = -15
        return True

    def terminate(self):
        self.terminated += 1
        self.exit_code = -15


class _FakeDisksManager:
    error = None

    def __init__(self):
        # Two disks: with one, the wizard selects it and has no disk page.
        self._disks = [
            SimpleNamespace(
                display_name=f"Test Disk {letter}", disk=f"/dev/vd{letter}",
                pretty_size="128 GB", size=128 * 1024**3, is_removable=False,
                model=f"Test Disk {letter}")
            for letter in ("a", "b")
        ]

    def all_disks(self):
        return list(self._disks)


def _view(window, name):
    return getattr(window, f"_BootcWindow__view_{name}")


def _current_page(window):
    carousel = window.carousel
    return carousel.get_nth_page(round(carousel.get_position()))


def _show(window, page):
    window.carousel.scroll_to(page, False)
    assert _wait(lambda: _current_page(window) is page), "the carousel did not move"


class _Flow:
    """A wizard window on the shipped recipe, with a disk chosen."""

    def __init__(self, app, window, patchers):
        self.app = app
        self.window = window
        self._patchers = patchers
        self.confirm = _view(window, "confirm")
        self.progress = _view(window, "progress")
        self.done = _view(window, "done")

    @property
    def sessions(self):
        return _FakeSession.created

    def last_step(self):
        return self.window._BootcWindow__last_step_widget

    def choose_disk(self):
        builder = self.window._BootcWindow__builder
        disk = next(w for w in builder.widgets if getattr(w, "_bootc_step_key", "") == "disk")
        disk._set_auto_partition_recipe(disk._BootcDefaultDisk__disks.all_disks()[0])
        _pump()

    def visit_confirm(self):
        """What the user does: Next on the last step, which is the click
        the window collects the finals on, and the Confirm page shows."""
        self.last_step().btn_next.emit("clicked")
        _pump()
        _show(self.window, self.confirm)

    def leave_confirm(self):
        _show(self.window, self.last_step())

    def click_install(self):
        self.confirm.btn_confirm.emit("clicked")
        _pump()

    def finish(self, exit_code):
        """fisherman exits; wait for the result page."""
        session = self.sessions[-1]
        session.exit_code = exit_code
        assert _wait(lambda: not self.progress.is_running()), "the install did not end"
        assert _wait(lambda: _current_page(self.window) is self.done)
        return session

    def dialog(self):
        return self.window._BootcWindow__open_dialog

    def close(self):
        self.window.destroy()
        self.app.remove_window(self.window)
        _pump()
        for patcher in reversed(self._patchers):
            patcher.stop()


# One application id for each test. Gtk.Application.register() exports the
# application on the session bus at a path made from its id, and GIO has
# no call that removes that export while the process lives. With one id
# for the module, the second register() failed on a machine that has a
# session bus ("An object is already exported ... org.gtk.Application").
_app_ids = itertools.count(1)


@pytest.fixture()
def flow(tmp_path):
    _FakeSession.created = []
    app_id = f"org.bootcinstaller.InstallerFlowTest.t{os.getpid()}n{next(_app_ids)}"
    env = {
        "BOOTC_CUSTOM_RECIPE": str(_RECIPE_PATH),
        "BOOTC_INSTALLER_PRODUCT_NAME": "Marlin",
        "BOOTC_APP_ID": app_id,
    }
    patchers = [
        patch.dict(os.environ, env, clear=False),
        patch("bootc_installer.defaults.disk.DisksManager", return_value=_FakeDisksManager()),
        # The host may lack mkfs.xfs; the probe fails closed (#85).
        patch("bootc_installer.defaults.disk_host.fs_tool_available", return_value=True),
        patch("bootc_installer.defaults.qr_companion.CompanionServer"),
        # The connection-check page moves on by itself; these tests place
        # the carousel themselves.
        patch("bootc_installer.defaults.conn_check.BootcDefaultConnCheck._run_check",
              lambda self: None),
        patch.object(progress_mod, "FishermanSession", _FakeSession),
        patch.object(progress_mod, "_FISHERMAN_LOG_PATH", str(tmp_path / "fisherman-output.log")),
        patch.object(progress_mod, "check_codecs_present",
                     return_value={"vp9": False, "av1": False}),
        patch.object(BootcInstaller, "quit"),
    ]
    for patcher in patchers:
        patcher.start()
    os.environ.pop("BOOTC_DEMO", None)
    os.environ.pop("BOOTC_TEST", None)
    for name in ("BOOTC_DEMO", "BOOTC_TEST", "BOOTC_PREVIEW_SCREEN"):
        assert name not in os.environ
    try:
        # The real application class: it owns the app.quit action and its
        # Ctrl+Q accelerator.
        app = BootcInstaller()
        assert app.get_application_id() == app_id
        # NON_UNIQUE: do not become, or look for, the primary instance.
        app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        app.register()
        window = BootcWindow(application=app)
        window.present()
        _pump()
    except Exception:
        for patcher in reversed(patchers):
            patcher.stop()
        raise
    f = _Flow(app, window, patchers)
    f.choose_disk()
    yield f
    f.close()


class TestShippedRecipe:
    def test_the_wizard_has_the_image_and_connection_pages(self, flow):
        keys = [getattr(flow.window.carousel.get_nth_page(i), "_bootc_step_key", "")
                for i in range(flow.window.carousel.get_n_pages())]
        assert "image" in keys and "conn-check" in keys
        assert keys.index("conn-check") < keys.index("image") < keys.index("disk")


class TestOneInstallAtATime:
    def test_three_visits_to_confirm_and_one_click_start_one_install(self, flow):
        """#308. Each visit connected one more handler to the button, and
        the click removed only the newest: two fisherman processes."""
        for _ in range(2):
            flow.visit_confirm()
            flow.leave_confirm()
        flow.visit_confirm()

        flow.click_install()

        assert len(flow.sessions) == 1
        assert flow.sessions[0].launches == 1
        assert flow.sessions[0].recipe["disk"] == "/dev/vda"
        assert _wait(lambda: _current_page(flow.window) is flow.progress)

    def test_a_second_click_while_the_install_runs_starts_nothing(self, flow):
        flow.visit_confirm()
        flow.click_install()
        flow.click_install()
        flow.window.on_installation_confirmed()
        flow.window.retry_installation()

        assert len(flow.sessions) == 1
        assert flow.progress.is_running()

    def test_a_refused_start_leaves_the_button_usable(self, flow):
        """No disk: the window refuses, with a toast. The user corrects the
        problem and the same page must accept the next click."""
        flow.visit_confirm()
        with patch("bootc_installer.windows.main_window.Processor.recipe_names_disk",
                   return_value=False):
            flow.click_install()
        assert flow.sessions == []
        assert _current_page(flow.window) is flow.confirm

        flow.click_install()
        assert len(flow.sessions) == 1


class TestTryAgain:
    def test_try_again_shows_the_progress_page_and_starts_one_session(self, flow):
        """#307. Try Again ran the install behind the failure page, and a
        second click ran a second one."""
        flow.visit_confirm()
        flow.click_install()
        flow.finish(1)
        assert flow.done.btn_retry.get_visible()

        flow.done.btn_retry.emit("clicked")
        _pump()
        flow.done.btn_retry.emit("clicked")
        _pump()

        assert len(flow.sessions) == 2
        assert flow.sessions[1].launches == 1
        assert flow.progress.is_running()
        assert _wait(lambda: _current_page(flow.window) is flow.progress)
        assert flow.progress.btn_cancel.get_visible()

    @pytest.mark.parametrize("code", ["plan_stale", "disk_identity_mismatch"])
    def test_try_again_after_a_stale_plan_plans_again_first(self, flow, code):
        """tuna-os/fisherman#371. The recipe is bound to the plan the
        confirm page showed; after fisherman says the machine no longer
        matches it, the same recipe fails the same way. Try Again goes back
        to the confirm page, which plans again, and starts nothing."""
        flow.visit_confirm()
        flow.click_install()
        flow.sessions[-1].pending_lines = [
            '{"type":"error","message":"the plan changed","code":"%s","field":"planBinding.digest"}\n' % code,
        ]
        flow.finish(1)

        flow.done.btn_retry.emit("clicked")
        _pump()

        assert len(flow.sessions) == 1
        assert _wait(lambda: _current_page(flow.window) is flow.confirm)
        # One more confirmation starts one new install.
        flow.click_install()
        assert len(flow.sessions) == 2

    def test_the_log_poller_stops_when_the_install_ends(self, flow):
        """Each run used to leave a 100 ms timer that read the log for ever."""
        flow.visit_confirm()
        flow.click_install()
        session = flow.sessions[0]
        assert _wait(lambda: session.reads >= 2), "the poller never ran"

        flow.finish(1)
        reads = session.reads
        _settle(0.5)

        assert session.reads == reads

    def test_a_poller_of_the_first_run_does_not_read_for_the_second(self, flow):
        flow.visit_confirm()
        flow.click_install()
        first = flow.finish(1)
        reads = first.reads
        flow.done.btn_retry.emit("clicked")
        assert _wait(lambda: flow.sessions[-1].reads >= 2)

        assert first.reads == reads

    def test_try_again_in_autoinstall_mode_reads_the_recipe_again(self, flow, tmp_path):
        """With --autoinstall there are no wizard finals; Try Again raised."""
        recipe = tmp_path / "auto.json"
        recipe.write_text('{"disk": "/dev/vdb", "image": "registry.example/os:1"}')
        flow.window._BootcWindow__autoinstall_recipe = str(recipe)
        with patch.object(BootcWindow, "_validate_autoinstall_recipe", return_value=""):
            flow.window._start_autoinstall()
            flow.finish(1)
            flow.done.btn_retry.emit("clicked")
            _pump()

        assert [s.recipe["disk"] for s in flow.sessions] == ["/dev/vdb", "/dev/vdb"]
        assert flow.progress.is_running()


class TestExitCodes:
    def _fail_with(self, flow, code):
        flow.visit_confirm()
        flow.click_install()
        flow.finish(code)
        return flow.done.page_header.title, flow.done.page_header.subtitle

    def test_126_says_the_password_prompt_was_closed(self, flow):
        title, subtitle = self._fail_with(flow, 126)
        assert title == "Installation failed"
        assert "password prompt was closed" in subtitle
        assert "Nothing was changed on the disk" in subtitle

    def test_127_says_no_administrator_rights(self, flow):
        title, subtitle = self._fail_with(flow, 127)
        assert title == "Installation failed"
        assert "administrator rights" in subtitle

    def test_130_is_a_cancelled_install_not_a_failure(self, flow):
        title, subtitle = self._fail_with(flow, 130)
        assert title == "Installation cancelled"
        assert "stopped before it finished" in subtitle
        assert flow.done.btn_retry.get_visible()
        assert not flow.done.btn_reboot.get_visible()

    def test_another_code_keeps_the_log_hint(self, flow):
        title, subtitle = self._fail_with(flow, 1)
        assert title == "Installation failed"
        assert "password prompt" not in subtitle
        assert subtitle

    def test_the_error_event_is_the_reason_on_the_failure_page(self, flow, caplog):
        """#64: fisherman's `error` event is shown, and the installer's own
        log gets the exit code, the reason and the end of the output."""
        import logging

        flow.visit_confirm()
        flow.click_install()
        key = "abcd-efgh-ijkl-mnop"
        flow.sessions[-1].pending_lines = [
            '{"type":"step","step":1,"total_steps":9,"step_name":"Preparing disk"}\n',
            '{"type":"recovery_key","key":"%s"}\n' % key,
            "fatal: sfdisk failed to partition disk\n",
            '{"type":"error","message":"target disk vanished","code":"","field":""}\n',
        ]
        with caplog.at_level(logging.ERROR):
            flow.finish(1)
        assert flow.done.page_header.title == "Installation failed"
        # The event wins over the "fatal:" line of the log.
        assert flow.done.page_header.subtitle == "Error: target disk vanished"
        assert flow.progress.last_error["message"] == "target disk vanished"
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "fisherman exited with code 1" in logged
        assert "target disk vanished" in logged
        assert "sfdisk failed to partition disk" in logged
        assert key not in logged

    def test_an_error_event_of_one_install_does_not_reach_the_next(self, flow):
        flow.visit_confirm()
        flow.click_install()
        flow.sessions[-1].pending_lines = ['{"type":"error","message":"first failure"}\n']
        flow.finish(1)
        assert flow.done.page_header.subtitle == "Error: first failure"
        flow.done.btn_retry.emit("clicked")
        _pump()
        assert flow.progress.last_error is None
        flow.finish(1)
        assert "first failure" not in flow.done.page_header.subtitle

    def test_126_keeps_its_own_line_when_there_is_no_event(self, flow):
        title, subtitle = self._fail_with(flow, 126)
        assert "password prompt was closed" in subtitle

    def test_success_shows_the_installed_page(self, flow):
        title, _subtitle = self._fail_with(flow, 0)
        assert title == "Marlin is installed"
        assert flow.done.btn_reboot.get_visible()


class TestQuit:
    def test_ctrl_q_is_the_quit_action(self, flow):
        # main.py binds "<primary>q"; GTK reports it in its own spelling.
        assert flow.app.get_accels_for_action("app.quit") == ["<Control>q"]

    def test_quit_during_an_install_asks_first(self, flow):
        """#309. The action called Application.quit(): the window went,
        fisherman stayed."""
        flow.visit_confirm()
        flow.click_install()

        flow.app.activate_action("quit", None)
        _pump()

        flow.app.quit.assert_not_called()
        assert flow.sessions[0].terminated == 0
        dialog = flow.dialog()
        assert isinstance(dialog, Adw.AlertDialog)
        assert "installation is in progress" in dialog.get_body()

        # A second Ctrl+Q does not stack a second dialog.
        flow.app.activate_action("quit", None)
        _pump()
        assert flow.dialog() is dialog

        dialog.emit("response", "cancel")
        _pump()
        flow.app.quit.assert_not_called()
        assert flow.sessions[0].terminated == 0
        assert flow.progress.is_running()

    def test_a_confirmed_quit_stops_fisherman_before_the_application_goes(self, flow):
        flow.visit_confirm()
        flow.click_install()
        flow.app.activate_action("quit", None)
        _pump()

        flow.dialog().emit("response", "exit")
        _pump()

        assert flow.sessions[0].terminated == 1
        flow.app.quit.assert_called_once()

    def test_quit_on_a_finished_install_needs_no_question(self, flow):
        flow.visit_confirm()
        flow.click_install()
        flow.finish(0)

        flow.app.activate_action("quit", None)
        _pump()

        assert flow.dialog() is None
        flow.app.quit.assert_called_once()

    def test_closing_the_window_takes_the_same_path(self, flow):
        flow.visit_confirm()
        flow.click_install()

        flow.window.close()
        _pump()

        flow.app.quit.assert_not_called()
        assert isinstance(flow.dialog(), Adw.AlertDialog)


class TestCancel:
    def test_cancel_is_shown_only_while_an_install_runs(self, flow):
        assert not flow.progress.btn_cancel.get_visible()
        flow.visit_confirm()
        flow.click_install()
        assert flow.progress.btn_cancel.get_visible()
        flow.finish(1)
        assert not flow.progress.btn_cancel.get_visible()

    def test_cancel_asks_first_and_continue_changes_nothing(self, flow):
        """#299. A stray click must not stop a disk write half-way."""
        flow.visit_confirm()
        flow.click_install()

        flow.progress.btn_cancel.emit("clicked")
        _pump()

        dialog = flow.dialog()
        assert isinstance(dialog, Adw.AlertDialog)
        assert dialog.get_heading() == "Cancel the installation?"
        assert dialog.get_default_response() == "continue"
        assert flow.sessions[0].cancel_requests == 0

        dialog.emit("response", "continue")
        _pump()
        assert flow.sessions[0].cancel_requests == 0
        assert flow.progress.is_running()

    def test_a_confirmed_cancel_shows_the_cancelled_page(self, flow):
        """The wrapper dies of the signal (exit -15), not with 130. After a
        cancel that is a cancelled install too."""
        flow.visit_confirm()
        flow.click_install()
        flow.progress.btn_cancel.emit("clicked")
        _pump()

        flow.dialog().emit("response", "stop")
        _pump()

        assert flow.sessions[0].cancel_requests == 1
        assert _wait(lambda: _current_page(flow.window) is flow.done)
        assert flow.done.page_header.title == "Installation cancelled"
        assert not flow.progress.is_running()

    def test_the_cancelled_heading_is_the_branding_copy_key(self, flow):
        flow.window.recipe["branding"]["copy"]["done_cancelled_title"] = "Stopped."
        flow.visit_confirm()
        flow.click_install()
        flow.finish(130)
        assert flow.done.page_header.title == "Stopped."

    def test_a_cancel_then_try_again_starts_one_new_install(self, flow):
        flow.visit_confirm()
        flow.click_install()
        flow.progress.btn_cancel.emit("clicked")
        _pump()
        flow.dialog().emit("response", "stop")
        assert _wait(lambda: _current_page(flow.window) is flow.done)

        flow.done.btn_retry.emit("clicked")
        _pump()

        assert len(flow.sessions) == 2
        assert not flow.progress.cancel_requested
        flow.finish(1)
        assert flow.done.page_header.title == "Installation failed"


    def _copy_lines(self, name, upto=None):
        cases = json.loads((_REPO / "shared" / "progress" / "source-reuse-cases.json").read_text())
        case = next(c for c in cases["cases"] if c["name"] == name)
        return [json.dumps(e) for e in case["events"][:upto]], case

    def test_during_the_copy_the_question_says_the_disk_does_not_change(self, flow):
        """#267: fisherman copies this computer's system before the first
        step. A cancel then stops the copy; the disk is as it was."""
        flow.visit_confirm()
        flow.click_install()
        lines, case = self._copy_lines("the_cancel_question_during_the_copy")
        for line in lines:
            flow.progress.feed_line(line)
        assert flow.progress.progress_reuse.get_visible()
        assert "copies this computer's system" in flow.progress.progress_reuse.get_label()
        assert flow.progress.progressbar.get_fraction() == 0.0

        flow.progress.btn_cancel.emit("clicked")
        _pump()
        body = flow.dialog().get_body()
        assert "The disk does not change" in body
        assert "can be left without a system" not in body

        flow.dialog().emit("response", "stop")
        session = flow.sessions[0]
        session.exit_code = None
        for line in self._copy_lines("cancelled_copy")[0][2:]:
            flow.progress.feed_line(line)
        assert "removed the copy" in flow.progress.progress_reuse.get_label()
        flow.finish(130)
        assert flow.done.page_header.title == "Installation cancelled"

    def test_after_the_first_step_the_question_warns_about_the_disk(self, flow):
        flow.visit_confirm()
        flow.click_install()
        lines, _ = self._copy_lines("copied_verified_then_installed", upto=4)
        for line in lines:
            flow.progress.feed_line(line)
        flow.progress.btn_cancel.emit("clicked")
        _pump()
        assert "can be left without a system" in flow.dialog().get_body()

    def test_exit_1_after_a_confirmed_cancel_is_a_failure(self, flow):
        """The decided rule (shared/progress/outcome-cases.json): after a
        confirmed cancel only 130 or a signal is the cancel."""
        flow.visit_confirm()
        flow.click_install()
        session = flow.sessions[0]
        session.request_cancel = lambda: True
        flow.progress.btn_cancel.emit("clicked")
        _pump()
        flow.dialog().emit("response", "stop")
        _pump()
        flow.finish(1)
        assert flow.done.page_header.title == "Installation failed"


class TestConfirmSummary:
    def _rows(self, flow):
        return {w.get_title(): w.get_subtitle() for w in flow.confirm.active_widgets
                if hasattr(w, "get_subtitle")}

    def test_a_second_disk_for_var_is_listed_and_named_in_the_warning(self, flow):
        """#313. Two disks were formatted; the page listed one."""
        flow.window.update_finals()
        finals = list(flow.window.finals)
        finals.append({"var_disk": {"disk": "/dev/vdb", "keep_existing": False}})
        flow.confirm.update(finals)

        assert self._rows(flow)["/var disk"] == "/dev/vdb: will be erased"
        warning = flow.confirm.row_warning.get_title()
        assert "/dev/vda and /dev/vdb" in warning

    def test_a_kept_var_disk_is_listed_as_kept_and_not_in_the_warning(self, flow):
        flow.window.update_finals()
        finals = list(flow.window.finals)
        finals.append({"var_disk": {"disk": "/dev/vdb", "keep_existing": True}})
        flow.confirm.update(finals)

        assert self._rows(flow)["/var disk"].startswith("/dev/vdb: kept")
        warning = flow.confirm.row_warning.get_title()
        assert "/dev/vda" in warning and "/dev/vdb" not in warning

    def test_the_account_row_reads_the_user_key(self, flow):
        flow.window.update_finals()
        finals = list(flow.window.finals)
        finals.append({"user": {"username": "ada", "fullname": "Ada L", "password": "x",
                                "groups": []}})
        flow.confirm.update(finals)
        assert self._rows(flow)["Users"] == "ada (Ada L)"

    def test_the_image_row_names_the_image_that_is_installed(self, flow):
        """#314. With an NVIDIA variant the page named the base image."""
        base, nvidia = "registry.example/os:1", "registry.example/os-nvidia:1"
        finals = [{"selected_image": base, "pretty_name": "Example OS",
                   "nvidia_imgref": nvidia}]
        host = "bootc_installer.core.system.Systeminfo."
        with patch(host + "gpu_display_string", return_value=""), \
             patch(host + "has_nvidia_gpu", return_value=False), \
             patch(host + "is_live", return_value=True), \
             patch(host + "offline_images", return_value=[nvidia]):
            flow.confirm.update(finals)
            rows = self._rows(flow)
            assert rows["Image"] == nvidia
            assert rows["Updates follow"] == base

        with patch(host + "gpu_display_string", return_value=""), \
             patch(host + "has_nvidia_gpu", return_value=False), \
             patch(host + "is_live", return_value=False), \
             patch(host + "offline_images", return_value=[]):
            flow.confirm.update(finals)
            rows = self._rows(flow)
            assert rows["Image"] == "Example OS"
            assert "Updates follow" not in rows


class TestRecoveryKeyInTheLog:
    _KEY = "mkta-rdcw-nnhu-fnbx-kwnv-oixz-ahhh-uahf"

    def test_the_log_pane_never_shows_the_key(self, flow):
        """#316. The pane, and Copy Log after it, carried the key."""
        flow.visit_confirm()
        flow.click_install()
        flow.progress.feed_line(json.dumps({"type": "recovery_key", "key": self._KEY}))
        buf = flow.progress.log_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert self._KEY not in text
        assert "[redacted]" in text

    def test_the_key_page_still_gets_the_key_and_the_log_is_scrubbed_on_ack(self, flow):
        flow.window.update_finals()
        flow.window.finals.append({"encryption": {"use_encryption": True, "type": "tpm2-luks"}})
        flow.window.on_installation_confirmed()
        flow.progress.feed_line(json.dumps({"type": "recovery_key", "key": self._KEY}))
        session = flow.sessions[0]
        session.exit_code = 0
        key_page = _view(flow.window, "recovery_key")
        assert _wait(lambda: _current_page(flow.window) is key_page)
        assert key_page.key_label.get_label() == self._KEY
        assert session.scrubbed == []

        key_page.ack_check.set_active(True)
        key_page.btn_continue.emit("clicked")
        _pump()

        assert _wait(lambda: _current_page(flow.window) is flow.done)

    def test_a_failed_install_scrubs_the_log(self, flow):
        flow.visit_confirm()
        flow.click_install()
        flow.progress.feed_line(json.dumps({"type": "recovery_key", "key": self._KEY}))
        session = flow.finish(1)
        assert session.scrubbed == [self._KEY]


class TestAutoinstallRefusal:
    def test_an_unreadable_recipe_starts_nothing_and_says_why(self, flow, tmp_path):
        """#317. The page said only "Installation failed"."""
        path = str(tmp_path / "absent.json")
        flow.window._BootcWindow__autoinstall_recipe = path

        flow.window._start_autoinstall()

        assert flow.sessions == []
        assert _wait(lambda: _current_page(flow.window) is flow.done)
        assert flow.done.page_header.title == "Installation failed"
        assert path in flow.done.page_header.subtitle

    def test_a_recipe_fisherman_rejects_starts_nothing_and_says_why(self, flow, tmp_path):
        recipe = tmp_path / "auto.json"
        recipe.write_text('{"disk": "/dev/vdb", "hostname": "Bad_Name"}')
        flow.window._BootcWindow__autoinstall_recipe = str(recipe)
        result = {"protocol_version": 1, "valid": False, "errors": [
            {"field": "hostname", "code": "no_such_code", "message": "hostname is not valid"}]}

        with patch("bootc_shared.validate.run", return_value=result):
            flow.window._start_autoinstall()

        assert flow.sessions == []
        assert flow.done.page_header.subtitle == "hostname is not valid"
