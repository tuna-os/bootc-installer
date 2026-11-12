# dialog_poweroff.py
#
# Copyright 2024 mirkobrombin
# Copyright 2024 muqtadir
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

from gi.repository import Adw, Gtk

from bootc_installer.core.system import Systeminfo
# The flatpak sandbox has no systemctl, so a bare call raised
# FileNotFoundError out of the signal handler and every row in this dialog
# did nothing ("Uncaught exception ... __on_firmware_setup", seen on the
# Dakota live ISO). host_systemctl runs it on the host (Scope.HOST).
from bootc_installer.utils.host_actions import host_systemctl as _host_systemctl

logger = logging.getLogger("Installer::PoweroffDialog")


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/dialog-poweroff.ui")
class BootcPoweroffDialog(Adw.Window):
    __gtype_name__ = "BootcPoweroffDialog"

    row_poweroff = Gtk.Template.Child()
    row_reboot = Gtk.Template.Child()
    row_firmware_setup = Gtk.Template.Child()

    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)
        self.set_transient_for(window)

        # signals
        self.row_poweroff.connect("activated", self.__on_poweroff)
        self.row_reboot.connect("activated", self.__on_reboot)
        self.row_firmware_setup.connect("activated", self.__on_firmware_setup)

        self.row_firmware_setup.set_visible(Systeminfo.is_uefi())

    def __on_poweroff(self, btn):
        _host_systemctl("poweroff")

    def __on_reboot(self, btn):
        _host_systemctl("reboot")

    def __on_firmware_setup(self, row):
        _host_systemctl("reboot", "--firmware-setup")