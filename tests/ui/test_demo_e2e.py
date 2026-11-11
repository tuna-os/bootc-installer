"""GTK integration coverage for demo-mode end-to-end flows."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib  # noqa: E402

from bootc_shared.branding import COPY_DEFAULTS  # noqa: E402
from bootc_installer.windows.main_window import BootcWindow  # noqa: E402

_RECIPE_PATH = Path(__file__).resolve().parents[2] / "recipe.json"


def _pump():
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, **_kwargs):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


class _TimeoutQueue:
    def __init__(self):
        self.pending = []

    def add(self, *args):
        callback = None
        callback_args = ()
        for index, value in enumerate(args):
            if callable(value):
                callback = value
                callback_args = args[index + 1:]
                break
        if callback is None:
            raise AssertionError(f"could not identify callback in GLib timeout args: {args!r}")
        self.pending.append((callback, callback_args))
        return len(self.pending)

    def add_seconds(self, _delay, _callback, *_args):
        return 1

    def drain(self, limit=64):
        for _ in range(limit):
            _pump()
            if not self.pending:
                return
            callback, args = self.pending.pop(0)
            callback(*args)
        raise AssertionError("timed out waiting for queued GTK callbacks")


class _FakeDisksManager:
    error = None

    def __init__(self):
        self._disks = [
            SimpleNamespace(
                display_name="Demo Disk",
                disk="/dev/vda",
                pretty_size="128 GB",
                size=128 * 1024**3,
                is_removable=False,
            )
        ]

    def all_disks(self):
        return list(self._disks)


def _make_window(extra_env):
    scheduler = _TimeoutQueue()
    app = Adw.Application(
        application_id="org.bootcinstaller.InstallerTest",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )

    env = {
        "BOOTC_CUSTOM_RECIPE": str(_RECIPE_PATH),
        **extra_env,
    }

    patchers = [
        patch.dict(os.environ, env, clear=False),
        patch("bootc_installer.defaults.disk.DisksManager", return_value=_FakeDisksManager()),
        patch("bootc_installer.views.progress.threading.Thread", _ImmediateThread),
        patch("bootc_installer.windows.main_window.GLib.idle_add", side_effect=scheduler.add),
        patch("bootc_installer.windows.main_window.GLib.timeout_add", side_effect=scheduler.add),
        patch("bootc_installer.views.progress.GLib.timeout_add", side_effect=scheduler.add),
        patch.object(GLib, "timeout_add_seconds", side_effect=scheduler.add_seconds),
        # Prevent CompanionServer from starting a real HTTPS server (openssl subprocess + port bind)
        # (the server also does the route lookup, so no socket call either)
        patch("bootc_installer.defaults.qr_companion.CompanionServer"),
    ]

    for patcher in patchers:
        patcher.start()

    try:
        window = BootcWindow(application=app)
        window.present()
        _pump()
    except Exception:
        for patcher in reversed(patchers):
            patcher.stop()
        raise

    return window, scheduler, patchers


def _view(window, name):
    return getattr(window, f"_BootcWindow__view_{name}")


def _stop(window, patchers):
    window.destroy()
    _pump()
    for patcher in reversed(patchers):
        patcher.stop()


class _Criticals:
    """Records CRITICAL messages of a GLib log domain while active.

    adw_carousel_remove() on a widget that is not a page is a
    g_return_if_fail(): it logs and raises nothing (#353)."""

    def __init__(self, domain):
        self.domain = domain
        self.messages = []
        self._handler = None

    def __enter__(self):
        def record(_domain, _level, message, *_args):
            self.messages.append(message)
        self._handler = GLib.log_set_handler(
            self.domain, GLib.LogLevelFlags.LEVEL_CRITICAL, record, None)
        return self

    def __exit__(self, *exc):
        GLib.log_remove_handler(self.domain, self._handler)
        return False


class TestDemoEndToEnd:
    def test_bootc_demo_and_bootc_test_reach_done_screen(self):
        # The product name comes from branding.json, then os-release; pin it
        # so the assertion does not depend on the runner's distribution.
        window, scheduler, patchers = _make_window({
            "BOOTC_DEMO": "1",
            "BOOTC_TEST": "1",
            "BOOTC_INSTALLER_PRODUCT_NAME": "Marlin",
        })

        try:
            builder = getattr(window, "_BootcWindow__builder")
            for step in builder.widgets:
                step.test_auto_advance()
                _pump()
                scheduler.drain()

            window.update_finals()
            _view(window, "confirm").test_auto_advance()
            scheduler.drain()

            done = _view(window, "done")
            assert done.page_header.title == "Marlin is installed"
            assert done.page_header.subtitle == COPY_DEFAULTS["done_subtitle"]
        finally:
            window.destroy()
            _pump()
            for patcher in reversed(patchers):
                patcher.stop()

    def test_a_destroyed_window_does_not_drive_itself(self):
        """#353. BOOTC_TEST advances each page that the carousel shows,
        through the GLib.timeout_add that these tests replace for the whole
        process. A window the previous test destroyed still got
        page-changed; its carousel has no size, so every scroll_to() landed
        on page 0 again, page 0 advanced again, and the next test's queue
        never emptied. Here the late event is a scroll on the destroyed
        window; the connection check is skipped so the chain is not stopped
        by the network of the machine that runs the tests."""
        window, scheduler, patchers = _make_window({
            "BOOTC_DEMO": "1",
            "BOOTC_TEST": "1",
            "VANILLA_SKIP_CONN_CHECK": "1",
        })
        try:
            scheduler.drain()
            window.destroy()
            _pump()
            scheduler.pending.clear()

            window.carousel.scroll_to(window.carousel.get_nth_page(0), False)
            _pump()
            scheduler.drain()
            assert scheduler.pending == []
        finally:
            _stop(window, patchers)

    def test_a_rebuild_removes_only_pages_the_carousel_has(self):
        """#353. A rebuild removed every step from the carousel, also the
        ones the last build skipped. That logged Adwaita-CRITICAL for each
        skipped step on every Next of the image page."""
        window, scheduler, patchers = _make_window({})
        try:
            scheduler.drain()
            builder = getattr(window, "_BootcWindow__builder")
            pages = {window.carousel.get_nth_page(i)
                     for i in range(window.carousel.get_n_pages())}
            skipped = [w for w in builder.widgets if w not in pages]
            # Without a skipped step this test proves nothing.
            assert skipped, "the bundled recipe no longer skips a step"

            with _Criticals("Adwaita") as criticals:
                window.rebuild_ui_after_image()
                window.rebuild_ui_after_image()
                _pump()
            assert criticals.messages == []
            assert window.carousel.get_nth_page(window.carousel.get_n_pages() - 1) \
                is _view(window, "done")
        finally:
            _stop(window, patchers)

    def test_preview_screen_can_jump_to_confirm(self):
        window, scheduler, patchers = _make_window({"BOOTC_PREVIEW_SCREEN": "confirm"})

        try:
            window._BootcWindow__apply_preview_screen()
            _pump()
            scheduler.drain()
            titles = {
                row.get_title()
                for row in _view(window, "confirm").active_widgets
            }
            assert "Target disk" in titles
            assert "Encryption" in titles
        finally:
            window.destroy()
            _pump()
            for patcher in reversed(patchers):
                patcher.stop()
