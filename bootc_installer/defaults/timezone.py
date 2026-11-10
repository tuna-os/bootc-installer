# timezone.py
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

"""The time zone step. The selected zone goes into the recipe as
`timezone` (#292), an IANA name ("Europe/Berlin"); fisherman links
/etc/localtime to it in the installed system. A GeoIP guess selects a row
that the user sees before Next. With no row selected the recipe has no
`timezone`, and the image keeps its own."""

import json
import logging
import pathlib
import re
import threading
import unicodedata
from gettext import gettext as _

from gi.repository import Adw, Gio, GLib, Gtk

from bootc_installer.core.timezones import (
    all_timezones,
    get_location,
    get_timezone_preview,
)
from bootc_installer.utils.field_check import ChoiceCheck, drop_focus_inside

logger = logging.getLogger("BootcInstaller::Timezone")


def _load_dinosaurs():
    try:
        data = Gio.resources_lookup_data(
            "/org/bootcinstaller/Installer/data/dinosaurs.json", 0
        )
        return json.loads(data.get_data().decode())
    except Exception:
        dev_path = pathlib.Path(__file__).resolve().parent.parent / "data" / "dinosaurs.json"
        try:
            return json.loads(dev_path.read_text())
        except Exception:
            return {}


_DINOSAURS = _load_dinosaurs()


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/widget-timezone.ui")
class TimezoneRow(Adw.ActionRow):
    __gtype_name__ = "TimezoneRow"

    select_button = Gtk.Template.Child()
    country_label = Gtk.Template.Child()

    def __init__(self, title, subtitle, tz_name, toggled_callback, parent_expander, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.subtitle = subtitle
        self.tz_name = tz_name
        self.parent_expander = parent_expander

        self.set_use_markup(False)
        self.set_title(title)
        self.country_label.set_label(tz_name)

        self.select_button.connect("toggled", toggled_callback, self)
        self.parent_expander.connect("notify::expanded", self.update_time_preview)

    def update_time_preview(self, *args):
        tz_time, tz_date = get_timezone_preview(self.tz_name)
        self.set_subtitle(f"{tz_time} • {tz_date}")


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/default-timezone.ui")
class BootcDefaultTimezone(Adw.Bin):
    __gtype_name__ = "BootcDefaultTimezone"

    btn_next = Gtk.Template.Child()
    entry_search_timezone = Gtk.Template.Child()
    all_timezones_group = Gtk.Template.Child()
    current_tz_label = Gtk.Template.Child()
    current_location_label = Gtk.Template.Child()
    dinosaur_label = Gtk.Template.Child()
    problem_label = Gtk.Template.Child()

    # Countries filled in at each idle callback.
    POPULATE_BATCH = 40


    expanders_list = dict(
        sorted(
            {
                country: region
                for region, countries in all_timezones.items()
                for country in countries.keys()
            }.items()
        )
    )

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        # Per page, made when the page is: not at import, before GTK is up.
        self.search_controller = Gtk.EventControllerKey.new()
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.__step_num = step["num"]
        self.delta = True
        # The selected zone, an IANA name, or None.
        self.selected_timezone = None
        self.check = ChoiceCheck(window, "timezone", self.problem_label,
                                 on_change=self.__update_next)

        # signals
        self.btn_next.connect("clicked", self.__window.next)
        self.__window.carousel.connect("page-changed", self.timezone_verify)

        self.search_controller.connect("key-released", self.__on_search_key_pressed)
        self.entry_search_timezone.add_controller(self.search_controller)


    def gen_deltas(self):
        self.__expanders = []
        self.__tz_entries = []
        self.__generate_timezone_list_widgets()


    def del_deltas(self):
        drop_focus_inside(self)
        self.__tz_entries = []
        for i in self.__expanders:
            self.all_timezones_group.remove(i)
        self.__expanders = []


    def timezone_verify(self, carousel=None, idx=None):
        if idx is not None and idx != self.__step_num:
            return

        def timezone_verify_callback(result, *args):
            # The guess selects a row only while the user has picked none:
            # it must not replace a pick on a second visit.
            if result and self.selected_timezone is None:
                current_city = result.get_city_name()
                current_country = result.get_country_name()
                get_zone = getattr(result, "get_timezone_str", None)
                zone = get_zone() if callable(get_zone) else None
                # The row of the city, else the first row of its zone. The
                # row's own IANA name is what __on_row_toggle stores.
                match = next((entry for entry in self.__tz_entries
                              if current_city == entry.title
                              and current_country == entry.subtitle), None)
                if match is None and isinstance(zone, str) and zone:
                    match = next((entry for entry in self.__tz_entries
                                  if entry.tz_name == zone), None)
                if match is not None:
                    match.select_button.set_active(True)
                    return
            self.__update_next()

        thread = threading.Thread(target=get_location, args=(timezone_verify_callback,))
        thread.start()

    def test_auto_advance(self):
        """BOOTC_TEST and the demo tests: move on with what is selected
        now, which may be nothing (the image keeps its own value)."""
        self.__window.next()

    def get_finals(self):
        """`timezone` is the IANA name of the selected row. No key when no
        row is selected: there is no fallback zone."""
        return {"timezone": self.selected_timezone} if self.selected_timezone else {}

    def __update_next(self, *args):
        check = getattr(self, "check", None)
        ok = check is None or check.ok
        # Next with no row: the image keeps its own zone.
        self.btn_next.set_sensitive(ok)

    def __on_search_key_pressed(self, *args):
        def remove_accents(msg: str):
            out = unicodedata.normalize("NFD", msg).encode("ascii", "ignore").decode("utf-8")
            return str(out)

        search_entry = self.entry_search_timezone.get_text().lower()
        keywords = remove_accents(search_entry)

        if len(keywords) == 0:
            for expander in self.__expanders:
                expander.set_visible(True)
                expander.set_expanded(False)
            return

        current_expander = 0
        current_country = self.__tz_entries[0].subtitle
        visible_entries = 0
        for entry in self.__tz_entries:
            row_title = remove_accents(entry.get_title().lower())
            match = re.search(keywords, row_title, re.IGNORECASE) is not None
            entry.set_visible(match)
            if entry.subtitle != current_country:
                self.__expanders[current_expander].set_expanded(True)
                self.__expanders[current_expander].set_visible(visible_entries != 0)
                visible_entries = 0
                current_country = entry.subtitle
                current_expander += 1
            visible_entries += match

    def __on_row_toggle(self, check_button, widget):
        # A radio group: the row that is switched off emits too.
        if not check_button.get_active():
            return
        self.selected_timezone = widget.tz_name
        self.check.submit({"timezone": widget.tz_name})
        self.current_tz_label.set_label(widget.tz_name)
        self.current_location_label.set_label(_("(at %s, %s)") % (widget.title, widget.subtitle))

        country = widget.subtitle
        dino = _DINOSAURS.get(country)
        if dino:
            self.dinosaur_label.set_markup(
                f"🦴 <i>{dino['name']}</i> — discovered in {dino['location']}"
            )
            self.dinosaur_label.set_visible(True)
        else:
            self.dinosaur_label.set_label("")
            self.dinosaur_label.set_visible(False)

        self.__update_next()

    def __generate_timezone_list_widgets(self):
        def __populate_expander(expander, region, country, *args):
            for city, tzname in all_timezones[region][country].items():
                timezone_row = TimezoneRow(city, country, tzname, self.__on_row_toggle, expander)
                self.__tz_entries.append(timezone_row)
                if len(self.__tz_entries) > 1:
                    timezone_row.select_button.set_group(self.__tz_entries[0].select_button)
                expander.add_row(timezone_row)
                # The rows are new on each visit: show the pick again.
                if tzname == self.selected_timezone:
                    timezone_row.select_button.set_active(True)

        pending = []
        for country, region in self.expanders_list.items():
            if len(all_timezones[region][country]) > 0:
                expander = Adw.ExpanderRow.new()
                # Plain text: "Turks & Caicos Is" is not markup.
                expander.set_use_markup(False)
                expander.set_title(country)
                expander.set_subtitle(region)
                self.all_timezones_group.add(expander)
                self.__expanders.append(expander)
                pending.append((expander, region, country))

        def __populate_some(*args):
            # Some countries at each idle, in order: the page draws at once,
            # and two hundred countries are not two hundred callbacks.
            for _ in range(min(self.POPULATE_BATCH, len(pending))):
                __populate_expander(*pending.pop(0))
            if pending:
                GLib.idle_add(__populate_some)
            return False

        if pending:
            GLib.idle_add(__populate_some)
