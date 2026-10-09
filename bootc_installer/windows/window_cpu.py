# window_cpu.py
#
# Copyright 2024 muhdsalm
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

import sys
import subprocess
from gi.repository import Adw, Gtk
from bootc_installer.windows.requirements import requirements_text


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/window-cpu.ui")
class BootcCpuWindow(Adw.Window):
    __gtype_name__ = "BootcCpuWindow"

    btn_continue = Gtk.Template.Child()
    description_label = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # fisherman's unmet requirement (`fisherman probe --json`), in the
        # shared requirements_* copy every frontend shows
        # (shared/probe/README.md).
        self.description_label.set_label(requirements_text("requirements_cpu"))
        self.btn_continue.connect("clicked", self.__continue)

    def __continue(self, btn):
        subprocess.Popen("IGNORE_RAM=1 IGNORE_CPU=1 vanilla-installer", shell=True)
        sys.exit(0)
