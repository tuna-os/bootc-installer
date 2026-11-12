# conn_check.py
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
import socket
import subprocess
from gettext import gettext as _

from gi.repository import Adw, Gtk

from bootc_shared import network

from bootc_installer.utils.run_async import RunAsync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BootcInstaller::Conn_Check")

_IN_FLATPAK = os.path.exists("/.flatpak-info")

# The desktop's own network settings, the first tool the host has: GNOME's
# first, then the others a live image can carry. The same tools as the
# XFCE (core.NETWORK_TOOLS), KDE (region::networkSettingsCommand), COSMIC
# (hardware::network_settings_command) and Niri buttons. A sandbox has none
# of them, so in a Flatpak the script runs on the host.
NETWORK_SETTINGS_SCRIPT = (
    "if command -v gnome-control-center >/dev/null 2>&1; then exec gnome-control-center wifi; "
    "elif command -v nm-connection-editor >/dev/null 2>&1; then exec nm-connection-editor; "
    "elif command -v systemsettings >/dev/null 2>&1; then exec systemsettings kcm_networkmanagement; "
    "elif command -v cosmic-settings >/dev/null 2>&1; then exec cosmic-settings network; "
    "else exit 127; fi"
)


def network_settings_argv(in_flatpak=None) -> list:
    """The command that opens the network settings, on the host in a
    Flatpak (`flatpak-spawn --host`)."""
    if in_flatpak is None:
        in_flatpak = _IN_FLATPAK
    argv = ["sh", "-c", NETWORK_SETTINGS_SCRIPT]
    return (["flatpak-spawn", "--host"] + argv) if in_flatpak else argv


def open_network_settings(in_flatpak=None) -> bool:
    """Start the network settings and do not wait for them. False when the
    command could not start."""
    try:
        subprocess.Popen(network_settings_argv(in_flatpak), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as error:
        logger.warning("Could not open the network settings: %s", error)
        return False
    return True


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/default-conn-check.ui")
class BootcDefaultConnCheck(Adw.Bin):
    __gtype_name__ = "BootcDefaultConnCheck"

    btn_recheck = Gtk.Template.Child()
    btn_network_settings = Gtk.Template.Child()
    page_header = Gtk.Template.Child()

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.__step_num = step["num"]
        self.delta = False

        # Which carousel page was shown before this one, and a counter that
        # drops the answer of a check the user has already left.
        self.__last_index = 0
        self.__going_back = False
        self.__check_run = 0

        # signals
        self.btn_recheck.connect("clicked", self.__on_btn_recheck_clicked)
        self.btn_network_settings.connect("clicked", self.__on_btn_network_settings_clicked)
        self.__window.carousel.connect("page-changed", self.__on_page_changed)

    @property
    def step_id(self):
        return self.__key

    def should_show(self, context: dict) -> bool:
        """Skip connection check when running an offline install (live ISO with baked image)."""
        return not context.get("offline_install", False)

    def get_finals(self):
        return {}

    def test_auto_advance(self):
        """Nothing to press: the page moves on by itself when the check
        passes (BOOTC_TEST and the demo tests call this on every step)."""

    def __is_current(self) -> bool:
        carousel = self.__window.carousel
        return carousel.get_nth_page(int(carousel.get_position())) is self

    def __on_page_changed(self, carousel, idx):
        # The page itself is compared, not the recipe's step number: steps
        # that are not shown (should_show) move every later index, so the
        # number named another page and the check ran on the wrong one, or
        # never.
        idx = int(idx)
        previous, self.__last_index = self.__last_index, idx
        if carousel.get_nth_page(idx) is not self:
            self.__check_run += 1  # the user left; drop a pending answer
            return
        # Reached with Back from a later page: keep going back when the
        # check passes. It used to go forward again, so Back could not
        # pass this page.
        self.__going_back = previous > idx
        self._run_check()

    def _image_to_download(self) -> str:
        """The image of the steps before this page, or "" when none has
        chosen one (the check then uses the shared targets only)."""
        ask = getattr(self.__window, "image_to_download", None)
        try:
            imgref = ask(self) if callable(ask) else ""
        except Exception as error:  # noqa: BLE001 - the check must run anyway
            logger.debug("no image for the connection check: %s", error)
            imgref = ""
        return imgref if isinstance(imgref, str) else ""

    def _run_check(self):
        self.__check_run += 1
        run = self.__check_run
        # Read on the main thread: the registry of the image that the
        # install downloads, when a step before this one has chosen it.
        imgref = self._image_to_download()

        def async_fn():
            # bootc_shared.network, which XFCE also uses: the registry of
            # the image first, then ghcr.io:443, then 8.8.8.8:53 as a plain
            # route probe. The image's own registry is what the install
            # downloads from; a mirror or a private registry can be up
            # when ghcr.io is blocked, and the reverse.
            if network.has_connectivity(imgref, connect=socket.create_connection):
                return True
            logger.error("Connection check failed: could not reach %s", ", ".join(
                f"{host}:{port}" for host, port in network.connectivity_targets(imgref)))
            return False

        def callback(res, *args):
            if run != self.__check_run or not self.__is_current():
                return

            if res:
                if self.__going_back:
                    self.__window.back()
                else:
                    self.__window.next()
                return

            self.page_header.icon_name = "network-wired-disconnected-symbolic"
            self.page_header.title = _("No Internet Connection!")
            self.page_header.subtitle = (
                _("Installer requires an active internet connection")
            )
            self.btn_recheck.set_visible(True)
            self.btn_network_settings.set_visible(True)

        RunAsync(async_fn, callback)

    def __on_btn_network_settings_clicked(self, widget, *args):
        # The user connects there, then presses Check Again.
        open_network_settings()

    def __on_btn_recheck_clicked(self, widget, *args):
        widget.set_visible(False)
        self.btn_network_settings.set_visible(False)
        self.page_header.icon_name = "content-loading-symbolic"
        self.page_header.title = _("Checking Connection")
        self.page_header.subtitle = (
            _("Please wait until the connection check is done")
        )
        self.__going_back = False
        self._run_check()
