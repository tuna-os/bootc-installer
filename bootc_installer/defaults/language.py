# language.py
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

"""The language step. The selected locale goes into the recipe as
`locale` (#292): the Processor writes it, fisherman sets LANG in the
installed system. With no row selected the recipe has no `locale`, and the
image keeps its own. fisherman checks the name (`validate --partial`)."""

import re
from gi.repository import Adw, Gtk
from bootc_installer.core.languages import all_languages, current_language
from bootc_installer.utils.field_check import ChoiceCheck, drop_focus_inside


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/widget-language.ui")
class LanguageRow(Adw.ActionRow):
    __gtype_name__ = "LanguageRow"

    select_button = Gtk.Template.Child()
    suffix_bin = Gtk.Template.Child()

    def __init__(self, title, subtitle, selected_language, **kwargs):
        super().__init__(**kwargs)
        self.__title = title
        self.__subtitle = subtitle
        self.__selected_language = selected_language

        self.set_title(title)
        self.suffix_bin.set_label(subtitle)

        self.select_button.connect("toggled", self.__on_check_button_toggled)

    def __on_check_button_toggled(self, widget):
        # A radio group: the row that is switched off emits too.
        if hasattr(widget, "get_active") and not widget.get_active():
            return
        self.__selected_language["language_title"] = self.__title
        self.__selected_language["language_subtitle"] = self.__subtitle
        parent = self.get_parent()
        if parent is not None:
            parent.emit("selected-rows-changed")


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/default-language.ui")
class BootcDefaultLanguage(Adw.Bin):
    __gtype_name__ = "BootcDefaultLanguage"

    btn_next = Gtk.Template.Child()
    entry_search_language = Gtk.Template.Child()
    all_languages_group = Gtk.Template.Child()
    problem_label = Gtk.Template.Child()

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        # Per page, made when the page is: not at import, before GTK is up.
        self.search_controller = Gtk.EventControllerKey.new()
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.__language_rows = []
        self.delta = True
        # One dict per page: the rows write into it.
        self.selected_language = {"language_title": None, "language_subtitle": None}
        self.check = ChoiceCheck(window, "locale", self.problem_label,
                                 on_change=self.__language_verify)
        self.__generate_language_list_widgets()
        self.__submit()

        # signals
        self.btn_next.connect("clicked", self.__window.next)
        self.all_languages_group.connect(
            "selected-rows-changed", self.__on_selection_changed
        )
        self.all_languages_group.connect("row-selected", self.__language_verify)
        self.all_languages_group.connect("row-activated", self.__language_verify)
        self.__window.carousel.connect("page-changed", self.__language_verify)

        self.search_controller.connect("key-released", self.__on_search_key_pressed)
        self.entry_search_language.add_controller(self.search_controller)


    def gen_deltas(self):
        for widget in self.__language_rows:
            self.all_languages_group.append(widget)


    def del_deltas(self):
        drop_focus_inside(self)
        self.all_languages_group.remove_all()

    def __submit(self, *args):
        """Ask fisherman about the selected locale."""
        code = self.selected_language["language_subtitle"]
        if code:
            self.check.submit({"locale": code})

    def __on_selection_changed(self, *args):
        self.__submit()
        self.__language_verify()

    def __language_verify(self, *args):
        check = getattr(self, "check", None)
        ok = check is None or check.ok
        self.btn_next.set_sensitive(
            self.selected_language["language_subtitle"] is not None and ok)

    def __generate_language_list_widgets(self):
        for language_code, language_title in all_languages.items():
            language_row = LanguageRow(
                language_title, language_code, self.selected_language
            )

            if len(self.__language_rows) > 0:
                language_row.select_button.set_group(self.__language_rows[0].select_button)

            self.__language_rows.append(language_row)

            if current_language == language_code:
                language_row.select_button.set_active(True)
                self.selected_language["language_title"] = language_title
                self.selected_language["language_subtitle"] = language_code

    def test_auto_advance(self):
        """BOOTC_TEST and the demo tests: move on with what is selected
        now, which may be nothing (the image keeps its own value)."""
        self.__window.next()

    def get_finals(self):
        """`language` is the selected locale ("de_DE.UTF-8"): the recipe's
        `locale`. No key when no row is selected."""
        code = self.selected_language["language_subtitle"]
        return {"language": code} if code else {}

    def __on_search_key_pressed(self, *args):
        keywords = re.sub(
            r"[^a-zA-Z0-9 ]", "", self.entry_search_language.get_text().lower()
        )

        for row in self.all_languages_group:
            row_title = re.sub(r"[^a-zA-Z0-9 ]", "", row.get_title().lower())
            row_subtitle = re.sub(
                r"[^a-zA-Z0-9 ]", "", row.suffix_bin.get_label().lower()
            )
            search_text = row_title + " " + row_subtitle
            row.set_visible(re.search(keywords, search_text, re.IGNORECASE) is not None)
