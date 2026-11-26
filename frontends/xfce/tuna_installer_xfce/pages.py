"""The bootc installer for XFCE — classic GTK3 wizard. Design: ../DESIGN.md.
Flow and recipe contract: ../../INSTALLER-FRONTENDS.md."""

import json
import os
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango
try:
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi  # noqa: E402
except (ValueError, ImportError):
    Atspi = None

from bootc_shared import completion  # noqa: E402
from bootc_shared import plan as install_plan  # noqa: E402
from bootc_shared import progress as progress_parser  # noqa: E402
from bootc_shared import redact  # noqa: E402
from bootc_shared import source_check  # noqa: E402
from bootc_shared import validate as fisherman_validate  # noqa: E402

from . import core, daemon as daemon_client, gates, locale as locale_checks
from . import tour
from .i18n import _
from .logo import product_logo

# The recipe's encryption types, in display order: fisherman's
# encryption-choices.json (core.ENCRYPTION_CHOICES), which
# tests/unit/test_encryption_choices.py holds to fisherman's own file. What
# each one is called is branding copy, never a literal here.
ENCRYPTION_TYPES = tuple(c["type"] for c in core.ENCRYPTION_CHOICES)


def live_check(on_result):
    """`fisherman validate --json --partial -` for one page: debounced, off
    the UI thread, answered on it (shared/recipe/README.md).

    On the daemon backend the same debounce drives fishermand's Validate
    and ConfigureTarget instead of the fisherman subprocess
    (core.daemon_live_runner)."""
    if core.backend() == "daemon":
        return fisherman_validate.LiveCheck(
            None, on_result, timeout_add=GLib.timeout_add,
            source_remove=GLib.source_remove, idle_add=GLib.idle_add,
            runner=core.daemon_live_runner())
    return fisherman_validate.LiveCheck(
        core.validate_argv(), on_result, timeout_add=GLib.timeout_add,
        source_remove=GLib.source_remove, idle_add=GLib.idle_add)


def problem_label():
    """The line under a field that shows fisherman's problem with it."""
    label = Gtk.Label(xalign=0)
    label.set_line_wrap(True)
    label.set_no_show_all(True)
    label.get_style_context().add_class("error")
    return label


def show_problem(label, problem):
    """Show `problem` (or nothing) in `label`: the copy key
    validate_<code>, or fisherman's message for a code with no copy."""
    if problem is None:
        label.set_text("")
        label.hide()
        return
    label.set_text(fisherman_validate.render(problem, core.BRANDING.text))
    label.show()


def toggle_reveal(entry, *_args):
    """Show or hide what a password entry holds; its icon follows."""
    shown = not entry.get_visibility()
    entry.set_visibility(shown)
    entry.set_icon_from_icon_name(
        Gtk.EntryIconPosition.SECONDARY,
        "view-conceal-symbolic" if shown else "view-reveal-symbolic")
    entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY,
                                _("Hide") if shown else _("Show"))


def password_entry():
    """A hidden entry with a reveal icon: the passphrase, the account
    password and their confirmations all use this one."""
    entry = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD,
                      hexpand=True, width_chars=28, activates_default=True)
    entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY,
                                  "view-reveal-symbolic")
    entry.set_icon_activatable(Gtk.EntryIconPosition.SECONDARY, True)
    entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, _("Show"))
    entry.connect("icon-press", toggle_reveal)
    return entry


def encryption_text(enc_type, suffix):
    """The copy line for an encryption type; suffix is _label or _description
    (shared/branding/README.md, "Encryption choices")."""
    return core.BRANDING.text("encryption_" + enc_type.replace("-", "_") + suffix)


def _page_title(text):
    label = Gtk.Label(xalign=0)
    label.set_markup(f"<big><b>{GLib.markup_escape_text(text)}</b></big>")
    label.set_margin_bottom(12)
    return label


def _warn_row(text):
    box = Gtk.Box(spacing=8)
    box.pack_start(Gtk.Image.new_from_icon_name("dialog-warning", Gtk.IconSize.MENU), False, False, 0)
    lbl = Gtk.Label(label=text, xalign=0)
    lbl.set_line_wrap(True)
    box.pack_start(lbl, True, True, 0)
    return box


def filesystem_label(fs):
    """What a filesystem is called: its id, and for zfs the branding copy
    `filesystem_zfs_label`. fisherman accepts zfs only as experimental
    (the recipe's `experimental`), and the name says so."""
    if fs == "zfs":
        return core.BRANDING.text("filesystem_zfs_label") or fs
    return fs


class Page(Gtk.Box):
    """One wizard page: vertical box, 12px spacing, knows if it can advance."""

    title = ""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                         margin=18)
        self.win = win
        if self.title:
            self.pack_start(_page_title(self.title), False, False, 0)

    def can_continue(self):
        return True

    def on_enter(self):
        pass

    def should_show(self):
        """Whether the wizard stops here. Pages with nothing to say (an
        unneeded network check, a stable release's disclaimer) return
        False, and the window walks past them in both directions."""
        return True


def a11y_name(widget, name):
    """The AT-SPI accessible name for a widget (screens.yaml,
    "accessibility"). GTK3 widgets expose good defaults for plain widgets;
    page roots and action buttons get the spec's exact names so the e2e
    harness can classify the page from its text."""
    accessible = widget.get_accessible()
    if accessible is not None:
        accessible.set_name(name)
    return widget


class RegionState:
    """The installed system's language, keyboard layout and time zone, as
    the three region pages pick them. "" means keep the image's own value
    (core.region_fields writes no key for it). The window owns one, and the
    identity page reads it; bare test doubles get an unshared one."""
    def __init__(self, locale="", keyboard_layout="", timezone="",
                 autologin=False, location_services=None):
        self.locale = locale
        self.keyboard_layout = keyboard_layout
        self.timezone = timezone
        self.autologin = autologin
        # None until the person touches the location switch: ConfigureTarget
        # only hears about location services when they changed it.
        self.location_services = location_services


class SearchListPage(Page):
    """A page that picks one value from a searchable list (language,
    keyboard, time zone). The SearchEntry filters the ListBox rows; one
    click selects. Blocking is false: a failed live apply shows a note,
    and the pick still reaches the target."""
    search_placeholder = ""
    a11y_page_name = ""
    a11y_search_name = ""

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, self.a11y_page_name)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(self.search_placeholder)
        a11y_name(self.search, self.a11y_search_name)
        self.search.connect("search-changed", self._on_search)
        self.pack_start(self.search, False, False, 0)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.set_filter_func(self._filter)
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.add(self.listbox)
        self.pack_start(scroll, True, True, 0)
        self.rows = {}
        # The list opens with the choice that applies when nobody picks one:
        # the session's value, or a row that says the image keeps its own.
        current = self.current()
        values = list(self.values())
        if current not in values:
            self._add_row("", _("Keep the image's setting"))
        for value in values:
            self._add_row(value, self.label_for(value))
        self.listbox.connect("row-selected", self._on_selected)
        self.note = _warn_row("")
        self.note.set_no_show_all(True)
        self.pack_start(self.note, False, False, 0)
        self.live_problem = problem_label()
        self.pack_start(self.live_problem, False, False, 0)
        self.check = live_check(self._on_checked)
        self.listbox.select_row(self.rows[current if current in self.rows else ""])

    def _add_row(self, value, text):
        row = Gtk.ListBoxRow()
        row.value = value
        row.haystack = f"{value} {text}".casefold()
        row.add(Gtk.Label(label=text, xalign=0, margin=6))
        self.listbox.add(row)
        self.rows[value] = row

    def on_enter(self):
        """Bring the selected row into view, when the list has its size."""
        GLib.idle_add(self._show_selected)

    def _show_selected(self):
        row = self.listbox.get_selected_row()
        adjustment = self.listbox.get_adjustment()
        if row is not None and adjustment is not None and row.get_mapped():
            area = row.get_allocation()
            if area.height > 1:
                adjustment.clamp_page(area.y, area.y + area.height)
        return False

    def label_for(self, value):
        """The text of a row; the value itself goes to the recipe."""
        return value

    def values(self):
        return []

    def current(self):
        return ""

    def pick(self, value):
        pass

    def keep(self):
        """Nothing picked: the image keeps its own value."""

    def fragment(self):
        return {}

    def _filter(self, row):
        needle = self.search.get_text().strip().casefold()
        return needle in getattr(row, "haystack", "")

    def _on_search(self, _entry):
        self.listbox.invalidate_filter()

    def _on_selected(self, _box, row):
        if row is not None and not row.value:
            self.keep()
        elif row is not None:
            self.pick(row.value)
        if row is not None:
            self.check.submit(self.fragment())
            self.win.refresh_nav()

    def _note(self, text):
        self.note.get_children()[1].set_text(text)
        self.note.set_visible(bool(text))

    def selected(self):
        row = self.listbox.get_selected_row()
        return getattr(row, "value", "") if row is not None else ""

    def _on_checked(self, problems, error):
        show_problem(self.live_problem, (problems or [None])[0])
        refresh = getattr(self.win, "refresh_nav", None)
        if refresh is not None:
            refresh()


class LanguagePage(SearchListPage):
    title = _("Language")
    a11y_page_name = _("Language")
    a11y_search_name = _("Search languages")
    search_placeholder = _("Search languages")

    def values(self):
        # A session in the C locale has no language to preselect: the page
        # opens on "Keep the image's setting".
        return [name for name in locale_checks.available_languages()
                if locale_checks.is_language(name)]

    def current(self):
        return locale_checks.current_language()

    def label_for(self, value):
        return locale_checks.language_label(value)

    def keep(self):
        self.win.region.locale = ""
        self._note("")

    def pick(self, value):
        self.win.region.locale = value
        if not locale_checks.apply_language(value):
            self._note(_("The live session could not switch to {value}; "
                         "the installed system still uses it.").format(value=value))
        else:
            self._note("")

    def fragment(self):
        return {"locale": self.win.region.locale}


class KeyboardPage(SearchListPage):
    title = _("Keyboard layout")
    a11y_page_name = _("Keyboard layout")
    a11y_search_name = _("Search keyboards")
    search_placeholder = _("Search keyboards")

    def __init__(self, win):
        super().__init__(win)
        self.test_entry = Gtk.Entry()
        self.test_entry.set_placeholder_text(_("Type here to test the layout"))
        self.pack_start(self.test_entry, False, False, 0)
        self.test_entry.show()

    def values(self):
        return locale_checks.available_keyboard_layouts()

    def current(self):
        return locale_checks.current_keyboard_layout()

    def label_for(self, value):
        return locale_checks.keyboard_label(value)

    def keep(self):
        self.win.region.keyboard_layout = ""

    def pick(self, value):
        self.win.region.keyboard_layout = value
        locale_checks.apply_keyboard_layout(value)

    def fragment(self):
        layout = self.win.region.keyboard_layout
        return {"keyboard": {"layout": layout}} if layout else {}


class TimezonePage(SearchListPage):
    title = _("Time zone")
    a11y_page_name = _("Time zone")
    a11y_search_name = _("Search time zones")
    search_placeholder = _("Search time zones")

    def __init__(self, win):
        super().__init__(win)
        hint = Gtk.Label(xalign=0)
        hint.set_line_wrap(True)
        hint.set_text(_("Pick the closest city. The installer never detects "
                        "the location; the choice stays on this computer."))
        hint.get_style_context().add_class("dim-label")
        self.pack_start(hint, False, False, 0)
        hint.show()
        # Location services for the installed system (ConfigureTarget
        # privacy.locationServices, default false). Off until the person
        # touches it: the daemon only hears about a changed choice.
        self.location_check = Gtk.CheckButton(
            label=_("Allow apps to determine the location"))
        self.location_check.connect("toggled", self._on_location_toggled)
        self.pack_start(self.location_check, False, False, 0)
        self.location_check.show()

    def values(self):
        return sorted(locale_checks.available_timezones(),
                      key=lambda zone: locale_checks.timezone_label(zone).casefold())

    def label_for(self, value):
        return locale_checks.timezone_label(value)

    def keep(self):
        self.win.region.timezone = ""
        self._note("")

    def current(self):
        return locale_checks.current_timezone()

    def pick(self, value):
        self.win.region.timezone = value
        if not locale_checks.apply_timezone(value):
            self._note(_("The live session clock could not change; "
                         "the installed system still uses {value}.").format(value=value))
        else:
            self._note("")

    def _on_location_toggled(self, _button):
        self.win.region.location_services = self.location_check.get_active()
        self.check.submit(self.fragment())

    def fragment(self):
        picked = {"timezone": self.win.region.timezone}
        changed = self.win.region.location_services
        if changed is not None:
            picked["privacy"] = {"locationServices": bool(changed)}
        return picked


class NetworkPage(Page):
    title = _("Network")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Network"))
        self.status = _warn_row("")
        self.pack_start(self.status, False, False, 0)
        bar = Gtk.Box(spacing=8)
        bar.set_halign(Gtk.Align.END)
        self.settings_btn = a11y_name(
            Gtk.Button(label=_("Network settings")), _("Network settings"))
        self.settings_btn.connect("clicked", self._on_settings)
        bar.pack_start(self.settings_btn, False, False, 0)
        self.recheck_btn = a11y_name(
            Gtk.Button(label=_("Recheck")), _("Recheck"))
        self.recheck_btn.connect("clicked", lambda *_a: self.on_enter())
        bar.pack_start(self.recheck_btn, False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.online = True

    def should_show(self):
        describe = getattr(self.win, "describe_connectivity", None)
        if describe is None:
            return True
        try:
            needs, _offline = describe()
        except Exception:  # noqa: BLE001 - never trap the wizard on a check
            return True
        return bool(needs)

    def on_enter(self):
        self._set(True, _("Checking network connection…"))
        image = ""
        source = getattr(self.win, "source_and_target", None)
        if callable(source):
            try:
                image = (source()[0] or "")
            except Exception:  # noqa: BLE001 - the check answers, not raises
                image = ""
        if core.dry_run():
            self._set(True, "")
            return

        def probe():
            ok = locale_checks.has_connectivity(imgref=image)
            GLib.idle_add(self._done, ok)

        threading.Thread(target=probe, daemon=True).start()

    def _done(self, ok):
        self._set(ok, "" if ok else _(
            "No network connection. Connect, then press Recheck."))
        refresh = getattr(self.win, "refresh_nav", None)
        if refresh is not None:
            refresh()
        return False

    def _on_settings(self, *_args):
        if not core.open_network_settings():
            self._set(False, _(
                "No network settings tool was found. Connect with the "
                "panel's network icon, then press Recheck."))

    def _set(self, ok, message):
        self.online = ok
        if message:
            self.status.get_children()[1].set_text(message)
        self.status.set_visible(bool(message))

    def can_continue(self):
        return self.online


class PrereleasePage(Page):
    title = _("Disclaimer")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Disclaimer"))
        _release, experiment = core.release_info()
        body = Gtk.Label(xalign=0)
        body.set_line_wrap(True)
        if experiment:
            body.set_text(experiment)
        else:
            body.set_text(_(
                "This is pre-release software. It may break, and it may "
                "lose data. Do not install it on a computer that matters."))
        self.pack_start(body, False, False, 0)

    def should_show(self):
        return core.show_prerelease()


class EulaPage(Page):
    title = _("Terms of use")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Terms of use"))
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.text = Gtk.TextView(editable=False, cursor_visible=False,
                                 wrap_mode=Gtk.WrapMode.WORD,
                                 left_margin=6, right_margin=6)
        self.loaded, blocks = self._load()
        self._render(blocks)
        scroll.add(self.text)
        self.pack_start(scroll, True, True, 0)
        self.accept = Gtk.CheckButton(
            label=_("I have read and accept the Terms of Use"))
        self.accept.connect("toggled", lambda *_a: self.win.refresh_nav())
        # eula-unreadable (spec): nothing to accept, so the only way out
        # is Power off.
        # no_show_all: the window's show_all() would show both.
        self.accept.set_no_show_all(True)
        self.accept.set_visible(self.loaded)
        self.pack_start(self.accept, False, False, 0)
        self.off_btn = Gtk.Button(label=_("Power off"))
        self.off_btn.connect(
            "clicked", lambda *_a: core.host_run(["systemctl", "poweroff"]))
        self.off_btn.set_no_show_all(True)
        self.off_btn.set_visible(not self.loaded)
        self.pack_start(self.off_btn, False, False, 0)

    def should_show(self):
        return bool(core.find_eula())

    def _load(self):
        """(loaded, blocks): the agreement as core.eula_blocks() reads it.
        A file that is gone, unreadable or no AppStream agreement is not
        loaded: the page then offers Power off, and never shows raw XML."""
        path = core.find_eula()
        try:
            with open(path, encoding="utf-8") as handle:
                blocks = core.eula_blocks(handle.read())
        except (OSError, UnicodeDecodeError):
            blocks = None
        if not blocks:
            return False, [("para", _("The terms could not be loaded."))]
        return True, blocks

    def _render(self, blocks):
        buf = self.text.get_buffer()
        buf.set_text("")
        heading = buf.create_tag("heading", weight=700, pixels_above_lines=8)
        item = buf.create_tag("item", left_margin=24)
        end = buf.get_end_iter
        for n, (kind, text) in enumerate(blocks):
            if n:
                buf.insert(end(), "\n")
            if kind == "heading":
                buf.insert_with_tags(end(), text, heading)
            elif kind == "item":
                buf.insert_with_tags(end(), "\u2022 " + text, item)
            elif kind == "number":
                buf.insert_with_tags(end(), text, item)
            else:
                buf.insert(end(), text)

    def plain_text(self):
        buf = self.text.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def can_continue(self):
        return self.accept.get_active()


class RstPage(Page):
    title = _("Intel RST")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Intel RST"))
        alert = _warn_row(_(
            "This computer uses Intel RST (RAID mode), which can hide disks. "
            "If the disk that you want is not in the list of the next step, "
            "switch the storage to AHCI in the firmware settings."))
        if Atspi is not None:
            alert.get_accessible().set_role(Atspi.Role.ALERT)
        self.pack_start(alert, False, False, 0)
        bar = Gtk.Box(spacing=8)
        bar.set_halign(Gtk.Align.END)
        self.off_btn = Gtk.Button(label=_("Power off"))
        self.off_btn.connect(
            "clicked", lambda *_a: core.host_run(["systemctl", "poweroff"]))
        bar.pack_start(self.off_btn, False, False, 0)
        self.pack_start(bar, False, False, 0)

    def should_show(self):
        try:
            return bool(core.rst_detected())
        except Exception:  # noqa: BLE001 - a gate must never trap the wizard
            return False


class WelcomePage(Page):
    # Flavour text is branding copy (shared/branding): the product's own
    # welcome line first, then what this assistant does.
    title = core.BRANDING.text("welcome_title")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Welcome"))
        self.logo = product_logo(core.BRANDING.logo, core.IN_FLATPAK)
        self.pack_start(self.logo, False, False, 0)
        self.reorder_child(self.logo, 0)
        subtitle = core.BRANDING.text("welcome_subtitle")
        if subtitle:
            sub = Gtk.Label(label=subtitle, xalign=0)
            sub.set_line_wrap(True)
            self.pack_start(sub, False, False, 0)
        body = Gtk.Label(xalign=0)
        body.set_line_wrap(True)
        body.set_text(_(
            "This assistant installs {product} on this computer.\n\n"
            "You'll choose what to install and where; nothing is written to "
            "any disk until you confirm on the final step.").format(
                product=core.PRODUCT_NAME))
        self.pack_start(body, False, False, 0)
        # A screen reader as early as the first page (standard A6): XFCE
        # has no shortcut for it. Mnemonic Alt+R. The choice goes to the
        # installed system in ConfigureTarget when it is on, or was
        # turned off here (accessibility_choice).
        self.reader_initial = core.screen_reader_enabled()
        self.reader = Gtk.CheckButton.new_with_mnemonic(_("Screen _reader"))
        a11y_name(self.reader, _("Screen reader"))
        self.reader.set_active(self.reader_initial)
        self.reader.set_tooltip_text(_(
            "Reads the screen aloud. The installed system keeps this setting."))
        self.reader_problem = problem_label()
        self.reader.connect("toggled", self._on_reader)
        self.pack_start(self.reader, False, False, 0)
        self.pack_start(self.reader_problem, False, False, 0)
        # Try or install (spec `try-or-install`): trying quits the wizard
        # and leaves the live session running; installing walks on.
        self.try_btn = a11y_name(Gtk.Button(
            label=_("Try {product}").format(product=core.PRODUCT_NAME)),
            _("Try {product}").format(product=core.PRODUCT_NAME))
        self.try_btn.connect("clicked", self._on_try)
        self.pack_start(self.try_btn, False, False, 0)
        # A first-run tour of the catalog's image families (tour.py), shown
        # where a newcomer actually waits. Below-minimum machines never
        # reach this page: the app shows a blocking RAM/CPU/UEFI gate
        # instead (gates.py), so there is no warn-inline here anymore.
        # GNOME blocks the same way; warn-and-continue was this
        # frontend's alone.
        self.tour = tour.TourCarousel()
        self.pack_start(self.tour, False, False, 0)
        self.tour.set_slides(tour.slides_from_catalog(core.load_catalog().roots))

    def _on_reader(self, check):
        on = check.get_active()
        if core.set_screen_reader(on):
            show_problem(self.reader_problem, None)
        else:
            show_problem(self.reader_problem, {"code": "", "message": _(
                "The screen reader setting could not be changed.")})

    def accessibility_choice(self):
        """ConfigureTarget `accessibility`: on whenever the box is ticked
        (the session may have had it on before the installer started),
        off only when the person turned it off here; None leaves the
        installed system's default."""
        on = self.reader.get_active()
        if on or self.reader_initial:
            return {"screenReader": on}
        return None

    def _on_try(self, *_args):
        """End the wizard; the live session keeps running."""
        application = self.get_toplevel().get_application()
        if application is not None:
            application.quit()


class SourcePage(Page):
    title = _("What do you want to install?")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Image"))
        # Live media and the offline images are fisherman's facts (probe's
        # `live` and `offline`), read on the host.
        self.live = core.is_live()
        self.live_image = core.live_image()
        self.offline_refs = core.offline_images()
        self.catalog = core.load_catalog()
        self.leaves = list(self.catalog.leaves)

        self.radios = []
        # The group's unseen member: active when no row is. A radio group
        # always has one active button, and the contract is that nothing is
        # selected until the branding or the catalog names a default (#289).
        self._none = Gtk.RadioButton()
        self._rows = []

        def add_radio(label_text, sub, payload, offline):
            radio = Gtk.RadioButton.new_with_label_from_widget(self._none, label_text)
            radio.payload = payload
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.pack_start(radio, False, False, 0)
            subline = Gtk.Label(xalign=0)
            tagged = (sub + "   " + _("[available offline]")).strip() if offline else sub
            subline.set_markup(
                f"<small><tt>{GLib.markup_escape_text(tagged)}</tt></small>")
            subline.set_margin_start(26)
            box.pack_start(subline, False, False, 0)
            self.listbox.pack_start(box, False, False, 4)
            self.radios.append(radio)
            self._rows.append((box, f"{label_text} {sub}".casefold()))
            return radio

        # The list is flat and the bundled catalog has 177 leaves: a filter
        # on the row label and the image reference.
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(_("Search images"))
        self.search.connect("search-changed", self._on_search)
        self.pack_start(self.search, False, False, 0)

        self.listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.add(self.listbox)
        self.pack_start(scroll, True, True, 0)

        selected = None
        if self.live:
            # The same row GNOME shows: welcome_install and its subtitle. The
            # "[available offline]" tag already says no download is needed.
            # On live media this row is the selection at the start.
            selected = add_radio(
                core.BRANDING.text("welcome_install") + " " + _("(this system)"),
                core.BRANDING.text("welcome_install_subtitle"), {"live": True}, True)

        def sort_key(leaf):
            return (leaf.imgref not in self.offline_refs, leaf.breadcrumb.casefold())

        # Off live media: the branding's default_image, then the catalog's,
        # else nothing. Never the first row.
        default = None if self.live else self.catalog.default_leaf(
            core.BRANDING.default_image)
        for leaf in sorted(self.leaves, key=sort_key):
            # The breadcrumb, not the leaf's name: fifteen leaves of the
            # bundled catalog are called "Stable".
            radio = add_radio(leaf.breadcrumb, leaf.imgref, {"leaf": leaf},
                              leaf.imgref in self.offline_refs)
            if leaf is default:
                selected = radio
        (selected or self._none).set_active(True)
        for radio in self.radios:
            radio.connect("toggled", self._on_toggled)

        self.choose = Gtk.Label(label=_("Choose an image to continue."), xalign=0)
        self.choose.get_style_context().add_class("dim-label")
        self.choose.set_no_show_all(True)
        self.pack_start(self.choose, False, False, 0)
        if not self.radios:
            self.search.set_no_show_all(True)
            self.pack_start(_warn_row(_(
                "No image catalog found and this is not a live system. "
                "Check that images.json is installed.")), False, False, 0)
        self.listbox.show_all()
        self._sync_hint()

    def should_show(self):
        # The daemon installs the medium's own image and takes no other, so
        # there is nothing to choose (as in KDE and COSMIC).
        return not (core.backend() == "daemon" and self.live)

    def _on_search(self, entry):
        needle = entry.get_text().strip().casefold()
        for box, haystack in self._rows:
            box.set_visible(needle in haystack)

    def _on_toggled(self, *_args):
        self._sync_hint()
        refresh = getattr(self.win, "refresh_nav", None)
        if refresh is not None:
            refresh()

    def _sync_hint(self):
        self.choose.set_visible(bool(self.radios) and self.selection() is None)

    def can_continue(self):
        # Held until a row is selected: there is no silent first choice.
        return self.selection() is not None

    def selection(self):
        for r in self.radios:
            if r.get_active():
                return r.payload
        return None


def disk_label(disk):
    """One destination row: the title (model, else path), then the path,
    fisherman's size label and the bus, in the order every frontend uses."""
    bits = [disk["title"], disk["path"], disk["size_label"], disk["transport_label"]]
    return "    ".join(b for b in bits if b)


class DestinationPage(Page):
    title = _("Where should {product} be installed?").format(product=core.PRODUCT_NAME)

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Disk selection"))
        self.radios = []
        self.listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.pack_start(self.listbox, False, False, 0)
        self.warn = _warn_row("")
        self.warn_label = self.warn.get_children()[1]
        # Shown by _update_warning only, with a disk picked: the window's
        # show_all() left a bare warning icon on a page with no disk.
        self.warn.set_no_show_all(True)
        self.warn.get_children()[0].show()
        self.warn_label.show()
        self.pack_end(self.warn, False, False, 0)

    def on_enter(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        self.radios = []
        try:
            if core.backend() == "daemon":
                self._enter_daemon()
            else:
                self._enter_recipe()
        except Exception as exc:  # noqa: BLE001 - never a half-built page
            for child in self.listbox.get_children():
                self.listbox.remove(child)
            self.radios = []
            self._empty_state(str(exc) or type(exc).__name__)
        self.listbox.show_all()
        self._update_warning()

    def _enter_recipe(self):
        group = None
        disks, error = core.candidate_disks()
        for disk in disks:
            radio = Gtk.RadioButton.new_with_label_from_widget(group, disk_label(disk))
            group = group or radio
            radio.disk = disk
            radio.connect("toggled", self._update_warning)
            self.listbox.pack_start(radio, False, False, 4)
            self.radios.append(radio)
        if not disks:
            self._empty_state(error)

    def _enter_daemon(self):
        from bootc_shared import probe as fisherman_probe

        group = None
        rows, error = core.daemon_disk_view()
        if sum(1 for row in rows if row["eligible"]) > 1:
            # Two disks or more: the person names the one to erase. A radio
            # group always has an active button, so an unseen one starts it.
            group = self._none = Gtk.RadioButton()
        for row in rows:
            if row["eligible"]:
                radio = Gtk.RadioButton.new_with_label_from_widget(
                    group, disk_label(row))
                group = group or radio
                radio.disk = row
                radio.connect("toggled", self._update_warning)
                self.listbox.pack_start(radio, False, False, 4)
                self.radios.append(radio)
            else:
                # Unusable disks sit in the list with the minimum size
                # (spec disk rows): visible, never selectable.
                if row["excluded_reason"] not in ("", "too_small"):
                    # The medium itself, a loop device, a DVD drive: not a
                    # disk that a person could make fit.
                    continue
                minimum = fisherman_probe.format_size(
                    row["minimal_size_bytes"] or 0)
                dim = Gtk.Label(xalign=0)
                dim.set_markup(GLib.markup_escape_text(
                    _("{title} ({path}) — needs at least {minimum}").format(
                        title=row["title"], path=row["path"],
                        minimum=minimum)))
                dim.set_sensitive(False)
                self.listbox.pack_start(dim, False, False, 4)
        if not self.radios:
            self._empty_state(error)

    def _empty_state(self, error):
        if error:
            self.listbox.pack_start(_warn_row(
                _("Could not detect disks: {error}").format(error=error)),
                False, False, 4)
        else:
            self.listbox.pack_start(_warn_row(
                _("No disk of at least 50 GiB was found. Connect one to install to.")),
                False, False, 4)
        bar = Gtk.Box(spacing=8)
        bar.set_halign(Gtk.Align.END)
        rescan = Gtk.Button(label=_("Rescan"))
        rescan.connect("clicked", lambda *_a: self.on_enter())
        bar.pack_start(rescan, False, False, 0)
        power = Gtk.Button(label=_("Power off"))
        power.connect("clicked", self._on_power_off)
        bar.pack_start(power, False, False, 0)
        self.listbox.pack_start(bar, False, False, 4)

    def _on_power_off(self, *_args):
        if core.backend() == "daemon":
            try:
                core.get_daemon().shutdown("poweroff")
                return
            except Exception:  # noqa: BLE001 - fall back to the host command
                pass
        core.host_run(["systemctl", "poweroff"])

    def _update_warning(self, *_args):
        d = self.selected_disk()
        if d:
            self.warn_label.set_text(
                _("Everything on {title} ({path}) will be erased.").format(
                    title=d["title"], path=d["path"]))
        self.warn.set_visible(d is not None)
        # With no disk picked at the start, the pick is what allows Next.
        refresh = getattr(self.win, "refresh_nav", None)
        if refresh is not None:
            refresh()

    def can_continue(self):
        return self.selected_disk() is not None

    def selected_disk(self):
        for r in self.radios:
            if r.get_active():
                return r.disk
        return None


class WipePage(Page):
    title = _("Existing data found")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Existing data found"))
        self.detail = Gtk.Label(xalign=0)
        self.detail.set_line_wrap(True)
        self.pack_start(self.detail, False, False, 0)
        self.free_radio = Gtk.RadioButton(label=_("Install to Free Space"))
        self.free_radio.connect("toggled", self._on_choice)
        self.pack_start(self.free_radio, False, False, 0)
        self.wipe_radio = Gtk.RadioButton.new_with_label_from_widget(
            self.free_radio, _("Use Entire Disk"))
        self.wipe_radio.connect("toggled", self._on_choice)
        self.pack_start(self.wipe_radio, False, False, 0)

    def disk(self):
        select = getattr(self.win.pages.get("destination"), "selected_disk",
                         None)
        return select() if callable(select) else None

    def should_show(self):
        # Daemon-only: the recipe probe has no existing-data facts, so the
        # legacy path keeps its erase warning on the disk page instead.
        if core.backend() != "daemon":
            return False
        disk = self.disk()
        if not disk:
            return False
        existing = disk.get("existing_data") or {}
        has_data = bool(existing.get("operatingSystems")
                        or existing.get("partitions")
                        or existing.get("hasLuks")
                        or existing.get("hasPartitionTable"))
        if not has_data:
            return False
        minimal = disk.get("minimal_size_bytes") or 0
        return (disk.get("free_bytes") or 0) >= minimal > 0

    def on_enter(self):
        disk = self.disk() or {}
        systems = ", ".join(
            (disk.get("existing_data") or {}).get("operatingSystems") or [])
        found = systems or _("a partitioned disk")
        self.detail.set_text(
            _("{title} holds {found}. Keep it and install into the free "
              "space, or erase the whole disk.").format(
                title=disk.get("title", ""), found=found))
        (self.wipe_radio if getattr(self.win, "install_mode", "erase") == "erase"
         else self.free_radio).set_active(True)
        self._on_choice()

    def _on_choice(self, *_args):
        mode = "erase" if self.wipe_radio.get_active() else "free_space"
        self.win.install_mode = mode


FILESYSTEMS = core.FILESYSTEMS


class SetupPage(Page):
    # "Disk encryption" is a keyword of the shared screen contract
    # (shared/walkthrough/parity_report.py). With the old title, "Filesystem
    # and encryption", this page matched nothing and the parity matrix showed
    # XFCE as the one frontend without an encryption screen it plainly has.
    title = _("Disk encryption")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Disk encryption"))
        self.has_tpm = core.has_tpm()

        self.enc_radios = []
        group = None
        for value in ENCRYPTION_TYPES:
            if core.needs_tpm2(value) and not self.has_tpm:
                continue
            # The daemon encrypts the root of each install and refuses `none`
            # (tuna-os/tunaOS run 45639909696): not offered there, as in KDE
            # and COSMIC.
            if value == "none" and core.backend() == "daemon":
                continue
            radio = Gtk.RadioButton.new_with_label_from_widget(
                group, encryption_text(value, "_label"))
            group = group or radio
            radio.value = value
            radio.connect("toggled", self._sync)
            self.pack_start(radio, False, False, 0)
            sub = Gtk.Label(xalign=0)
            sub.set_markup("<small>" + GLib.markup_escape_text(
                encryption_text(value, "_description")) + "</small>")
            sub.set_margin_start(26)
            self.pack_start(sub, False, False, 0)
            self.enc_radios.append(radio)

        grid = Gtk.Grid(column_spacing=12, row_spacing=6, margin_top=6)
        self.pass1 = password_entry()
        self.pass2 = password_entry()
        a11y_name(self.pass1, _("Passphrase"))
        a11y_name(self.pass2, _("Confirm passphrase"))
        for e in (self.pass1, self.pass2):
            e.connect("changed", self._sync)
        grid.attach(Gtk.Label(label=_("Passphrase"), xalign=0), 0, 0, 1, 1)
        grid.attach(self.pass1, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label=_("Confirm"), xalign=0), 0, 1, 1, 1)
        grid.attach(self.pass2, 1, 1, 1, 1)
        self.pass_grid = grid
        self.pack_start(grid, False, False, 0)
        # fisherman's answer for the encryption and filesystem choice: an
        # empty passphrase, or LUKS on ZFS (encryption.*, filesystem).
        self.problem = None
        self.problem_label = problem_label()
        self.pack_start(self.problem_label, False, False, 0)
        self.check = live_check(self._on_checked)
        # Checked from the first visit on: before it, the window has no
        # image selection to take the filesystem from.
        self._entered = False

        adv = Gtk.Expander(label=_("Advanced"))
        # The daemon takes no filesystem: the image decides it.
        adv.set_no_show_all(core.backend() == "daemon")
        advbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)
        self.fs_combo = Gtk.ComboBoxText()
        # Whether the person picked a filesystem. Until they do, the combo
        # follows the selected image's catalog default (on_enter), and that
        # default is what goes in the recipe. The choices are the image's
        # too (`filesystems`, else its one `filesystem`); this frontend's
        # own list is for an image that names neither.
        self._fs_chosen = False
        self._fs_syncing = False
        self._fs_leaf = None
        self._load_filesystems(None)
        self.fs_combo.connect("changed", self._on_fs_changed)
        fsrow = Gtk.Box(spacing=8)
        fsrow.pack_start(Gtk.Label(label=_("Filesystem"), xalign=0), False, False, 0)
        fsrow.pack_start(self.fs_combo, False, False, 0)
        advbox.pack_start(fsrow, False, False, 0)
        self.subvol_check = Gtk.CheckButton(
            label=_("Create btrfs subvolumes (@, @home, @snapshots)"))
        advbox.pack_start(self.subvol_check, False, False, 0)
        adv.add(advbox)
        self.pack_start(adv, False, False, 0)
        if core.backend() == "daemon" and self.has_tpm:
            # Sealed to the TPM, with nothing to type.
            for radio in self.enc_radios:
                if radio.value == "tpm2-luks":
                    radio.set_active(True)
        self._sync()

    def should_show(self):
        # screens.yaml `encryption.skip_when`: with a usable TPM 2.0 the
        # daemon seals the disk to it with nothing to type, and Confirm
        # says so. The page stays for no TPM (a passphrase) and for the
        # recipe path (its filesystem and encryption choices).
        return not (core.backend() == "daemon" and self.has_tpm)

    def _sync(self, *_args):
        self.pass_grid.set_sensitive(core.needs_passphrase(self.enc_type()))
        self.win.refresh_nav()
        if getattr(self, "check", None) is not None and self._entered:
            self.check.submit(self.partial_recipe())

    def partial_recipe(self):
        leaf = self.win.layout_source()
        enc = {"type": self.enc_type()}
        if core.needs_passphrase(enc["type"]):
            enc["passphrase"] = self.pass1.get_text()
        partial = {"filesystem": self.default_filesystem(leaf.filesystem if leaf else ""),
                   "encryption": enc}
        partial.update(core.experimental_for(partial["filesystem"]))
        if leaf is not None and getattr(leaf, "composefs", False):
            # fisherman's filesystem rule depends on it (composefs needs
            # fs-verity), so the page shows the problem before Install.
            partial["composeFsBackend"] = True
        return partial

    def _on_checked(self, problems, error):
        problems = problems or []
        self.problem = next((p for p in problems if p.get("field", "").startswith(
            ("encryption", "filesystem"))), None)
        show_problem(self.problem_label, self.problem)
        self.win.refresh_nav()

    def enc_type(self):
        for r in self.enc_radios:
            if r.get_active():
                return r.value
        return "none"

    def can_continue(self):
        # The passphrase rule (not empty) is fisherman's; that the two
        # entries match is this page's.
        if self.problem is not None:
            return False
        if core.needs_passphrase(self.enc_type()):
            p1, p2 = self.pass1.get_text(), self.pass2.get_text()
            return bool(p1) and p1 == p2
        return True

    def _load_filesystems(self, leaf):
        """Offer the image's filesystems and select its default, without
        counting that as the person's pick."""
        choices = list(getattr(leaf, "filesystems", None) or FILESYSTEMS)
        default = getattr(leaf, "filesystem", "") or core.DEFAULT_FILESYSTEM
        if default not in choices:
            # A leaf that lists choices without the frontend's default, and
            # names no default of its own: its first choice.
            default = choices[0]
        self._fs_syncing = True
        try:
            self.fs_combo.remove_all()
            for fs in choices:
                self.fs_combo.append(fs, filesystem_label(fs))
            self.fs_combo.set_active_id(default)
        finally:
            self._fs_syncing = False

    def _on_fs_changed(self, *_args):
        if not self._fs_syncing:
            self._fs_chosen = True
            self._sync()

    def on_enter(self):
        leaf = self.win.layout_source()
        key = getattr(leaf, "imgref", "") if leaf is not None else ""
        if not self._entered or key != self._fs_leaf:
            # A different image: its filesystems and its default apply. The
            # choice made for the image before it does not carry over.
            self._fs_leaf = key
            self._fs_chosen = False
            self._load_filesystems(leaf)
        self._entered = True
        self.check.submit(self.partial_recipe())

    def default_filesystem(self, leaf_default):
        # Catalog default wins unless the user touched Advanced. This used to
        # be `get_active_id() or leaf_default`, but the combo always had
        # "xfs" active, so the catalog default could never apply.
        if self._fs_chosen:
            return self.fs_combo.get_active_id() or leaf_default or core.DEFAULT_FILESYSTEM
        return leaf_default or core.DEFAULT_FILESYSTEM


class IdentityPage(Page):
    title = _("Name this computer")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Account"))
        # The installed system's language, keyboard and time zone live on
        # the window (RegionState): the region pages own the controls, this
        # page only reads the picks for the recipe.
        self.region = getattr(win, "region", None) or RegionState()
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        # Seeded from the selected image's default_hostname, else the
        # branding's (on_enter), until the person types one.
        self._hostname_edited = False
        self._hostname_syncing = False
        self.hostname = Gtk.Entry(text=core.BRANDING.default_hostname, hexpand=True,
                                  width_chars=28, activates_default=True)
        a11y_name(self.hostname, _("Hostname"))
        self.hostname.connect("changed", self._on_hostname_changed)
        grid.attach(Gtk.Label(label=_("Hostname"), xalign=0), 0, 0, 1, 1)
        grid.attach(self.hostname, 1, 0, 1, 1)
        self.hostname_problem = problem_label()
        grid.attach(self.hostname_problem, 1, 1, 1, 1)
        self.pack_start(grid, False, False, 0)

        self.user_frame = Gtk.Frame(label=_("Your account"), margin_top=8)
        ug = Gtk.Grid(column_spacing=12, row_spacing=6, margin=10)
        self.username = Gtk.Entry(hexpand=True, width_chars=28, activates_default=True)
        self.fullname = Gtk.Entry(hexpand=True, width_chars=28, activates_default=True)
        # Asked twice, each with a reveal icon: one typo in a single hidden
        # entry made an account nobody could sign in to (#295).
        self.password = password_entry()
        self.password2 = password_entry()
        a11y_name(self.username, _("User name"))
        a11y_name(self.fullname, _("Full name"))
        a11y_name(self.password, _("Password"))
        a11y_name(self.password2, _("Confirm password"))
        for i, (lbl, entry) in enumerate(((_("Username"), self.username),
                                          (_("Full name"), self.fullname),
                                          (_("Password"), self.password),
                                          (_("Confirm password"), self.password2))):
            ug.attach(Gtk.Label(label=lbl, xalign=0), 0, i * 2, 1, 1)
            ug.attach(entry, 1, i * 2, 1, 1)
            entry.connect("changed", self._on_account_changed)
        self.username_problem = problem_label()
        ug.attach(self.username_problem, 1, 1, 1, 1)
        self.password_problem = problem_label()
        self.password_problem.set_text(_("The passwords do not match."))
        ug.attach(self.password_problem, 1, 7, 1, 1)
        self.user_frame.add(ug)
        self.pack_start(self.user_frame, False, False, 0)

        # Automatic sign-in (spec account inputs): the daemon stores it
        # over ConfigureTarget. The recipe schema has no such key, so the
        # box shows on the daemon backend only.
        self.autologin = Gtk.CheckButton(label=_("Sign in automatically"))
        self.autologin.set_no_show_all(True)
        self.autologin.connect(
            "toggled", self._on_autologin_toggled)
        self.pack_start(self.autologin, False, False, 0)

        # The hostname and username rules are fisherman's
        # (`fisherman validate --json --partial -`). The hostname used to be
        # a single-label pattern here with no length limit, and the username
        # was not checked at all, so "root" failed after the OS was on disk.
        self.problems = {}
        self.check = live_check(self._on_checked)
        for entry in (self.hostname, self.username):
            entry.connect("changed", lambda *_args: self.check.submit(self.partial_recipe()))

    def partial_recipe(self):
        partial = {"hostname": self.hostname.get_text()}
        if self.win.needs_user_creation():
            partial["user"] = {"username": self.username.get_text()}
        if core.backend() == "daemon":
            partial["autologin"] = self.region.autologin
        return partial

    def region_choices(self):
        """The picks as build_recipe() takes them: "" for "keep"."""
        return {"locale": self.region.locale,
                "keyboard_layout": self.region.keyboard_layout,
                "timezone": self.region.timezone}

    def region_fields(self):
        """The recipe's `locale`, `keyboard` and `timezone`: only the ones
        the person picked."""
        return core.region_fields(**self.region_choices())

    def _on_checked(self, problems, error):
        problems = problems or []
        self.problems = {f: next((p for p in problems if p.get("field") == f), None)
                         for f in ("hostname", "user.username")}
        show_problem(self.hostname_problem, self.problems["hostname"])
        show_problem(self.username_problem, self.problems["user.username"])
        self.win.refresh_nav()

    def _on_autologin_toggled(self, _button):
        self.region.autologin = self.autologin.get_active()
        self.check.submit(self.partial_recipe())

    def passwords_match(self):
        return self.password.get_text() == self.password2.get_text()

    def _on_account_changed(self, *_args):
        # The mismatch line shows once the confirmation has something in it.
        self.password_problem.set_visible(
            bool(self.password2.get_text()) and not self.passwords_match())
        self.win.refresh_nav()

    def _on_hostname_changed(self, *_args):
        if not self._hostname_syncing:
            self._hostname_edited = True

    def seed_hostname(self):
        """Show the selected image's default hostname until the person has
        typed one (shared/catalog/README.md, "Hostname")."""
        if self._hostname_edited:
            return
        leaf = self.win.selected_leaf()
        seed = getattr(leaf, "default_hostname", "") or core.BRANDING.default_hostname
        if self.hostname.get_text() != seed:
            self._hostname_syncing = True
            try:
                self.hostname.set_text(seed)
            finally:
                self._hostname_syncing = False

    def on_enter(self):
        self.seed_hostname()
        self.user_frame.set_visible(self.win.needs_user_creation())
        show = core.backend() == "daemon"
        self.autologin.set_visible(show)
        self.check.submit(self.partial_recipe())

    def can_continue(self):
        if self.problems.get("hostname") is not None:
            return False
        if self.win.needs_user_creation():
            # A user is required for this image (needs_user_creation), and
            # the password rules are this page's (not empty, typed the same
            # twice); fisherman accepts any.
            return (bool(self.username.get_text()) and bool(self.password.get_text())
                    and self.passwords_match()
                    and self.problems.get("user.username") is None)
        return True


class ConfirmPage(Page):
    title = core.BRANDING.text("confirm_title")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Confirm"))
        # confirm_subtitle and confirm_body are the product's own lines
        # (a quote, a tagline); empty in the neutral defaults, so hidden.
        self.subtitle = Gtk.Label(xalign=0)
        self.subtitle.set_line_wrap(True)
        self.subtitle.set_no_show_all(True)
        self.pack_start(self.subtitle, False, False, 0)
        self.summary = Gtk.Grid(column_spacing=18, row_spacing=6)
        a11y_name(self.summary, _("Summary"))
        self.pack_start(self.summary, False, False, 0)
        # What fisherman would refuse: asked here, before the install starts.
        self.refused = []
        self.refused_generation = 0
        self.refused_label = problem_label()
        self.pack_start(self.refused_label, False, False, 0)
        # The install plan (tuna-os/fisherman#371): the disk that fisherman
        # will write to, what it reports about itself, and each device whose
        # data the install destroys, from `fisherman plan --json -`. Hidden
        # until fisherman answers with a valid plan.
        self.plan = None
        self.plan_generation = 0
        self.plan_label = Gtk.Label(xalign=0)
        self.plan_label.set_line_wrap(True)
        self.plan_label.set_selectable(True)
        self.plan_label.set_no_show_all(True)
        self.pack_start(self.plan_label, False, False, 0)
        # The install source (#267): download the image (the default), or
        # copy the system that this computer runs from its bootc storage.
        # Shown only when fisherman's probe has an item that qualifies;
        # never on live media.
        self.reuse_source = None
        self.reuse_selected = False
        self.reuse_problems = []
        self.reuse_check = None
        self.reuse_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.reuse_box.set_no_show_all(True)
        self.reuse_title = Gtk.Label(xalign=0)
        self.reuse_box.pack_start(self.reuse_title, False, False, 0)
        self.reuse_download = Gtk.RadioButton(label=core.BRANDING.text("source_reuse_download"))
        self.reuse_local = Gtk.RadioButton.new_with_label_from_widget(
            self.reuse_download, core.BRANDING.text("source_reuse_local"))
        self.reuse_detail = Gtk.Label(xalign=0)
        self.reuse_detail.set_line_wrap(True)
        for widget in (self.reuse_download, self.reuse_local, self.reuse_detail):
            self.reuse_box.pack_start(widget, False, False, 0)
        self.reuse_problem = problem_label()
        self.reuse_box.pack_start(self.reuse_problem, False, False, 0)
        self.reuse_local.connect("toggled", self._on_reuse_toggled)
        self.pack_start(self.reuse_box, False, False, 0)
        # The source check (#266) and this computer's bootc storage (#267):
        # what fisherman's probe says about the selected image. Only a
        # blocked source holds Install.
        self.source_label = Gtk.Label(xalign=0)
        self.source_label.set_line_wrap(True)
        self.source_label.set_selectable(True)
        # In a scrolled box of its own: this computer's bootc storage can
        # list several images, and the page must not push Back and Install
        # off a small screen.
        self.source_scroll = Gtk.ScrolledWindow()
        self.source_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.source_scroll.set_propagate_natural_height(True)
        self.source_scroll.set_max_content_height(160)
        self.source_scroll.add(self.source_label)
        self.source_scroll.set_no_show_all(True)
        self.pack_start(self.source_scroll, False, False, 0)
        self.source_generation = 0
        self.source_blocked = False
        self.body = Gtk.Label(xalign=0)
        self.body.set_line_wrap(True)
        self.body.set_no_show_all(True)
        self.pack_start(self.body, False, False, 0)
        # confirm_warning names the disk that is about to be erased; on_enter
        # fills in the selected one's path, as KDE, COSMIC and Niri do.
        self.warn_label = _warn_row(
            core.BRANDING.text("confirm_warning", disk=_("the selected disk")))
        self.warn_text = self.warn_label.get_children()[1]
        self.pack_start(self.warn_label, False, False, 0)
        # First, under the title: it must not be below the fold of a small
        # screen or of large text.
        self.reorder_child(self.warn_label, 1)
        # Connectivity gate (defaults/conn_check.py): an install that must
        # download its image cannot start offline. GNOME's conn_check page
        # auto-skips on offline installs and otherwise blocks with a
        # Recheck button; this row is that page, folded into confirm so
        # the wizard keeps its eight pages. net_ok starts True and only a
        # real window's async check can turn it False, so test stubs (no
        # check_connectivity) never gate.
        self.net_ok = True
        self.net_row = _warn_row(_("Checking network connection…"))
        self.net_row.set_no_show_all(True)
        self.pack_start(self.net_row, False, False, 0)
        netbar = Gtk.Box(spacing=8)
        netbar.set_halign(Gtk.Align.END)
        # Help to get online, not only a verdict (#301): the desktop's own
        # network tool, opened on the host.
        self.net_settings = Gtk.Button(label=_("Network settings"))
        self.net_settings.connect("clicked", self._on_network_settings)
        self.net_settings.set_no_show_all(True)
        netbar.pack_start(self.net_settings, False, False, 0)
        self.net_recheck = Gtk.Button(label=_("Recheck"))
        self.net_recheck.connect("clicked", lambda *_args: self._check_network())
        self.net_recheck.set_no_show_all(True)
        netbar.pack_start(self.net_recheck, False, False, 0)
        self.net_bar = netbar
        self.pack_start(netbar, False, False, 0)
        for widget, key in ((self.subtitle, "confirm_subtitle"), (self.body, "confirm_body")):
            line = core.BRANDING.text(key)
            widget.set_text(line)
            widget.set_visible(bool(line))

    def on_enter(self):
        self._update_reuse(self.win.wizard_recipe() if hasattr(self.win, "wizard_recipe")
                           else self.win.build_recipe())
        self._fill()

    def _fill(self):
        r = self.win.build_recipe()
        disk = r.get("disk") or self.win.pages["destination"].selected_disk()["path"]
        if r.get("sourceReuse"):
            image = core.BRANDING.text("source_reuse_install_from").replace(
                "{value}", self.reuse_source["ref"])
        else:
            image = (r.get("image") or self.win.pages["source"].live_image
                     or _("this live system"))
        # The same rows, in the same order, as KDE's confirm step.
        daemon = core.backend() == "daemon"
        rows = [
            (_("Target disk"), self._disk_text(disk) if daemon else disk)]
        if not daemon:
            # The daemon takes no filesystem: the image decides it.
            rows.append((_("Filesystem"), filesystem_label(r["filesystem"])))
        enc = r["encryption"]["type"] or "none"
        enc_text = encryption_text(enc, "_label")
        if daemon:
            # The encryption page is skipped with a TPM (screens.yaml), so
            # Confirm is where a person reads how the disk unlocks.
            enc_text = ": ".join(t for t in (
                enc_text, encryption_text(enc, "_description")) if t)
        rows += [
            (_("Encryption"), enc_text),
            (_("Hostname"), r["hostname"]),
        ]
        if daemon and getattr(self.win.pages.get("source"), "live", False):
            # The medium installs its own image: its product name, not a
            # registry reference.
            image = core.PRODUCT_NAME or image
        rows.append((_("Image"), image))
        if r.get("targetImgref") and r["targetImgref"] != r.get("image"):
            # The image that updates follow, when it is not the one installed.
            rows.append((_("Updates from"), r["targetImgref"]))
        if r.get("user", {}).get("username"):
            rows.append((_("User"), r["user"]["username"]))
        # What the installed system gets of the identity page's picks (#292).
        keep = _("The image's setting")
        rows += [
            (_("Language"), locale_checks.language_label(r["locale"])
             if r.get("locale") else keep),
            (_("Keyboard"), locale_checks.keyboard_label(r["keyboard"]["layout"])
             if r.get("keyboard") else keep),
            (_("Time zone"), locale_checks.timezone_label(r["timezone"])
             if r.get("timezone") else keep)]
        self._show_summary(rows)
        selected = self.win.pages["destination"].selected_disk()
        warn_key = (
            "confirm_warning_removable"
            if selected and selected.get("removable")
            else "confirm_warning"
        )
        self.warn_text.set_text(core.BRANDING.text(warn_key, disk=disk))
        self._start_plan(r)
        self._check_source(r)
        self._check_network()
        self._check_refused(r)

    def _disk_text(self, path):
        select = getattr(self.win.pages["destination"], "selected_disk", None)
        row = select() if callable(select) else None
        if not row or row.get("path") != path or row.get("title") in ("", path, None):
            return path
        return f"{row['title']} ({', '.join(b for b in (path, row.get('size_label')) if b)})"

    def _show_summary(self, rows):
        for child in self.summary.get_children():
            self.summary.remove(child)
        for i, (name, value) in enumerate(rows):
            key = Gtk.Label(label=name + ":", xalign=0, yalign=0)
            key.get_style_context().add_class("dim-label")
            text = Gtk.Label(label=value, xalign=0, hexpand=True, selectable=False)
            text.set_line_wrap(True)
            text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.summary.attach(key, 0, i, 1, 1)
            self.summary.attach(text, 1, i, 1, 1)
        self.summary.show_all()

    def summary_text(self):
        """The summary rows as text, one "name: value" a line."""
        cell = self.summary.get_child_at
        lines, i = [], 0
        while cell(0, i) is not None:
            lines.append(f"{cell(0, i).get_text()} {cell(1, i).get_text()}")
            i += 1
        return "\n".join(lines)

    # How the daemon is asked; tests replace both.
    refused_request = staticmethod(lambda recipe: core.recipe_problems(recipe))
    refused_start = staticmethod(lambda fn: threading.Thread(target=fn, daemon=True).start())

    def _check_refused(self, recipe):
        """Validate the whole recipe on the daemon before Install can be
        pressed. The daemon refused an unencrypted install only after the
        install had started (tuna-os/tunaOS run 45639909696)."""
        self.refused_generation += 1
        generation = self.refused_generation
        self._on_refused(generation, [])
        if core.backend() != "daemon" or core.dry_run():
            return
        request = self.refused_request

        def work():
            GLib.idle_add(self._on_refused, generation, request(recipe))

        self.refused_start(work)

    def _on_refused(self, generation, problems):
        if generation != self.refused_generation:
            return False
        self.refused = list(problems or [])
        self.refused_label.set_text("\n".join(self.refused))
        self.refused_label.set_visible(bool(self.refused))
        refresh = getattr(self.win, "refresh_nav", None)
        if refresh is not None:
            refresh()
        return False

    # How a plan is asked and where it runs; tests replace both.
    plan_request = staticmethod(lambda recipe: core.request_plan(recipe))
    plan_start = staticmethod(lambda fn: threading.Thread(target=fn, daemon=True).start())

    def _start_plan(self, recipe):
        """Ask `fisherman plan --json -` about the recipe that Next would
        install, off the UI thread, and forget the plan of an earlier
        visit. The recipe goes to fisherman on stdin; the worker drops it
        with its answer. A dry run (the capture) has no fisherman to ask."""
        self.plan_generation += 1
        self.plan = None
        self._show_plan([])
        if core.dry_run():
            return
        generation = self.plan_generation
        request = self.plan_request

        def work():
            answer = request(recipe)
            GLib.idle_add(self._on_plan, generation, answer)

        self.plan_start(work)

    def _on_plan(self, generation, answer):
        """Show a valid plan of this visit. No plan (an older fisherman, a
        timeout, an invalid recipe) leaves the page as it was: the field
        checks name a problem, and the install runs its own checks."""
        if generation != self.plan_generation:
            return False
        result, error = answer
        if error is not None or not result or not result.get("valid"):
            return False
        self.plan = result["plan"]
        self._show_plan(install_plan.rows(self.plan, core.BRANDING.text))
        return False

    def _show_plan(self, rows):
        lines = [title + ("\n    " + detail if detail else "") for title, detail in rows]
        if lines:
            lines.insert(0, core.BRANDING.text("confirm_plan_title"))
        self.plan_label.set_text("\n".join(lines))
        self.plan_label.set_visible(bool(lines))

    def bind_disk(self, recipe):
        """`recipe` bound to the disk that this page's plan showed: with
        `diskIdentity`, so that fisherman refuses the install if another
        device is now at that path (`disk_identity_mismatch`). `recipe`
        unchanged with no plan, a manual layout, a plan for another disk,
        or a disk that reports nothing to bind to."""
        if self.plan is None:
            return recipe
        return install_plan.bind(recipe, self.plan)

    def apply_source(self, recipe):
        """`recipe` with the install source that this page selected."""
        if not (self.reuse_selected and self.reuse_source):
            return recipe
        return source_check.apply_reuse(recipe, self.reuse_source)

    def _update_reuse(self, recipe):
        """Offer this computer's system as a second install source when the
        probe has an item that qualifies. The download stays selected until
        the user picks the item; a different item, or none, drops the
        choice."""
        update_ref = recipe.get("targetImgref") or recipe.get("image") or ""
        result, _error = core.probe()
        source = source_check.reuse_source(result, update_ref)
        if not source or (self.reuse_source or {}).get("digest") != source["digest"]:
            self.reuse_selected = False
            self.reuse_problems = []
        self.reuse_source = source
        rows = source_check.reuse_rows(source, update_ref, core.BRANDING.text)
        self.reuse_box.set_visible(bool(rows))
        if not rows:
            return
        self.reuse_title.set_text(core.BRANDING.text("source_reuse_title"))
        (_k1, download, download_detail), (_k2, local, local_detail) = rows
        self.reuse_download.set_label(download)
        self.reuse_local.set_label(local)
        self.reuse_detail.set_text(local_detail if self.reuse_selected else download_detail)
        if self.reuse_local.get_active() != self.reuse_selected:
            (self.reuse_local if self.reuse_selected else self.reuse_download).set_active(True)
        self.reuse_box.show_all()
        self._show_reuse_problems()
        if self.reuse_selected:
            self._check_reuse(recipe)

    def _on_reuse_toggled(self, button):
        if button.get_active() == self.reuse_selected or not self.reuse_source:
            return
        self.reuse_selected = button.get_active()
        self.reuse_problems = []
        self.on_enter()
        self.win.refresh_nav()

    def _check_reuse(self, recipe):
        """`fisherman validate --json --partial -` for the reuse fields;
        a problem shows in the words of `validate_<code>` and holds Next."""
        if self.reuse_check is None:
            self.reuse_check = live_check(self._on_reuse_checked)
        self.reuse_check.submit(source_check.reuse_fragment(
            source_check.apply_reuse(recipe, self.reuse_source)))

    def _on_reuse_checked(self, problems, error):
        if not self.reuse_selected:
            return
        self.reuse_problems = [] if error is not None else list(problems or [])
        self._show_reuse_problems()
        refresh = getattr(self.win, "refresh_nav", None)
        if refresh is not None:
            refresh()

    def _show_reuse_problems(self):
        lines = [fisherman_validate.render(p, core.BRANDING.text) for p in self.reuse_problems]
        self.reuse_problem.set_text("\n".join(lines))
        self.reuse_problem.set_visible(bool(lines))

    def _check_source(self, recipe):
        """Probe the selected source off the UI thread, and drop a reply
        for an older visit. The probe gets image references only."""
        self.source_generation += 1
        generation = self.source_generation
        self.source_blocked = False
        if core.backend() == "daemon":
            # The daemon installs the image of the medium: nothing to probe.
            self._show_source([])
            return
        req = source_check.recipe_request(recipe, core.is_live())
        args = source_check.probe_args(req)
        if not args:
            self._show_source([])
            return
        self._show_source(source_check.rows(None, None, core.BRANDING.text))
        if core.dry_run():
            # The capture reads BOOTC_INSTALLER_FAKE_PROBE; answer on this
            # thread so the screenshot shows the result, not "Checking".
            self._on_source(generation, req, core.probe_source(args))
            return

        def work():
            result = core.probe_source(args)
            GLib.idle_add(self._on_source, generation, req, result)

        threading.Thread(target=work, daemon=True).start()

    def _on_source(self, generation, req, result):
        if generation != self.source_generation:
            return False
        view = source_check.source_check(result, req)
        if view["state"] == "stale":
            return False
        self.source_blocked = source_check.blocks_install(view)
        self._show_source(source_check.rows(
            view, source_check.bootc_store(result), core.BRANDING.text,
            reuse=bool(self.reuse_selected and self.reuse_source)))
        refresh = getattr(self.win, "refresh_nav", None)
        if refresh is not None:
            refresh()
        return False

    def _show_source(self, rows):
        lines = [title + ("\n    " + subtitle if subtitle else "") for title, subtitle in rows]
        self.source_label.set_text("\n".join(lines))
        self.source_label.set_visible(bool(lines))
        self.source_scroll.set_visible(bool(lines))
        if lines:
            self.source_scroll.show_all()

    def _check_network(self):
        """Ask the window whether this install needs the network, and if so
        probe it off the UI thread (locale.has_connectivity). The window
        owns the answer because only it sees all pages: live media installs
        the running system, and an image already in the host's stores needs
        no download (offline_images). Test doubles have no
        check_connectivity and keep net_ok True."""
        check = getattr(self.win, "check_connectivity", None)
        if check is None:
            return
        if core.dry_run():
            # The screenshot harness drives on_enter with no route out;
            # probing would stall the capture and paint a "Checking…"
            # row into the committed screenshot.
            self._set_net(True, "")
            return
        needs, offline = self.win.describe_connectivity()
        if not needs:
            self._set_net(True, "")
            return
        self._set_net(True, _("Checking network connection…"))
        self.win.refresh_nav()
        # The registry of the image this install downloads is probed first.
        image = self.win.source_and_target()[0]

        def probe():
            ok = locale_checks.has_connectivity(imgref=image)
            GLib.idle_add(self._on_net_result, ok, offline)

        threading.Thread(target=probe, daemon=True).start()

    NO_NETWORK = _("No network connection. The selected image must be "
                   "downloaded. Open Network settings to connect, then press "
                   "Recheck; or go back and choose an image marked "
                   "[available offline].")
    NO_NETWORK_TOOL = _("No network settings tool was found on this system. "
                        "Connect with the network icon of the panel, then "
                        "press Recheck.")

    def _on_net_result(self, ok, offline):
        if ok:
            self._set_net(True, "")
        else:
            self._set_net(False, self.NO_NETWORK)
        self.win.refresh_nav()
        return False

    def _on_network_settings(self, *_args):
        if not core.open_network_settings():
            self._set_net(False, self.NO_NETWORK + "\n\n" + self.NO_NETWORK_TOOL)

    def _set_net(self, ok, message):
        self.net_ok = ok
        if message:
            self.net_row.get_children()[1].set_text(message)
        self.net_row.set_visible(bool(message))
        self.net_recheck.set_visible(not ok)
        self.net_settings.set_visible(not ok)

    def can_continue(self):
        return (self.net_ok and not self.source_blocked and not self.refused
                and not (self.reuse_selected and self.reuse_problems))

    def forced_erase(self):
        """Whether Next must pass the countdown dialog: a forced fit
        (insufficient free space, a foreign disk label) on the daemon
        backend. The recipe backend never knows the fit, so Next installs
        as before."""
        if core.backend() != "daemon":
            return False
        destination = (self.win.pages or {}).get("destination")
        select = getattr(destination, "selected_disk", None)
        selected = select() if callable(select) else None
        return (selected or {}).get("fit") in core.FORCED_FITS

    def confirm_advance(self):
        """Run the forced-erase countdown dialog; False stays on confirm."""
        if not self.forced_erase():
            return True
        destination = (self.win.pages or {}).get("destination")
        select = getattr(destination, "selected_disk", None)
        selected = select() if callable(select) else None
        dialog = gates.CountdownEraseDialog(
            self.get_toplevel(), (selected or {}).get("path", ""))
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK


def progress_parser_event(line):
    """Whether `line` is an event of fisherman's progress protocol."""
    try:
        event = json.loads(line)
    except ValueError:
        return False
    return isinstance(event, dict) and bool(event.get("type"))


def readable_log(text):
    """The install log for a person: each protocol line as its sentence."""
    lines = []
    for line in text.splitlines():
        shown = progress_parser.render_event(line)
        if shown is None and progress_parser_event(line):
            continue
        lines.append(line if shown is None else shown)
    return "\n".join(lines)


def failure_reason(error):
    """fisherman's message as a sentence, "" when it sent none."""
    message = ((error or {}).get("message") or "").strip()
    if not message:
        return ""
    message = message[0].upper() + message[1:]
    return message if message[-1] in ".!?…" else message + "."


class ProgressPage(Page):
    title = core.BRANDING.text("progress_title")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Installing"))
        self.steplabel = Gtk.Label(xalign=0)
        self.pack_start(self.steplabel, False, False, 0)
        self.bar = Gtk.ProgressBar(show_text=True)
        a11y_name(self.bar, _("Installation progress"))
        self.pack_start(self.bar, False, False, 0)
        # progress_note ("Do not power off the computer.") -- the one warning
        # that matters while the disk is being written. Empty hides it.
        self.note = Gtk.Label(label=core.BRANDING.text("progress_note"), xalign=0)
        self.note.get_style_context().add_class("dim-label")
        self.note.set_no_show_all(not self.note.get_text())
        self.pack_start(self.note, False, False, 0)
        # The copy of this computer's system before the first step (#267):
        # fisherman's source_reuse events. Hidden on every other install.
        self.reuselabel = Gtk.Label(xalign=0, selectable=True)
        self.reuselabel.set_line_wrap(True)
        self.reuselabel.get_style_context().add_class("dim-label")
        self.reuselabel.set_no_show_all(True)
        self.pack_start(self.reuselabel, False, False, 0)
        # Multi-line parser context (current step, weight, seen substeps).
        self._progress = progress_parser.new_progress_state()
        # The one step label that names the product ("Installing {product}…")
        # must say what this build installs, not a hardcoded distro. The
        # parser defaults to a neutral "the OS" until told otherwise.
        progress_parser.set_product_name(core.PRODUCT_NAME)
        progress_parser.set_install_label(core.BRANDING.text("progress_title"))
        # fisherman names each step with a stable step_id; its label is the
        # copy key "step_<id>". An id the copy does not know reads "" and
        # the parser falls back to the step name.
        progress_parser.set_step_label_resolver(
            lambda step_id: core.BRANDING.text("step_" + step_id))
        # Log visible by default — XFCE users want the output (DESIGN.md).
        self.logview = Gtk.TextView(editable=False, monospace=True)
        self.logview.modify_font(Pango.FontDescription("monospace 9"))
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.add(self.logview)
        self.pack_start(scroll, True, True, 0)
        # A visible way out (#299). The window's Back/Next bar is hidden
        # here, so this row takes its place. The button asks first
        # (gates.ConfirmCancelDialog, through the window).
        actions = Gtk.Box(spacing=8)
        actions.set_halign(Gtk.Align.END)
        self.cancel_btn = Gtk.Button(label=_("Cancel"))
        a11y_name(self.cancel_btn, _("Cancel"))
        self.cancel_btn.connect("clicked", self._on_cancel)
        actions.pack_start(self.cancel_btn, False, False, 0)
        self.pack_end(actions, False, False, 0)

    def on_enter(self):
        self.cancel_btn.set_sensitive(True)
        if not self.steplabel.get_text():
            # Until the first event: no empty page at 0 %.
            self.steplabel.set_text(_("Starting the installation…"))
        self.win.start_install(self)

    def _on_cancel(self, *_args):
        request = getattr(self.win, "request_cancel", None)
        if request is not None:
            request()

    def append_log(self, text):
        buf = self.logview.get_buffer()
        for line in text.splitlines():
            # fisherman's protocol is machine-readable; this pane is not. The
            # protocol line goes to the log FILE (app.py) — that is what gets
            # pasted into bug reports — but a human reads this one. Neither
            # shows the recovery key (#337): the key is for the done page,
            # which reads it from the event below.
            shown = progress_parser.render_event(line)
            if shown is None and progress_parser_event(line):
                # An event with nothing to read (a tick of the bar): the
                # person gets no JSON.
                continue
            if shown is None:
                shown = line
            shown = redact.redact_recovery_key(shown, self._progress.get("recovery_key", ""))
            buf.insert(buf.get_end_iter(), shown + "\n")
        mark = buf.create_mark(None, buf.get_end_iter(), False)
        self.logview.scroll_mark_onscreen(mark)
        # The bar is driven by fisherman's newline-delimited JSON progress
        # protocol (shared/progress/README.md), parsed by the shared parser.
        #
        # This used to be `re.search(r"\[(\d)/9\]", text)` against a
        # hardcoded nine-entry step table. fisherman has never written that
        # prefix — it emits JSON on stdout and nothing else — so the bar sat
        # at zero and the step label stayed empty for the whole of every real
        # install. The screenshot harness did not catch it because the dry-run
        # transcript in core.py was itself written in the "[n/9]" shape, so
        # the only thing the parser ever matched was the fixture written to
        # match the parser.
        #
        # The step COUNT was wrong too, independently: fisherman computes
        # total_steps (8, adjusted for manual layout, LUKS, TPM2 enrolment and
        # a separate /var disk — cmd/fisherman/main.go), so it is 9 only by
        # coincidence. The protocol carries cumulative_pct precisely so no
        # frontend has to model the pipeline; this reads it instead of
        # counting steps. Current fisherman goes further and sends the bar
        # itself as overall_pct, which the parser prefers; the cumulative_pct
        # derivation is the fallback for an older fisherman.
        for line in text.splitlines():
            update = progress_parser.apply_progress_event(line, self._progress)
            if update is None:
                continue
            if "source_reuse" in update:
                # The copy moves no bar: it holds until fisherman's first step.
                self.show_source_reuse()
                continue
            if update["label"] is not None:
                # The step label sits directly under the page title, and for
                # the install step the branding's "progress_title" and the
                # parser's "Installing {product}…" are the same sentence — so
                # the screen said it twice, for the 87% of the install that
                # step covers. Blank rather than stale: repeating the previous
                # step's name would be a lie about what is running.
                dup = update["label"].rstrip("…. ") == self.title.rstrip("…. ")
                self.steplabel.set_text("" if dup else update["label"])
            if update["fraction"] is not None:
                frac = update["fraction"]
                self.bar.set_fraction(frac)
                self.win.trawl.set_fill(frac)

    def show_source_reuse(self):
        lines = progress_parser.source_reuse_text(self._progress.get("source_reuse"),
                                                  core.BRANDING.text)
        self.reuselabel.set_text("\n".join(lines))
        self.reuselabel.set_visible(bool(lines))

    def progress_state(self):
        """The parser's state, for the cancel question (copy_cancel)."""
        return self._progress

    def recovery_key(self):
        """The key fisherman emitted, or "" for a non-TPM install.

        The parser has tracked this all along (shared/progress/README.md);
        nothing read it, which is how it stayed a log line only.
        """
        return self._progress.get("recovery_key", "")

    def receipt(self):
        """What the install did with the installation receipt: the parser's
        view of fisherman's `receipt` event, or None when none came (#269)."""
        return self._progress.get("receipt")

    def error(self):
        """fisherman's last `error` event as the parser keeps it, or None
        when none came (shared/progress/error-cases.json)."""
        return self._progress.get("error")

    def can_continue(self):
        return False  # navigation unlocked by install completion


class RecoveryKeyDialog(Gtk.Dialog):
    """The QR code for the recovery key (spec recovery-key): a dialog over
    the recovery-key page, drawn from the qrcode matrix onto a DrawingArea
    with cairo. No image files, no Pillow: get_matrix() is pure Python."""

    def __init__(self, parent, key):
        super().__init__(title=_("Recovery key QR code"), transient_for=parent,
                         modal=True)
        self.set_default_size(300, 330)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        label = Gtk.Label(xalign=0)
        label.set_line_wrap(True)
        label.set_text(_("Scan this code into a password manager, then "
                         "write the key down too."))
        box.pack_start(label, False, False, 0)
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(240, 240)
        self.area.connect("draw", self._on_draw, key)
        box.pack_start(self.area, True, True, 0)
        close = self.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        close.grab_default()
        self.show_all()

    @staticmethod
    def _on_draw(area, cairo_context, key):
        import qrcode

        box = qrcode.QRCode(border=1)
        box.add_data(key)
        box.make()
        rows = box.get_matrix()
        width = area.get_allocated_width()
        height = area.get_allocated_height()
        cell = min(width, height) / max(len(rows), 1)
        cairo_context.set_source_rgb(1, 1, 1)
        cairo_context.paint()
        cairo_context.set_source_rgb(0, 0, 0)
        for y, line in enumerate(rows):
            for x, dark in enumerate(line):
                if dark:
                    cairo_context.rectangle(x * cell, y * cell, cell, cell)
                    cairo_context.fill()
        return False


def qr_available():
    """Whether the QR dialog can render (the qrcode module is installed)."""
    try:
        import qrcode  # noqa: F401
    except ImportError:
        return False
    return True


class RecoveryPage(Page):
    title = core.BRANDING.text("recovery_key_title")
    next_label = _("Done")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Recovery key"))
        self.body = Gtk.Label(xalign=0)
        self.body.set_line_wrap(True)
        self.body.set_text(core.BRANDING.text("recovery_key_body"))
        self.pack_start(self.body, False, False, 0)
        self.key_label = Gtk.Label(xalign=0, selectable=True)
        self.key_label.set_line_wrap(True)
        self.key_label.modify_font(Pango.FontDescription("monospace 11"))
        self.pack_start(self.key_label, False, False, 0)
        row = Gtk.Box(spacing=8)
        self.copy_btn = Gtk.Button(
            label=core.BRANDING.text("recovery_key_copy"))
        a11y_name(self.copy_btn, core.BRANDING.text("recovery_key_copy"))
        self.copy_btn.connect("clicked", self._on_copy)
        row.pack_start(self.copy_btn, False, False, 0)
        self.qr_btn = Gtk.Button(
            label=_("Show QR Code for Recovery Key"))
        a11y_name(self.qr_btn, _("Show QR Code for Recovery Key"))
        self.qr_btn.connect("clicked", self._on_qr)
        row.pack_start(self.qr_btn, False, False, 0)
        self.pack_start(row, False, False, 0)
        self.ack = Gtk.CheckButton(
            label=core.BRANDING.text("recovery_key_ack"))
        self.ack.connect("toggled", self._on_ack)
        self.pack_start(self.ack, False, False, 0)
        self.error_label = problem_label()
        self.pack_start(self.error_label, False, False, 0)
        self.retry_btn = Gtk.Button.new_with_mnemonic(_("_Try again"))
        self.retry_btn.set_halign(Gtk.Align.START)
        self.retry_btn.set_no_show_all(True)
        self.retry_btn.connect("clicked", lambda *_a: self.on_enter())
        self.pack_start(self.retry_btn, False, False, 0)
        self.key = ""

    def encrypted(self):
        setup = self.win.pages.get("setup")
        enc_type = setup.enc_type() if setup is not None else "none"
        return enc_type != "none"

    def should_show(self):
        try:
            return bool(self.encrypted())
        except Exception:  # noqa: BLE001 - bare doubles may lack the page
            return True

    def on_enter(self):
        self.key = ""
        self.ack.set_active(False)
        show_problem(self.error_label, None)
        if core.backend() == "daemon":
            try:
                self.key = core.get_daemon().make_recovery_key()
            except Exception as exc:  # noqa: BLE001 - recovery-key-failed
                # The daemon's error name (io.systemd.System) is for the
                # log; a person gets a sentence and Try again.
                print(f"no recovery key: {exc}", file=sys.stderr)
                show_problem(self.error_label, {"code": "", "message": _(
                    "The installer could not make a recovery key. The disk "
                    "is installed. Press Try again.")})
                self.key = ""
        else:
            progress = self.win.pages.get("progress")
            self.key = progress.recovery_key() if progress else ""
        self.retry_btn.set_visible(core.backend() == "daemon" and not self.key)
        self.key_label.set_text(self.key)
        self.qr_btn.set_visible(bool(self.key) and qr_available())
        refresh = getattr(self.win, "refresh_nav", None)
        if refresh is not None:
            refresh()

    def on_leave(self):
        """Enrol the key before leaving (daemon): gnome-setup enrols on
        Done. False keeps the wizard here with the error shown."""
        if core.backend() != "daemon" or not self.key:
            return True
        disk = ""
        destination = self.win.pages.get("destination")
        selected = destination.selected_disk() if destination else None
        if selected:
            disk = selected.get("path", "")
        # A passphrase install locks the disk with the person's passphrase,
        # not the empty one the TPM path sets: CryptEnroll needs it to
        # unlock (mock no-tpm answered PasswordIncorrect, and the page
        # never let the person go on).
        unlock = ""
        setup = self.win.pages.get("setup")
        entry = getattr(setup, "pass1", None)
        if entry is not None and core.needs_passphrase(setup.enc_type()):
            unlock = entry.get_text()
        try:
            core.get_daemon().enroll_recovery_key(disk, self.key, unlock)
        except Exception as exc:  # noqa: BLE001 - the key is shown; retry
            # The error name of the daemon (io.systemd.System) is for the
            # log; it tells a person nothing.
            print(f"the recovery key was not enrolled: {exc}", file=sys.stderr)
            show_problem(self.error_label, {
                "code": "", "message": _(
                    "The recovery key could not be saved to the disk. It does "
                    "not unlock the disk yet. Press Done to try again.")})
            return False
        return True

    def _on_copy(self, *_args):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(self.key_label.get_text(), -1)

    def _on_qr(self, *_args):
        dialog = RecoveryKeyDialog(self.get_toplevel(), self.key)
        dialog.run()
        dialog.destroy()

    def _on_ack(self, _check):
        refresh = getattr(self.win, "refresh_nav", None)
        if refresh is not None:
            refresh()

    def can_continue(self):
        # No key (recovery-key-failed) never advances: the spec forbids
        # continuing without one.
        return bool(self.key) and self.ack.get_active()


class HandoffPage(Page):
    title = _("Handoff")

    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Handoff"))
        self.body = Gtk.Label(xalign=0)
        self.body.set_line_wrap(True)
        self.pack_start(self.body, False, False, 0)
        bar = Gtk.Box(spacing=8)
        bar.set_halign(Gtk.Align.END)
        self.not_now_btn = a11y_name(Gtk.Button(label=_("Not now")), _("Not now"))
        self.not_now_btn.connect("clicked", lambda *_a: self.win.go(+1))
        bar.pack_start(self.not_now_btn, False, False, 0)
        self.continue_btn = a11y_name(
            Gtk.Button(label=_("Continue")), _("Continue"))
        self.continue_btn.get_style_context().add_class("suggested-action")
        self.continue_btn.connect("clicked", self._on_continue)
        bar.pack_start(self.continue_btn, False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.handoff_error = problem_label()
        self.pack_start(self.handoff_error, False, False, 0)

    def on_enter(self):
        mode, reason = self.handoff_mode()
        self.body.set_text(self.mode_text(mode, reason))
        show_problem(self.handoff_error, None)

    def handoff_mode(self):
        """(mode, reason): the daemon's Probe decides; missing means reboot
        on either backend."""
        if core.backend() != "daemon":
            return "reboot", ""
        try:
            info = daemon_client.probe_handoff(core.get_daemon().probe())
        except Exception:  # noqa: BLE001 - a Varlink error reply too
            return "reboot", ""
        return info["mode"], info["reason"]

    @staticmethod
    def mode_text(mode, reason):
        if mode == "migrate":
            text = _("The system is installed. The live session becomes "
                       "the installed system: nothing restarts, and what is "
                       "open stays open.")
        elif mode == "soft_reboot":
            text = _("The system is installed. Continuing restarts userspace "
                       "into it; the live session's files do not carry over.")
        else:
            text = _("The system is installed. Continuing restarts the "
                       "computer into it; remove the install media when asked.")
        # One word is an id for the log (btrfs-seed, el10, default of
        # fisherman/internal/handoff), not a sentence for a person.
        return text + (" " + reason if " " in reason.strip() else "")

    def _on_continue(self, *_args):
        if core.backend() == "daemon":
            try:
                result = core.get_daemon().handoff()
            except Exception as exc:  # noqa: BLE001 - handoff-failed
                print(f"handoff failed: {exc}", file=sys.stderr)
                show_problem(self.handoff_error, {"code": "", "message": _(
                    "The installed system could not be started from here. "
                    "Press Not now, then Restart.")})
                return
            self.win.handoff_result = result
        self.win.go(+1)

    def can_continue(self):
        return True


class DonePage(Page):
    def __init__(self, win):
        super().__init__(win)
        a11y_name(self, _("Done"))
        self.logo = product_logo(core.BRANDING.logo, core.IN_FLATPAK)
        self.logo.hide()
        self.pack_start(self.logo, False, False, 0)
        self.headline = _page_title("")
        self.pack_start(self.headline, False, False, 0)
        # "installed", "cancelled" or "failed" once set_result() has run.
        self.result = ""
        self.body = Gtk.Label(xalign=0)
        self.body.set_line_wrap(True)
        self.pack_start(self.body, False, False, 0)
        # The log of a failed install: closed, and with its own scroll bar, so
        # that the buttons stay in the window.
        self.details = Gtk.Expander(label=_("Details"))
        self.details.set_no_show_all(True)
        self.details_view = Gtk.TextView(editable=False, monospace=True,
                                         wrap_mode=Gtk.WrapMode.WORD_CHAR)
        a11y_name(self.details_view, _("Details"))
        scroll = Gtk.ScrolledWindow(hexpand=True, min_content_height=140)
        scroll.add(self.details_view)
        scroll.show_all()
        self.details.add(scroll)
        self.pack_start(self.details, False, False, 0)
        # store_label -> store_url on every frontend when the branding sets a
        # store (docs/PARITY.md); hidden otherwise.
        self.store_btn = Gtk.LinkButton(uri=core.BRANDING.store_url,
                                        label=core.BRANDING.text("store_label"))
        self.store_btn.set_no_show_all(True)
        self.pack_start(self.store_btn, False, False, 0)
        # The key lived here as a panel; it has its own screen now
        # (RecoveryPage), which gates Done on the acknowledgement.
        #
        # The page's own action row, where the wizard's Back/Next bar sits on
        # every other page (the window hides that bar here). Try again shows
        # on a failed or cancelled install; Not now on an installed one.
        # Power off opens the poweroff dialog (gates.py, mirroring GNOME's
        # dialog_poweroff.py); View install log opens the persistent log
        # with a Copy button (mirroring dialog_output.py) and shows only
        # on failure, when there is something to diagnose.
        actions = Gtk.Box(spacing=8)
        self.try_btn = Gtk.Button(label=_("Try again"))
        self.try_btn.connect("clicked", self._on_try_again)
        self.try_btn.set_no_show_all(True)
        self.reboot_btn = Gtk.Button(label=core.BRANDING.text("done_restart") or _("Restart now"))
        self.reboot_btn.get_style_context().add_class("suggested-action")
        self.reboot_btn.connect("clicked", self._on_reboot)
        self.poweroff_btn = Gtk.Button(label=_("Power off"))
        self.poweroff_btn.connect("clicked", self.__on_poweroff)
        self.log_btn = Gtk.Button(label=_("View install log"))
        self.log_btn.connect("clicked", self.__on_view_log)
        self.log_btn.set_no_show_all(True)
        self.not_now_btn = Gtk.Button(label=_("Not now"))
        self.not_now_btn.connect("clicked", self.__on_close)
        self.not_now_btn.set_no_show_all(True)
        self.close_btn = Gtk.Button(label=_("Close"))
        self.close_btn.connect("clicked", self.__on_close)
        actions.pack_end(self.reboot_btn, False, False, 0)
        actions.pack_end(self.poweroff_btn, False, False, 0)
        actions.pack_end(self.log_btn, False, False, 0)
        actions.pack_end(self.try_btn, False, False, 0)
        actions.pack_end(self.not_now_btn, False, False, 0)
        actions.pack_end(self.close_btn, False, False, 0)
        self.pack_end(actions, False, False, 0)
        self.reboot_error = problem_label()
        self.pack_start(self.reboot_error, False, False, 0)

    def _on_try_again(self, *_args):
        """Back to confirm: the person adjusts the plan and installs again."""
        self.win._enter(PAGE_ORDER.index("confirm"))

    def _on_reboot(self, *_args):
        # reboot-failed (spec done): the error shows inline with a retry
        # (this button), instead of stranding the page.
        show_problem(self.reboot_error, None)
        try:
            if core.backend() == "daemon":
                core.get_daemon().shutdown("reboot")
            else:
                core.host_run(["systemctl", "reboot"])
        except Exception as exc:  # noqa: BLE001 - reboot-failed
            show_problem(self.reboot_error, {
                "code": "", "message": str(exc) or _(
                    "Cannot restart right now. Try again.")})

    def __on_poweroff(self, *_args):
        dialog = gates.PoweroffDialog(self.get_toplevel())
        dialog.run()
        dialog.destroy()

    def __on_view_log(self, *_args):
        dialog = gates.InstallLogDialog(self.get_toplevel())
        dialog.run()
        dialog.destroy()

    def __on_close(self, *_args):
        top = self.get_toplevel()
        if isinstance(top, Gtk.Window):
            top.close()

    def set_result(self, ok, log_tail, cancelled=False, receipt=None,
                   error=None):
        """Show how the install ended: installed, cancelled or failed.

        `cancelled` is a cancel the person confirmed, or fisherman's exit
        code 130. It is not a failure and has its own heading, the copy key
        done_cancelled_title (#299). `receipt` is the progress page's
        receipt(): the done page says what it set up for the first-boot
        check, and never that the new system started. `error` is the
        progress page's error(): a failure says whether the disk was
        changed, and when the cleanup failed or timed out
        (tuna-os/fisherman#449).

        The recovery key is not shown here: RecoveryPage owns that screen,
        and gates Done on the acknowledgement."""
        self.logo.set_visible(ok and self.logo.get_pixbuf() is not None)
        self.result = "installed" if ok else ("cancelled" if cancelled else "failed")
        self.details.set_visible(False)
        self.details.set_expanded(False)
        if ok:
            self.headline.set_markup("<big><b>" + GLib.markup_escape_text(
                core.BRANDING.text("done_title")) + "</b></big>")
            # Installed, restart required: never "verified". Only the new
            # system can check its own start (shared/completion/README.md).
            self.body.set_text("\n\n".join(line for line in (
                core.BRANDING.text("done_subtitle"),
                *(completion.receipt_text(receipt, core.BRANDING.text)
                  if receipt is not None or core.backend() != "daemon"
                  else ())) if line))
            self.store_btn.set_visible(bool(core.BRANDING.store_url))
            self.reboot_btn.show()
            self.reboot_btn.set_sensitive(True)
            self.log_btn.set_visible(False)
            self.try_btn.set_visible(False)
            self.not_now_btn.set_visible(True)
            return
        self.store_btn.set_visible(False)
        self.reboot_btn.hide()
        self.not_now_btn.set_visible(False)
        self.log_btn.set_visible(True)
        self.try_btn.set_visible(True)
        if cancelled:
            self.headline.set_markup("<big><b>" + GLib.markup_escape_text(
                core.BRANDING.text("done_cancelled_title")) + "</b></big>")
            self.body.set_text(_(
                "You stopped the installation. The target disk holds an "
                "incomplete system: start the installer again to use it."
                "\n\nFull log: {path}").format(path=core.install_log_path()))
        else:
            self.headline.set_markup("<big><b>" + GLib.markup_escape_text(
                core.BRANDING.text("done_failed_title")) + "</b></big>")
            tail = readable_log(log_tail)
            reason = failure_reason(error) or (tail.splitlines() or [""])[-1].strip()
            disk_lines = progress_parser.failure_text(error, core.BRANDING.text)
            if (core.backend() == "daemon" and isinstance(error, dict)
                    and error.get("disk_changed") is None):
                # The partition step failed, or the daemon went away during
                # the install: the disk may hold new partitions or not. Say
                # so; the failure page states what happened to the disk.
                disk_lines = [_("The installer may have changed the disk."),
                              *disk_lines]
            self.body.set_text("\n\n".join(line for line in (
                *disk_lines, reason,
                _("Full log: {path}").format(path=core.install_log_path())) if line))
            self.details_view.get_buffer().set_text(tail)
            self.details.set_visible(bool(tail))


PAGE_ORDER = ["welcome", "language", "keyboard", "timezone", "network",
              "prerelease", "eula", "source", "rst", "destination", "wipe",
              "setup", "identity", "confirm", "progress", "recovery",
              "handoff", "done"]
