# main.py
#
# Copyright 2024 mirkobrombin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundationat version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import sys
import os

_debug = os.environ.get("BOOTC_INSTALLER_DEBUG", "").lower() in ("1", "true", "yes")
_log_level = logging.DEBUG if _debug else logging.INFO

_cache_dir = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
    "bootc-installer",
)
os.makedirs(_cache_dir, exist_ok=True)
_log_file = os.path.join(_cache_dir, "installer-debug.log")

logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(_log_file, mode="w"),
    ],
)
logger_boot = logging.getLogger("Installer::Boot")
logger_boot.info(f"Logging to {_log_file}")


def _log_uncaught_exception(exc_type, exc_value, exc_traceback):
    """Route uncaught exceptions into installer-debug.log.

    GTK/GLib signal callbacks route their exceptions through
    sys.excepthook (via PyErr_Print), so without this override a crash
    in a button handler or async callback only ever reaches stderr and
    never lands in the log file users are asked to attach to bug reports.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.getLogger("Installer::Uncaught").critical(
        "Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback)
    )
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


sys.excepthook = _log_uncaught_exception

import gi  # noqa: E402
logger_boot.info("gi imported")

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
logger_boot.info("gi.require_version done")

from gi.repository import Adw, Gio, GLib  # noqa: E402
logger_boot.info("Adw/Gio imported")

from bootc_installer.widgets.page_header import BootcPageHeader  # noqa: E402,F401 - must load before blueprints
logger_boot.info("BootcPageHeader imported")
from bootc_installer.windows.main_window import BootcWindow  # noqa: E402
logger_boot.info("BootcWindow imported")
from bootc_installer.windows.window_unsupported import BootcUnsupportedWindow  # noqa: E402
from bootc_installer.windows.window_ram import BootcRamWindow  # noqa: E402
from bootc_installer.windows.window_cpu import BootcCpuWindow  # noqa: E402
from bootc_installer.core.system import Systeminfo  # noqa: E402
from bootc_shared import readiness  # noqa: E402
logger_boot.info("All imports done")

logger = logging.getLogger("Installer::Main")


def _arm_readiness_frame_gated(win, app_id):
    """Stamp readiness only after the window maps AND a frame paints.

    Niri's frame-swapped stamp (frontends/niri/installer/readiness.go)
    fires on QQuickWindow::frameSwapped — proof a frame reached the
    compositor, strictly stronger than "the widget mapped". GTK exposes no
    present-confirmation, so the closest GTK equivalent is map plus the
    frame clock's first after-paint: a mapped-but-never-drawn window (the
    COSMIC-leg failure mode) writes no stamp, while a window whose toolkit
    never realises one still stamps on map alone.

    Lives here, not in bootc_shared/readiness.py: that module is the one
    that XFCE also imports, and this gating changes no shared semantics —
    map and the stamp format are untouched.
    """
    state = {"mapped": False, "painted": False, "stamped": False}

    def _maybe_stamp(widget):
        if state["stamped"] or not (state["mapped"] and state["painted"]):
            return
        state["stamped"] = True
        readiness.write_stamp(app_id, type(widget).__name__)

    def _on_after_paint(_clock):
        state["painted"] = True
        _maybe_stamp(win)

    def _on_map(widget):
        state["mapped"] = True
        try:
            clock = widget.get_frame_clock()
        except AttributeError:
            clock = None
        if clock is None:
            # Never realised far enough to own a frame clock: fall back to
            # plain map semantics rather than staying silent forever.
            state["painted"] = True
        else:
            clock.connect("after-paint", _on_after_paint)
        _maybe_stamp(widget)

    win.connect("map", _on_map)


class BootcInstaller(Adw.Application):
    """The main application singleton class."""

    def __init__(self):
        logger.info("BootcInstaller.__init__")
        app_id = os.environ.get("BOOTC_APP_ID", "org.bootcinstaller.Installer")
        variant = os.environ.get("BOOTC_VARIANT", "gnome")
        logger.info(f"Running {variant} variant with app_id={app_id}")
        super().__init__(
            application_id=app_id,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.variant = variant
        self.create_action("quit", self.close, ["<primary>q"])
        self._autoinstall_recipe: str | None = None
        # Register --autoinstall option for GApplication option parsing.
        self.add_main_option(
            "autoinstall", ord("a"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING,
            "Skip the wizard and install using RECIPE_JSON directly",
            "RECIPE_JSON",
        )

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()
        if options.contains("autoinstall"):
            self._autoinstall_recipe = options.lookup_value("autoinstall").get_string()
            logger.info(f"--autoinstall mode: recipe={self._autoinstall_recipe}")
        self.activate()
        return 0

    def do_activate(self):
        logger.info("do_activate called")
        win = self.props.active_window
        if not win:
            try:
                logger.info("Checking system requirements")
                if self._autoinstall_recipe:
                    # Skip wizard, go straight to the main window in autoinstall mode.
                    win = BootcWindow(application=self,
                                       autoinstall_recipe=self._autoinstall_recipe)
                elif "IGNORE_RAM" not in os.environ and not Systeminfo.is_ram_enough():
                    logger.info("Not enough RAM")
                    win = BootcRamWindow(application=self)
                elif "IGNORE_CPU" not in os.environ and not Systeminfo.is_cpu_enough():
                    logger.info("Not enough CPU")
                    win = BootcCpuWindow(application=self)
                elif not Systeminfo.is_uefi():
                    logger.info("Not UEFI")
                    win = BootcUnsupportedWindow(application=self)
                else:
                    logger.info("Creating main window")
                    win = BootcWindow(application=self)
                    logger.info("Main window created")
            except Exception:
                logger.exception("Fatal error in do_activate")
                self.quit()
                return

        # Record which window actually MAPS, before presenting it.
        #
        # installer-smoke.yml proves the frontend is up with `flatpak ps`,
        # which answers "is the process alive" — a different question from
        # "did the user get a window", and the two have already diverged: the
        # COSMIC leg ran the process with no window ever appearing and stayed
        # green. It also cannot tell the wizard apart from the RAM, CPU and
        # UEFI windows above, any of which a CI VM can land on while every
        # check passes. The stamp names the class, so the smoke test can
        # require the wizard rather than merely a window.
        _arm_readiness_frame_gated(win, self.props.application_id)

        win.present()

    def create_action(self, name, callback, shortcuts=None):
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
              activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def close(self, *args):
        """The app.quit action (Ctrl+Q).

        The wizard window decides: it asks first, and it stops fisherman
        before the application goes (#309). The other windows (RAM, CPU,
        UEFI) have nothing to lose and quit at once.
        """
        win = self.props.active_window
        request_quit = getattr(win, "request_quit", None)
        if callable(request_quit):
            request_quit()
            return
        self.quit()


def main(version):
    """The application's entry point."""
    logger.info("Creating BootcInstaller instance")
    app = BootcInstaller()
    logger.info("Calling app.run()")
    ret = app.run(sys.argv)
    logger.info("app.run() returned: %s", ret)
    return ret
