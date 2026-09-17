"""Application composition and install-process orchestration."""

import os
import shutil
import signal

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from . import core, readiness
from .pages import (
    PAGE_ORDER,
    ConfirmPage,
    DestinationPage,
    DonePage,
    IdentityPage,
    ProgressPage,
    SetupPage,
    SourcePage,
    WelcomePage,
)
from .trawlline import TrawlLine


class InstallerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=f"{core.PRODUCT_NAME} Installer",
                         default_width=640, default_height=520)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)

        self.trawl = TrawlLine(len(PAGE_ORDER))
        outer.pack_start(self.trawl, False, False, 6)

        self.stack = Gtk.Stack()
        outer.pack_start(self.stack, True, True, 0)

        nav = Gtk.Box(spacing=8, margin=12)
        self.back_btn = Gtk.Button(label="Back")
        self.next_btn = Gtk.Button(label="Next")
        self.back_btn.connect("clicked", lambda *_: self.go(-1))
        self.next_btn.connect("clicked", lambda *_: self.go(+1))
        nav.pack_end(self.next_btn, False, False, 0)
        nav.pack_end(self.back_btn, False, False, 0)
        outer.pack_end(nav, False, False, 0)

        self.pages = {
            "welcome": WelcomePage(self), "source": SourcePage(self),
            "destination": DestinationPage(self), "setup": SetupPage(self),
            "identity": IdentityPage(self), "confirm": ConfirmPage(self),
            "progress": ProgressPage(self), "done": DonePage(self),
        }
        for name in PAGE_ORDER:
            self.stack.add_named(self.pages[name], name)
        self.index = 0
        self._log_tail = []
        self._install_log = None
        self.show_all()
        self._enter(0)

    def go(self, delta):
        self._enter(self.index + delta)

    def _enter(self, i):
        self.index = max(0, min(len(PAGE_ORDER) - 1, i))
        name = PAGE_ORDER[self.index]
        page = self.pages[name]
        self.stack.set_visible_child_name(name)
        self.trawl.set_step(self.index)
        page.on_enter()
        self.refresh_nav()

    def refresh_nav(self):
        if not getattr(self, "pages", None):
            return
        name = PAGE_ORDER[self.index]
        page = self.pages[name]
        self.back_btn.set_sensitive(name not in ("progress", "done") and self.index > 0)
        self.next_btn.set_visible(name not in ("progress", "done"))
        self.next_btn.set_sensitive(page.can_continue())
        self.next_btn.set_label("Install Now" if name == "confirm" else "Next")
        ctx = self.next_btn.get_style_context()
        if name == "confirm":
            ctx.add_class("destructive-action")
        else:
            ctx.remove_class("destructive-action")

    def selected_leaf(self):
        sel = self.pages["source"].selection() or {}
        return sel.get("leaf")

    def needs_user_creation(self):
        leaf = self.selected_leaf()
        return leaf.needs_user_creation if leaf else True

    def build_recipe(self):
        """Read page widgets and adapt their values to the core recipe API."""
        src, setup = self.pages["source"], self.pages["setup"]
        leaf = self.selected_leaf()
        disk = self.pages["destination"].selected_disk()
        identity = self.pages["identity"]
        return core.build_recipe(
            disk=disk["path"],
            filesystem=setup.default_filesystem(leaf.filesystem if leaf else ""),
            btrfs_subvolumes=setup.subvol_check.get_active(),
            encryption_type=setup.enc_type(),
            passphrase=setup.pass1.get_text(),
            image=leaf.imgref if leaf else "",
            hostname=identity.hostname.get_text(),
            bootloader=leaf.bootloader if leaf else "",
            composefs=leaf.composefs if leaf else False,
            flatpaks=leaf.flatpaks if leaf else "",
            stores=src.stores,
            needs_user=self.needs_user_creation(),
            username=identity.username.get_text(),
            fullname=identity.fullname.get_text(),
            password=identity.password.get_text(),
        )

    def start_install(self, progress_page):
        if core.dry_run():
            self._start_dry_run(progress_page)
            return

        recipe_path = core.write_recipe(self.build_recipe())
        argv = core.fisherman_argv(recipe_path)
        self._log_tail = []
        self._install_log = core.open_install_log()
        self._install_log.write(f"=== install started: {core.fisherman_shell(recipe_path)} ===\n")
        self._install_log.flush()
        flags = GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.DO_NOT_REAP_CHILD
        pid, _in, out, err = GLib.spawn_async(
            argv, flags=flags, standard_output=True, standard_error=True)
        for fd in (out, err):
            channel = GLib.IOChannel.unix_new(fd)
            channel.set_flags(GLib.IOFlags.NONBLOCK)
            GLib.io_add_watch(channel, GLib.IO_IN | GLib.IO_HUP,
                              self._on_output, progress_page)
        GLib.child_watch_add(pid, self._on_exit, recipe_path)

    def _start_dry_run(self, progress_page):
        """Play a fisherman transcript through the real progress page."""
        self._log_tail = []
        lines = list(core.DRY_RUN_TRANSCRIPT)

        def pump():
            if not lines:
                self.pages["done"].set_result(True, "".join(self._log_tail))
                self._enter(PAGE_ORDER.index("done"))
                return False
            text = lines.pop(0)
            self._log_tail = (self._log_tail + [text])[-15:]
            progress_page.append_log(text)
            return True

        GLib.timeout_add(400, pump)

    def _on_output(self, channel, cond, page):
        if cond & GLib.IO_IN:
            _status, text, _length, _term = channel.read_line()
            if text:
                self._log_tail = (self._log_tail + [text])[-15:]
                if self._install_log:
                    self._install_log.write(text)
                    self._install_log.flush()
                page.append_log(text)
        return not (cond & GLib.IO_HUP)

    def _on_exit(self, pid, status, recipe_path):
        GLib.spawn_close_pid(pid)
        shutil.rmtree(core.recipe_dir(recipe_path), ignore_errors=True)
        ok = os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
        if self._install_log:
            outcome = "ok" if ok else f"failed (status {status})"
            self._install_log.write(f"=== fisherman exited: {outcome} ===\n")
            self._install_log.close()
            self._install_log = None
        self.pages["done"].set_result(ok, "".join(self._log_tail))
        self._enter(PAGE_ORDER.index("done"))


class InstallerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.tunaos.InstallerXfce")

    def do_activate(self):
        win = self.get_active_window() or InstallerWindow(self)
        readiness.arm(win, page_getter=lambda: PAGE_ORDER[win.index])
        win.present()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    InstallerApp().run()
