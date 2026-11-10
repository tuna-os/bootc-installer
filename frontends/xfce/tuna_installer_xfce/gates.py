"""Blocking gates and small dialogs, mirroring GNOME's windows/ layer.

GNOME blocks below-minimum machines before the wizard ever appears
(do_activate shows BootcRamWindow / BootcCpuWindow / BootcUnsupportedWindow
instead of BootcWindow) and confirms quitting mid-install (delete ->
AlertDialog "Exit Installer?" -> progress.terminate()). This frontend used
to warn inline on the welcome page and documented having no cancel UI at
all. These are the GTK3 equivalents, in theme colors only (DESIGN.md):

- required_gate(): which gate, if any, fisherman's probe demands. Order
  mirrors GNOME's do_activate (RAM, CPU, then UEFI) and honors the same
  IGNORE_RAM / IGNORE_CPU escape hatches its Continue buttons relaunch
  with.
- RamGateWindow / CpuGateWindow: the requirement text plus Continue anyway
  (re-executes the installer with the matching IGNORE_* set, exactly what
  GNOME's __continue does with vanilla-installer) and Close.
- UnsupportedGateWindow: the UEFI text plus Power off (on the host --
  core.host_run crosses the Flatpak sandbox) and Close.
- PoweroffDialog: power off / restart / firmware-setup row, for the done
  page. The firmware row shows only on UEFI, as in dialog_poweroff.py.
- InstallLogDialog: the persistent install log (core.install_log_path())
  with a Copy button -- GNOME's dialog_output.py, whose LOG_PATH is the
  same per-install file core.open_install_log() appends to here.
- ConfirmExitDialog: "Exit Installer? Any progress will be lost." with
  Cancel / Exit, the delete-event guard for a running install.
- ConfirmCancelDialog: the question the progress page's Cancel button asks
  before it stops a disk write half-way (#299).
"""

import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import core, locale as locale_checks


def required_gate(unmet=None):
    """Which blocking gate the machine needs, or None.

    `unmet` is fisherman's system.unmet (core.unmet_requirements()); read
    live when omitted. RAM is checked before CPU before UEFI, the order
    GNOME's do_activate uses, and IGNORE_RAM / IGNORE_CPU skip their gate
    the way GNOME's Continue buttons relaunch with them set.
    """
    if unmet is None:
        unmet = core.unmet_requirements()
    items = set(unmet or [])
    if "ram" in items and os.environ.get("IGNORE_RAM") != "1":
        return "ram"
    if "cpu" in items and os.environ.get("IGNORE_CPU") != "1":
        return "cpu"
    if "uefi" in items:
        return "unsupported"
    return None


def _gate_window(title, body):
    """A small blocking window: title, wrapped message, action row."""
    win = Gtk.Window(title=f"{core.PRODUCT_NAME} Installer")
    win.set_default_size(440, 200)
    win.set_position(Gtk.WindowPosition.CENTER)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                  margin=18)
    win.add(box)
    heading = Gtk.Label(xalign=0)
    heading.set_markup(f"<big><b>{title}</b></big>")
    box.pack_start(heading, False, False, 0)
    message = Gtk.Label(xalign=0)
    message.set_line_wrap(True)
    message.set_text(body)
    box.pack_start(message, True, True, 0)
    actions = Gtk.Box(spacing=8)
    actions.set_halign(Gtk.Align.END)
    box.pack_end(actions, False, False, 0)
    return win, actions


def _relaunch_ignoring(var):
    """Re-execute this installer with IGNORE_RAM/IGNORE_CPU set: GNOME's
    Continue buttons relaunch with the matching variable; the gate then
    clears itself via required_gate()."""
    env = dict(os.environ, **{var: "1"})
    argv = [sys.executable] + sys.argv if sys.argv[0].endswith(".py") \
        else sys.argv
    try:
        os.execvpe(argv[0], argv, env)
    except OSError:
        pass


def _gate_body(key):
    lines = [core.BRANDING.text("requirements_title"),
             core.BRANDING.text(key)]
    return "\n\n".join(line for line in lines if line)


def make_ram_gate():
    """Below-minimum-memory gate (GNOME's BootcRamWindow)."""
    win, actions = _gate_window("Not enough memory",
                                _gate_body("requirements_ram"))
    go = Gtk.Button(label="Continue anyway")
    go.connect("clicked", lambda *_: _relaunch_ignoring("IGNORE_RAM"))
    close = Gtk.Button(label="Close")
    close.connect("clicked", lambda *_: win.close())
    actions.pack_start(close, False, False, 0)
    actions.pack_start(go, False, False, 0)
    return win


def make_cpu_gate():
    """Below-minimum-CPU gate (GNOME's BootcCpuWindow)."""
    win, actions = _gate_window("Not enough processing power",
                                _gate_body("requirements_cpu"))
    go = Gtk.Button(label="Continue anyway")
    go.connect("clicked", lambda *_: _relaunch_ignoring("IGNORE_CPU"))
    close = Gtk.Button(label="Close")
    close.connect("clicked", lambda *_: win.close())
    actions.pack_start(close, False, False, 0)
    actions.pack_start(go, False, False, 0)
    return win


def make_unsupported_gate():
    """No-UEFI gate (GNOME's BootcUnsupportedWindow): nothing to continue
    to, so the action is Power off."""
    win, actions = _gate_window("Unsupported firmware",
                                _gate_body("requirements_uefi"))
    close = Gtk.Button(label="Close")
    close.connect("clicked", lambda *_: win.close())
    off = Gtk.Button(label="Power off")
    off.connect("clicked",
                lambda *_: core.host_run(["systemctl", "poweroff"]))
    actions.pack_start(close, False, False, 0)
    actions.pack_start(off, False, False, 0)
    return win


GATE_BUILDERS = {
    "ram": make_ram_gate,
    "cpu": make_cpu_gate,
    "unsupported": make_unsupported_gate,
}


class PoweroffDialog(Gtk.Dialog):
    """Power off / restart / firmware setup, for the done page.

    Mirrors dialog_poweroff.py: systemctl runs on the host (core.host_run
    crosses the Flatpak boundary), and the firmware row shows only on UEFI.
    """

    def __init__(self, parent):
        super().__init__(title="Power off", transient_for=parent, modal=True)
        self.set_default_size(360, 120)
        box = self.get_content_area()
        box.set_spacing(6)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        self.row_poweroff = Gtk.Button(label="Power off")
        self.row_reboot = Gtk.Button(label="Restart")
        self.row_firmware_setup = Gtk.Button(label="Firmware setup")
        self.row_poweroff.connect(
            "clicked", lambda *_: core.host_run(["systemctl", "poweroff"]))
        self.row_reboot.connect(
            "clicked", lambda *_: core.host_run(["systemctl", "reboot"]))
        self.row_firmware_setup.connect(
            "clicked", lambda *_: core.host_run(
                ["systemctl", "reboot", "--firmware-setup"]))
        for row in (self.row_poweroff, self.row_reboot,
                    self.row_firmware_setup):
            box.pack_start(row, False, False, 0)
        # GNOME hides the firmware row off UEFI; local check, same rule.
        self.row_firmware_setup.set_visible(locale_checks.is_uefi())
        close = self.add_button("Close", Gtk.ResponseType.CLOSE)
        close.grab_default()
        self.show_all()
        # show_all() reveals the firmware row despite set_visible(False):
        # re-hide after, the same no_show_all dance DonePage uses.
        self.row_firmware_setup.set_visible(locale_checks.is_uefi())


class InstallLogDialog(Gtk.Dialog):
    """The persistent install log with a Copy button (dialog_output.py).

    The log is the file core.open_install_log() appends fisherman's output
    to during the install, so it survives the wizard process; here it is
    shown scrolled to the end, like GNOME's dialog.
    """

    def __init__(self, parent):
        super().__init__(title="Install log", transient_for=parent,
                         modal=True)
        self.set_default_size(560, 360)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        self.log_view = Gtk.TextView(editable=False, monospace=True)
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.add(self.log_view)
        box.pack_start(scroll, True, True, 0)
        try:
            with open(core.install_log_path(), encoding="utf-8",
                      errors="replace") as fh:
                content = fh.read()
        except OSError:
            content = "Log not available."
        buf = self.log_view.get_buffer()
        buf.set_text(content or "Log not available.")
        self.log_view.scroll_mark_onscreen(buf.get_insert())
        row = Gtk.Box(spacing=8)
        row.set_halign(Gtk.Align.END)
        self.btn_copy = Gtk.Button(label="Copy")
        self.btn_copy.connect("clicked", self._on_copy)
        close = Gtk.Button(label="Close")
        close.connect("clicked", lambda *_: self.destroy())
        row.pack_start(self.btn_copy, False, False, 0)
        row.pack_start(close, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.show_all()

    def _on_copy(self, _button):
        buf = self.log_view.get_buffer()
        start, end = buf.get_bounds()
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(
            buf.get_text(start, end, False), -1)
        self.btn_copy.set_label("Copied")


class ConfirmExitDialog(Gtk.Dialog):
    """"Exit Installer? Any progress will be lost." -- the delete-event
    guard while fisherman runs (GNOME's __on_exit_clicked AlertDialog)."""

    def __init__(self, parent):
        super().__init__(title="Exit Installer?", transient_for=parent,
                         modal=True)
        self.set_default_size(380, 120)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        body = Gtk.Label(xalign=0)
        body.set_line_wrap(True)
        body.set_text("Any progress will be lost.")
        box.pack_start(body, True, True, 0)
        row = Gtk.Box(spacing=8)
        row.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.response(Gtk.ResponseType.CANCEL))
        done = Gtk.Button(label="Exit")
        done.get_style_context().add_class("destructive-action")
        done.connect("clicked", lambda *_: self.response(Gtk.ResponseType.OK))
        row.pack_start(cancel, False, False, 0)
        row.pack_start(done, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.show_all()


class ConfirmCancelDialog(Gtk.Dialog):
    """"Cancel the installation?" -- asked before the progress page's Cancel
    button stops fisherman. A stray click must not stop a disk write
    half-way, so the safe answer is the default."""

    def __init__(self, parent):
        super().__init__(title="Cancel the installation?", transient_for=parent,
                         modal=True)
        self.set_default_size(400, 120)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        body = Gtk.Label(xalign=0)
        body.set_line_wrap(True)
        body.set_text("The installation stops and the disk is left "
                      "incomplete. You can start again afterwards.")
        box.pack_start(body, True, True, 0)
        row = Gtk.Box(spacing=8)
        row.set_halign(Gtk.Align.END)
        self.keep_btn = Gtk.Button(label="Continue installing")
        self.keep_btn.connect("clicked", lambda *_a: self.response(Gtk.ResponseType.CANCEL))
        self.stop_btn = Gtk.Button(label="Cancel installation")
        self.stop_btn.get_style_context().add_class("destructive-action")
        self.stop_btn.connect("clicked", lambda *_a: self.response(Gtk.ResponseType.OK))
        row.pack_start(self.keep_btn, False, False, 0)
        row.pack_start(self.stop_btn, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.show_all()
        self.keep_btn.grab_focus()
