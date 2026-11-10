"""The real BootcWindow for tests, built from the shipped recipe.json.

Nothing is stubbed in the window: the Builder, the carousel and every page
are the ones the Flatpak presents. Only the outside world is replaced: the
disks, and the phone companion's server (a recorder, so no test binds a port
or runs openssl).
"""

import contextlib
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SHIPPED_RECIPE = os.path.join(REPO, "recipe.json")


class FakeDisksManager:
    error = None

    def all_disks(self):
        return [SimpleNamespace(display_name="Test Disk", disk="/dev/vda", pretty_size="128 GB",
                                size=128 * 1024**3, is_removable=False)]


class RecordingServer:
    """Stands in for CompanionServer and records when it runs."""

    instances = []
    start_result = True

    def __init__(self, port=8443, host=None):
        self.port = port
        self.host = None
        self.auth_token = None
        self.unavailable_reason = None
        self.running = False
        self.started = 0
        self.stopped = 0
        RecordingServer.instances.append(self)

    def start(self):
        if not RecordingServer.start_result:
            self.unavailable_reason = "no-network"
            return False
        self.host = "192.0.2.10"
        self.auth_token = "window-test-token"
        self.running = True
        self.started += 1
        return True

    def stop(self, wait=False):
        self.running = False
        self.stopped += 1

    @classmethod
    def any_running(cls):
        return any(s.running for s in cls.instances)


def pump(seconds=0.0):
    """Run the main context: everything pending, then for `seconds` more."""
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while ctx.pending() or time.monotonic() < deadline:
        if not ctx.iteration(False):
            time.sleep(0.005)


def wait_for(condition, timeout=8.0, what="condition"):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        pump(0.02)
    pump()


def pages(window):
    return [window.carousel.get_nth_page(i) for i in range(window.carousel.get_n_pages())]


def current_page(window):
    return window.carousel.get_nth_page(int(round(window.carousel.get_position())))


def page_by_key(window, key):
    for page in pages(window):
        if getattr(page, "_bootc_step_key", None) == key:
            return page
    return None


def go(window, step):
    """window.next() or window.back(), then wait for the carousel to arrive."""
    target = int(round(window.carousel.get_position())) + step
    (window.next if step > 0 else window.back)()
    wait_for(lambda: window.carousel.get_position() == float(target),
             what=f"the carousel to reach page {target}")
    return current_page(window)


def shipped_recipe(**image_overrides):
    """recipe.json as shipped, with fields of its first image replaced."""
    with open(SHIPPED_RECIPE, encoding="utf-8") as f:
        recipe = json.load(f)
    if image_overrides:
        recipe.setdefault("images", [{}])
        recipe["images"][0].update(image_overrides)
    return recipe


@contextlib.contextmanager
def real_window(tmp_path, recipe=None):
    """A presented BootcWindow. `recipe` None means recipe.json itself."""
    from bootc_installer.windows.main_window import BootcWindow

    path = SHIPPED_RECIPE
    if recipe is not None:
        recipe = dict(recipe, log_file=str(tmp_path / "installer.log"))
        path = str(tmp_path / "recipe.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(recipe, f)

    RecordingServer.instances = []
    RecordingServer.start_result = True
    env = {"BOOTC_CUSTOM_RECIPE": path, "BOOTC_DEMO": "1",
           "BOOTC_INSTALLER_PRODUCT_NAME": "Example OS"}
    patchers = [
        patch.dict(os.environ, env, clear=False),
        patch("bootc_installer.defaults.disk.DisksManager", return_value=FakeDisksManager()),
        patch("bootc_installer.defaults.qr_companion.CompanionServer", RecordingServer),
    ]
    for p in patchers:
        p.start()
    # patch.dict puts the whole environment back when it stops.
    for name in ("BOOTC_TEST", "BOOTC_PREVIEW_SCREEN", "VANILLA_FORCE_TOUR"):
        os.environ.pop(name, None)
    window = None
    try:
        app = Adw.Application(application_id="org.bootcinstaller.InstallerTest",
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
        window = BootcWindow(application=app)
        window.present()
        pump(0.3)
        yield window
    finally:
        if window is not None:
            # Leave the companion page first, so its poll and server stop.
            with contextlib.suppress(Exception):
                window.carousel.scroll_to(window.carousel.get_nth_page(0), False)
                pump(0.05)
            with contextlib.suppress(Exception):
                window.destroy()
            pump(0.05)
        for p in reversed(patchers):
            p.stop()
