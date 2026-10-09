# window_unsupported.py
#
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

import subprocess
from gi.repository import Adw, Gtk
from bootc_installer.windows.requirements import requirements_text


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/window-unsupported.ui")
class BootcUnsupportedWindow(Adw.Window):
    __gtype_name__ = "BootcUnsupportedWindow"

    btn_poweroff = Gtk.Template.Child()
    description_label = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # fisherman's unmet requirement (`fisherman probe --json`), in the
        # shared requirements_* copy every frontend shows
        # (shared/probe/README.md).
        self.description_label.set_label(requirements_text("requirements_uefi"))
        self.btn_poweroff.connect("clicked", self.__on_poweroff)

    def __on_poweroff(self, btn):
        subprocess.call(["systemctl", "poweroff"])
