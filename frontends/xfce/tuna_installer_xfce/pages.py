"""TunaOS installer for XFCE — classic GTK3 wizard. Design: ../DESIGN.md.
Flow and recipe contract: ../../INSTALLER-FRONTENDS.md."""

import os
import re

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

from . import core

HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$")

PIPELINE_STEPS = [
    "Partitioning disk", "Formatting boot partitions", "Setting up encryption",
    "Formatting root filesystem", "Mounting target", "Installing image",
    "Copying Flatpaks", "Writing hostname", "Finalizing boot entries",
]

ENCRYPTION_CHOICES = [
    ("none", "No encryption", "Anyone with the disk can read your files."),
    ("luks-passphrase", "Passphrase", "You'll type it at every boot."),
    ("tpm2-luks", "TPM", "Unlocks automatically on this hardware."),
    ("tpm2-luks-passphrase", "TPM + passphrase", "Automatic unlock, passphrase as fallback."),
]


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
    title = f"Welcome to {core.PRODUCT_NAME}"

    def __init__(self, win):
        super().__init__(win)
        body = Gtk.Label(xalign=0)
        body.set_line_wrap(True)
        body.set_text(
            f"This assistant installs {core.PRODUCT_NAME} on this computer.\n\n"
            "You'll choose what to install and where; nothing is written to "
            "any disk until you confirm on the final step.")
        self.pack_start(body, False, False, 0)


class SourcePage(Page):
    title = "What do you want to install?"

    def __init__(self, win):
        super().__init__(win)
        self.live_ref = core.live_iso_image()
        self.stores = core.offline_stores()
        self.offline_refs = core.offline_images(self.stores) if self.stores else set()
        _, _, self.catalog = core.load_catalog()
        self.leaves = [l for root in self.catalog for l in root.leaves()]

        self.radios = []
        group = None

        def add_radio(label_text, sub, payload, offline):
            nonlocal group
            radio = Gtk.RadioButton.new_with_label_from_widget(group, label_text)
            group = group or radio
            radio.payload = payload
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.pack_start(radio, False, False, 0)
            subline = Gtk.Label(xalign=0)
            tagged = f"{sub}   [available offline]" if offline else sub
            subline.set_markup(
                f"<small><tt>{GLib.markup_escape_text(tagged)}</tt></small>")
            subline.set_margin_start(26)
            box.pack_start(subline, False, False, 0)
            self.listbox.pack_start(box, False, False, 4)
            self.radios.append(radio)

        self.listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.add(self.listbox)
        self.pack_start(scroll, True, True, 0)

        if self.live_ref:
            add_radio(f"Install {core.PRODUCT_NAME} (this system)",
                      "no download required", {"live": True}, True)

        def sort_key(leaf):
            return (leaf.imgref not in self.offline_refs, leaf.name)

        for leaf in sorted(self.leaves, key=sort_key):
            add_radio(leaf.name, leaf.imgref, {"leaf": leaf},
                      leaf.imgref in self.offline_refs)
        if not self.radios:
            self.pack_start(_warn_row(
                "No image catalog found and this is not a live system. "
                "Check that fisherman's images.json is installed."), False, False, 0)
        self.listbox.show_all()

    def can_continue(self):
        return bool(self.radios)

    def selection(self):
        for r in self.radios:
            if r.get_active():
                return r.payload
        return None


class DestinationPage(Page):
    title = f"Where should {core.PRODUCT_NAME} be installed?"

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
        for disk in core.candidate_disks():
            text = f"{disk['model']}    {core.human_size(disk['size'])}    {disk['path']}"
            radio = Gtk.RadioButton.new_with_label_from_widget(group, text)
            group = group or radio
            radio.disk = disk
            radio.connect("toggled", self._update_warning)
            self.listbox.pack_start(radio, False, False, 4)
            self.radios.append(radio)
        self.listbox.show_all()
        self._update_warning()

    def _update_warning(self, *_):
        d = self.selected_disk()
        if d:
            self.warn_label.set_text(
                f"Everything on {d['model']} ({d['path']}) will be erased.")
        self.warn.set_visible(d is not None)

    def can_continue(self):
        return self.selected_disk() is not None

    def selected_disk(self):
        for r in self.radios:
            if r.get_active():
                return r.disk
        return None


class SetupPage(Page):
    title = "Filesystem and encryption"

    def __init__(self, win):
        super().__init__(win)
        self.has_tpm = os.path.exists("/sys/class/tpm/tpm0")

        self.enc_radios = []
        group = None
        for value, label, explain in ENCRYPTION_CHOICES:
            if value.startswith("tpm2") and not self.has_tpm:
                continue
            radio = Gtk.RadioButton.new_with_label_from_widget(group, label)
            group = group or radio
            radio.value = value
            radio.connect("toggled", self._sync)
            self.pack_start(radio, False, False, 0)
            sub = Gtk.Label(xalign=0)
            sub.set_markup(f"<small>{GLib.markup_escape_text(explain)}</small>")
            sub.set_margin_start(26)
            self.pack_start(sub, False, False, 0)
            self.enc_radios.append(radio)

        grid = Gtk.Grid(column_spacing=12, row_spacing=6, margin_top=6)
        self.pass1 = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
        self.pass2 = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
        for e in (self.pass1, self.pass2):
            e.connect("changed", lambda *_: self.win.refresh_nav())
        grid.attach(Gtk.Label(label="Passphrase", xalign=0), 0, 0, 1, 1)
        grid.attach(self.pass1, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Confirm", xalign=0), 0, 1, 1, 1)
        grid.attach(self.pass2, 1, 1, 1, 1)
        self.pass_grid = grid
        self.pack_start(grid, False, False, 0)

        adv = Gtk.Expander(label="Advanced")
        advbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)
        self.fs_combo = Gtk.ComboBoxText()
        for fs in ("xfs", "ext4", "btrfs", "zfs"):
            self.fs_combo.append(fs, fs)
        self.fs_combo.set_active_id("xfs")
        fsrow = Gtk.Box(spacing=8)
        fsrow.pack_start(Gtk.Label(label="Filesystem", xalign=0), False, False, 0)
        fsrow.pack_start(self.fs_combo, False, False, 0)
        advbox.pack_start(fsrow, False, False, 0)
        self.subvol_check = Gtk.CheckButton(label="Create btrfs subvolumes (@, @home, @snapshots)")
        advbox.pack_start(self.subvol_check, False, False, 0)
        adv.add(advbox)
        self.pack_start(adv, False, False, 0)
        self._sync()

    def _sync(self, *_):
        self.pass_grid.set_sensitive("passphrase" in self.enc_type())
        self.win.refresh_nav()

    def enc_type(self):
        for r in self.enc_radios:
            if r.get_active():
                return r.value
        return "none"

    def can_continue(self):
        if "passphrase" in self.enc_type():
            p1, p2 = self.pass1.get_text(), self.pass2.get_text()
            return bool(p1) and p1 == p2
        return True

    def default_filesystem(self, leaf_default):
        # Catalog default wins unless the user touched Advanced.
        return self.fs_combo.get_active_id() or leaf_default or "xfs"


class IdentityPage(Page):
    title = "Name this computer"

    def __init__(self, win):
        super().__init__(win)
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        self.hostname = Gtk.Entry(text="tunaos")
        self.hostname.connect("changed", lambda *_: win.refresh_nav())
        grid.attach(Gtk.Label(label="Hostname", xalign=0), 0, 0, 1, 1)
        grid.attach(self.hostname, 1, 0, 1, 1)
        self.pack_start(grid, False, False, 0)

        self.user_frame = Gtk.Frame(label="Your account", margin_top=8)
        ug = Gtk.Grid(column_spacing=12, row_spacing=6, margin=10)
        self.username = Gtk.Entry()
        self.fullname = Gtk.Entry()
        self.password = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
        for i, (lbl, entry) in enumerate((("Username", self.username),
                                          ("Full name", self.fullname),
                                          ("Password", self.password))):
            ug.attach(Gtk.Label(label=lbl, xalign=0), 0, i, 1, 1)
            ug.attach(entry, 1, i, 1, 1)
            entry.connect("changed", lambda *_: win.refresh_nav())
        self.user_frame.add(ug)
        self.pack_start(self.user_frame, False, False, 0)

    def on_enter(self):
        self.user_frame.set_visible(self.win.needs_user_creation())

    def can_continue(self):
        if not HOSTNAME_RE.match(self.hostname.get_text()):
            return False
        if self.win.needs_user_creation():
            return bool(self.username.get_text()) and bool(self.password.get_text())
        return True


class ConfirmPage(Page):
    title = "Ready to install"

    def __init__(self, win):
        super().__init__(win)
        self.summary = Gtk.Label(xalign=0)
        self.summary.set_line_wrap(True)
        self.pack_start(self.summary, False, False, 0)
        self.pack_start(_warn_row(
            "Clicking Install Now erases the selected disk. "
            "This cannot be undone."), False, False, 0)

    def on_enter(self):
        r = self.win.build_recipe()
        lines = [
            f"Image:       {r.get('image') or 'this live system'}",
            f"Disk:        {self.win.pages['destination'].selected_disk()['path']}",
            f"Filesystem:  {r['filesystem']}",
            f"Encryption:  {r['encryption']['type']}",
            f"Hostname:    {r['hostname']}",
        ]
        if r.get("additionalImageStores"):
            lines.append(f"Offline stores: {', '.join(r['additionalImageStores'])}")
        if r.get("user", {}).get("username"):
            lines.append(f"User:        {r['user']['username']}")
        self.summary.set_markup("<tt>" + GLib.markup_escape_text("\n".join(lines)) + "</tt>")


class ProgressPage(Page):
    title = f"Installing {core.PRODUCT_NAME}"

    def __init__(self, win):
        super().__init__(win)
        self.steplabel = Gtk.Label(xalign=0)
        self.pack_start(self.steplabel, False, False, 0)
        self.bar = Gtk.ProgressBar(show_text=True)
        self.pack_start(self.bar, False, False, 0)
        # Log visible by default — XFCE users want the output (DESIGN.md).
        self.logview = Gtk.TextView(editable=False, monospace=True)
        self.logview.modify_font(Pango.FontDescription("monospace 9"))
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.add(self.logview)
        self.pack_start(scroll, True, True, 0)

    def on_enter(self):
        self.win.start_install(self)

    def append_log(self, text):
        buf = self.logview.get_buffer()
        buf.insert(buf.get_end_iter(), text)
        mark = buf.create_mark(None, buf.get_end_iter(), False)
        self.logview.scroll_mark_onscreen(mark)
        # crude step mapping: fisherman prefixes steps as "[n/9]"
        m = re.search(r"\[(\d)/9\]", text)
        if m:
            step = int(m.group(1))
            self.steplabel.set_text(PIPELINE_STEPS[step - 1])
            frac = step / 9.0
            self.bar.set_fraction(frac)
            self.win.trawl.set_fill(frac)

    def can_continue(self):
        return False  # navigation unlocked by install completion


class DonePage(Page):
    def __init__(self, win):
        super().__init__(win)
        self.headline = _page_title("")
        self.pack_start(self.headline, False, False, 0)
        self.body = Gtk.Label(xalign=0)
        self.body.set_line_wrap(True)
        self.pack_start(self.body, False, False, 0)
        self.reboot_btn = Gtk.Button(label="Reboot")
        self.reboot_btn.connect("clicked", lambda *_: core.host_run(["systemctl", "reboot"]))
        self.pack_start(self.reboot_btn, False, False, 8)

    def set_result(self, ok, log_tail):
        if ok:
            self.headline.set_markup("<big><b>Installation complete</b></big>")
            self.body.set_text("Remove the installation medium, then reboot "
                               "into your new system.")
            self.reboot_btn.show()
        else:
            self.headline.set_markup("<big><b>Installation failed</b></big>")
            self.body.set_text(
                "The last lines of the install log:\n\n" + log_tail +
                "\n\nFull log: " + core.install_log_path())
            self.reboot_btn.hide()


PAGE_ORDER = ["welcome", "source", "destination", "setup", "identity",
              "confirm", "progress", "done"]
