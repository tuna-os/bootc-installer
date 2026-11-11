"""TunaOS installer for XFCE — classic GTK3 wizard. Design: ../DESIGN.md.
Flow and recipe contract: ../../INSTALLER-FRONTENDS.md."""

import os
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from bootc_shared import progress as progress_parser  # noqa: E402
from bootc_shared import redact  # noqa: E402
from bootc_shared import source_check  # noqa: E402
from bootc_shared import validate as fisherman_validate  # noqa: E402

from . import core, gates, locale as locale_checks
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
    the UI thread, answered on it (shared/recipe/README.md)."""
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
    entry = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
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


class WelcomePage(Page):
    # Flavour text is branding copy (shared/branding): the product's own
    # welcome line first, then what this assistant does.
    title = core.BRANDING.text("welcome_title")

    def __init__(self, win):
        super().__init__(win)
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
        # A first-run tour of the catalog's image families (tour.py), shown
        # where a newcomer actually waits. Below-minimum machines never
        # reach this page: the app shows a blocking RAM/CPU/UEFI gate
        # instead (gates.py), so there is no warn-inline here anymore.
        # GNOME blocks the same way; warn-and-continue was this
        # frontend's alone.
        self.tour = tour.TourCarousel()
        self.pack_start(self.tour, False, False, 0)
        self.tour.set_slides(tour.slides_from_catalog(core.load_catalog().roots))


class SourcePage(Page):
    title = _("What do you want to install?")

    def __init__(self, win):
        super().__init__(win)
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
                "Check that fisherman's images.json is installed.")), False, False, 0)
        self.listbox.show_all()
        self._sync_hint()

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
        self.radios = []
        self.listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.pack_start(self.listbox, False, False, 0)
        self.warn = _warn_row("")
        self.warn_label = self.warn.get_children()[1]
        self.pack_end(self.warn, False, False, 0)

    def on_enter(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        self.radios = []
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
            self.listbox.pack_start(_warn_row(
                _("Could not detect disks: {error}").format(error=error) if error else
                _("No disk of at least 50 GiB was found. Connect one to install to.")),
                False, False, 4)
        self.listbox.show_all()
        self._update_warning()

    def _update_warning(self, *_args):
        d = self.selected_disk()
        if d:
            self.warn_label.set_text(
                _("Everything on {title} ({path}) will be erased.").format(
                    title=d["title"], path=d["path"]))
        self.warn.set_visible(d is not None)

    def can_continue(self):
        return self.selected_disk() is not None

    def selected_disk(self):
        for r in self.radios:
            if r.get_active():
                return r.disk
        return None


FILESYSTEMS = core.FILESYSTEMS


class SetupPage(Page):
    # "Disk encryption" is a keyword of the shared screen contract
    # (shared/walkthrough/parity_report.py). With the old title, "Filesystem
    # and encryption", this page matched nothing and the parity matrix showed
    # XFCE as the one frontend without an encryption screen it plainly has.
    title = _("Disk encryption")

    def __init__(self, win):
        super().__init__(win)
        self.has_tpm = core.has_tpm()

        self.enc_radios = []
        group = None
        for value in ENCRYPTION_TYPES:
            if core.needs_tpm2(value) and not self.has_tpm:
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
        self._sync()

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
                self.fs_combo.append(fs, fs)
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
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        # Seeded from the selected image's default_hostname, else the
        # branding's (on_enter), until the person types one.
        self._hostname_edited = False
        self._hostname_syncing = False
        self.hostname = Gtk.Entry(text=core.BRANDING.default_hostname)
        self.hostname.connect("changed", self._on_hostname_changed)
        grid.attach(Gtk.Label(label=_("Hostname"), xalign=0), 0, 0, 1, 1)
        grid.attach(self.hostname, 1, 0, 1, 1)
        self.hostname_problem = problem_label()
        grid.attach(self.hostname_problem, 1, 1, 1, 1)
        self.pack_start(grid, False, False, 0)

        self.user_frame = Gtk.Frame(label=_("Your account"), margin_top=8)
        ug = Gtk.Grid(column_spacing=12, row_spacing=6, margin=10)
        self.username = Gtk.Entry()
        self.fullname = Gtk.Entry()
        # Asked twice, each with a reveal icon: one typo in a single hidden
        # entry made an account nobody could sign in to (#295).
        self.password = password_entry()
        self.password2 = password_entry()
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

        # Keyboard layout (locale.py). It applies to this live session as it
        # changes (setxkbmap), so the passphrase typed here is the one the
        # person means; the label says "this session only" because nothing
        # here reaches the installed system. This expander also held a
        # Language and a Timezone combo whose values nothing read (#292).
        # The recipe has no field for the three yet (tuna-os/fisherman#405).
        loc = Gtk.Expander(label=_("Keyboard layout (this session only)"))
        locbox = Gtk.Grid(column_spacing=12, row_spacing=6, margin=6)
        self.kb_combo = Gtk.ComboBoxText()
        for name in locale_checks.available_keyboard_layouts():
            self.kb_combo.append(name, name)
        self._select_combo(self.kb_combo, locale_checks.current_keyboard_layout())
        self.kb_combo.connect("changed", self._on_keyboard_changed)
        locbox.attach(Gtk.Label(label=_("Keyboard"), xalign=0), 0, 0, 1, 1)
        locbox.attach(self.kb_combo, 1, 0, 1, 1)
        loc.add(locbox)
        self.locale_expander = loc
        self.pack_start(loc, False, False, 0)

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
        return partial

    def _on_checked(self, problems, error):
        problems = problems or []
        self.problems = {f: next((p for p in problems if p.get("field") == f), None)
                         for f in ("hostname", "user.username")}
        show_problem(self.hostname_problem, self.problems["hostname"])
        show_problem(self.username_problem, self.problems["user.username"])
        self.win.refresh_nav()

    @staticmethod
    def _select_combo(combo, value):
        """Select `value`, adding it first when the system reports one the
        list does not contain (a live session can outrun localectl)."""
        if value and combo.get_model() is not None:
            ids = [row[1] for row in combo.get_model()]
            if value not in ids:
                combo.append(value, value)
        combo.set_active_id(value)

    def _on_keyboard_changed(self, combo):
        layout = combo.get_active_id()
        if layout:
            locale_checks.apply_keyboard_layout(layout)

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
        # confirm_subtitle and confirm_body are the product's own lines
        # (a quote, a tagline); empty in the neutral defaults, so hidden.
        self.subtitle = Gtk.Label(xalign=0)
        self.subtitle.set_line_wrap(True)
        self.subtitle.set_no_show_all(True)
        self.pack_start(self.subtitle, False, False, 0)
        self.summary = Gtk.Label(xalign=0)
        self.summary.set_line_wrap(True)
        self.pack_start(self.summary, False, False, 0)
        # The source check (#266) and this computer's bootc storage (#267):
        # what fisherman's probe says about the selected image. Only a
        # blocked source holds Install.
        self.source_label = Gtk.Label(xalign=0)
        self.source_label.set_line_wrap(True)
        self.source_label.set_selectable(True)
        self.source_label.set_no_show_all(True)
        self.pack_start(self.source_label, False, False, 0)
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
        r = self.win.build_recipe()
        disk = r.get("disk") or self.win.pages["destination"].selected_disk()["path"]
        # The same rows, in the same order, as KDE's confirm step.
        rows = [
            (_("Target disk"), disk),
            (_("Filesystem"), r["filesystem"]),
            (_("Encryption"), encryption_text(r["encryption"]["type"] or "none", "_label")),
            (_("Hostname"), r["hostname"]),
            (_("Image"), r.get("image") or self.win.pages["source"].live_image
             or _("this live system")),
        ]
        if r.get("targetImgref") and r["targetImgref"] != r.get("image"):
            # The image that updates follow, when it is not the one installed.
            rows.append((_("Updates from"), r["targetImgref"]))
        if r.get("user", {}).get("username"):
            rows.append((_("User"), r["user"]["username"]))
        width = max(len(k) for k, _value in rows) + 2
        lines = [f"{k + ':':<{width}}{v}" for k, v in rows]
        self.summary.set_markup("<tt>" + GLib.markup_escape_text("\n".join(lines)) + "</tt>")
        selected = self.win.pages["destination"].selected_disk()
        warn_key = (
            "confirm_warning_removable"
            if selected and selected.get("removable")
            else "confirm_warning"
        )
        self.warn_text.set_text(core.BRANDING.text(warn_key, disk=disk))
        self._check_source(r)
        self._check_network()

    def _check_source(self, recipe):
        """Probe the selected source off the UI thread, and drop a reply
        for an older visit. The probe gets image references only."""
        self.source_generation += 1
        generation = self.source_generation
        self.source_blocked = False
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
            view, source_check.bootc_store(result), core.BRANDING.text))
        refresh = getattr(self.win, "refresh_nav", None)
        if refresh is not None:
            refresh()
        return False

    def _show_source(self, rows):
        lines = [title + ("\n    " + subtitle if subtitle else "") for title, subtitle in rows]
        self.source_label.set_text("\n".join(lines))
        self.source_label.set_visible(bool(lines))

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
        return self.net_ok and not self.source_blocked


class ProgressPage(Page):
    title = core.BRANDING.text("progress_title")

    def __init__(self, win):
        super().__init__(win)
        self.steplabel = Gtk.Label(xalign=0)
        self.pack_start(self.steplabel, False, False, 0)
        self.bar = Gtk.ProgressBar(show_text=True)
        self.pack_start(self.bar, False, False, 0)
        # progress_note ("Do not power off the computer.") -- the one warning
        # that matters while the disk is being written. Empty hides it.
        self.note = Gtk.Label(label=core.BRANDING.text("progress_note"), xalign=0)
        self.note.get_style_context().add_class("dim-label")
        self.note.set_no_show_all(not self.note.get_text())
        self.pack_start(self.note, False, False, 0)
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
        self.cancel_btn.connect("clicked", self._on_cancel)
        actions.pack_start(self.cancel_btn, False, False, 0)
        self.pack_end(actions, False, False, 0)

    def on_enter(self):
        self.cancel_btn.set_sensitive(True)
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

    def recovery_key(self):
        """The key fisherman emitted, or "" for a non-TPM install.

        The parser has tracked this all along (shared/progress/README.md);
        nothing read it, which is how it stayed a log line only.
        """
        return self._progress.get("recovery_key", "")

    def can_continue(self):
        return False  # navigation unlocked by install completion


class DonePage(Page):
    def __init__(self, win):
        super().__init__(win)
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
        # store_label -> store_url on every frontend when the branding sets a
        # store (docs/PARITY.md); hidden otherwise.
        self.store_btn = Gtk.LinkButton(uri=core.BRANDING.store_url,
                                        label=core.BRANDING.text("store_label"))
        self.store_btn.set_no_show_all(True)
        self.pack_start(self.store_btn, False, False, 0)
        # Recovery key (#129). fisherman emits it once, after TPM enrolment,
        # and for a tpm2-luks install it is the only way back into the disk
        # if the TPM state changes. Writing it to the log pane was the
        # mitigation; the log scrolls and nothing pauses, so a user could
        # reach this page and reboot having never seen it.
        #
        # This is a panel rather than the modal #129 suggested: a dialog is
        # dismissed and then the key is gone, while this keeps it on screen
        # for as long as it takes to write down. The gate is on the reboot
        # button, which is the action that ends the chance to read it.
        self.recovery_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.recovery_box.set_no_show_all(True)
        self.recovery_title = _page_title("")
        self.recovery_box.pack_start(self.recovery_title, False, False, 0)
        self.recovery_body = Gtk.Label(xalign=0)
        self.recovery_body.set_line_wrap(True)
        self.recovery_box.pack_start(self.recovery_body, False, False, 0)
        self.recovery_key_label = Gtk.Label(xalign=0, selectable=True)
        self.recovery_key_label.set_line_wrap(True)
        self.recovery_key_label.modify_font(Pango.FontDescription("monospace 11"))
        self.recovery_box.pack_start(self.recovery_key_label, False, False, 0)
        self.recovery_copy_btn = Gtk.Button(
            label=core.BRANDING.text("recovery_key_copy"))
        self.recovery_copy_btn.connect("clicked", self.__on_copy)
        self.recovery_box.pack_start(self.recovery_copy_btn, False, False, 0)
        self.recovery_ack = Gtk.CheckButton(
            label=core.BRANDING.text("recovery_key_ack"))
        self.recovery_ack.connect("toggled", self.__on_ack)
        self.recovery_box.pack_start(self.recovery_ack, False, False, 0)
        self.pack_start(self.recovery_box, False, False, 8)

        # The page's own action row, where the wizard's Back/Next bar sits on
        # every other page (the window hides that bar here): Close, and
        # Restart now -- held while a recovery key is unacknowledged.
        # Power off opens the poweroff dialog (gates.py, mirroring GNOME's
        # dialog_poweroff.py); View install log opens the persistent log
        # with a Copy button (mirroring dialog_output.py) and shows only
        # on failure, when there is something to diagnose.
        actions = Gtk.Box(spacing=8)
        self.reboot_btn = Gtk.Button(label=core.BRANDING.text("done_restart") or _("Restart now"))
        self.reboot_btn.get_style_context().add_class("suggested-action")
        self.reboot_btn.connect("clicked", lambda *_args: core.host_run(["systemctl", "reboot"]))
        self.poweroff_btn = Gtk.Button(label=_("Power off"))
        self.poweroff_btn.connect("clicked", self.__on_poweroff)
        self.log_btn = Gtk.Button(label=_("View install log"))
        self.log_btn.connect("clicked", self.__on_view_log)
        self.log_btn.set_no_show_all(True)
        self.close_btn = Gtk.Button(label=_("Close"))
        self.close_btn.connect("clicked", self.__on_close)
        actions.pack_end(self.reboot_btn, False, False, 0)
        actions.pack_end(self.poweroff_btn, False, False, 0)
        actions.pack_end(self.log_btn, False, False, 0)
        actions.pack_end(self.close_btn, False, False, 0)
        self.pack_end(actions, False, False, 0)

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

    def __on_copy(self, *_args):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(self.recovery_key_label.get_text(), -1)

    def __on_ack(self, check):
        self.reboot_btn.set_sensitive(check.get_active())

    def show_recovery_key(self, key):
        """Reveal the panel and gate reboot behind the acknowledgement.

        No key means no panel and no gate: a non-TPM install must not be
        asked to tick a box about a key it was never given.
        """
        key = (key or "").strip()
        self.recovery_box.set_visible(bool(key))
        if not key:
            self.reboot_btn.set_sensitive(True)
            return
        self.recovery_title.set_markup("<big><b>" + GLib.markup_escape_text(
            core.BRANDING.text("recovery_key_title")) + "</b></big>")
        self.recovery_body.set_text(core.BRANDING.text("recovery_key_body"))
        self.recovery_key_label.set_text(key)
        self.recovery_ack.set_active(False)
        self.reboot_btn.set_sensitive(False)
        # show_all() is a no-op while no_show_all is set -- that flag exists
        # to stop the window's own show_all() revealing the panel on a
        # non-TPM install. Lift it for this one call, or the box appears with
        # none of its children in it: the capture drew an empty panel and the
        # key never reached the screen.
        self.recovery_box.set_no_show_all(False)
        self.recovery_box.show_all()
        self.recovery_box.set_no_show_all(True)

    def set_result(self, ok, log_tail, recovery_key="", cancelled=False):
        """Show how the install ended: installed, cancelled or failed.

        `cancelled` is a cancel the person confirmed, or fisherman's exit
        code 130. It is not a failure and has its own heading, the copy key
        done_cancelled_title (#299)."""
        # Only a finished install enrolled a TPM, so only it has a key.
        self.show_recovery_key(recovery_key if ok else "")
        self.logo.set_visible(ok and self.logo.get_pixbuf() is not None)
        self.result = "installed" if ok else ("cancelled" if cancelled else "failed")
        if ok:
            self.headline.set_markup("<big><b>" + GLib.markup_escape_text(
                core.BRANDING.text("done_title")) + "</b></big>")
            # Installed, restart required: never "verified". Only the new
            # system can check its own start (shared/completion/README.md).
            self.body.set_text("\n\n".join(line for line in (
                core.BRANDING.text("done_subtitle"),
                core.BRANDING.text("done_verification")) if line))
            self.store_btn.set_visible(bool(core.BRANDING.store_url))
            self.reboot_btn.show()
            self.log_btn.set_visible(False)
            return
        self.store_btn.set_visible(False)
        self.reboot_btn.hide()
        self.log_btn.set_visible(True)
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
            self.body.set_text(_(
                "The last lines of the install log:\n\n{log}"
                "\n\nFull log: {path}").format(log=log_tail, path=core.install_log_path()))


PAGE_ORDER = ["welcome", "source", "destination", "setup", "identity",
              "confirm", "progress", "done"]
