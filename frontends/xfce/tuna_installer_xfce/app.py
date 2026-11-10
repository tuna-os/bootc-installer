"""Application composition and install-process orchestration."""

import json
import os
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import core, gates, readiness
from . import locale as locale_checks
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


def spawn_fisherman(argv, stdin_data=b""):
    """Start the fisherman wrapper as the leader of its own process group,
    and hand it the recipe on stdin.

    The wrapper (the bash that core.fisherman_command() starts, behind
    flatpak-spawn in a Flatpak) is the only process in the install this
    user can signal; fisherman runs as root and cancels when its parent
    dies (tuna-os/fisherman#267). The contract every frontend follows is
    "kill your wrapper's process group", which needs the wrapper in a group
    of its own rather than the installer's. Closing the window mid-install
    asks first (ConfirmExitDialog) and then signals exactly that group.

    fisherman reads the recipe from stdin (`fisherman -`, #276) until EOF:
    `stdin_data` is written and the pipe closed here. A recipe is a few KiB,
    well under a pipe's buffer, so this does not wait for the polkit prompt.
    No file ever holds the passphrase or the user password.

    Returns (pid, stdout_fd, stderr_fd); the caller reaps the pid.
    """
    flags = GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.DO_NOT_REAP_CHILD
    pid, stdin_fd, out, err = GLib.spawn_async(
        argv, flags=flags, child_setup=_child_setup,
        standard_input=True, standard_output=True, standard_error=True)
    try:
        view = memoryview(stdin_data)
        while view:
            written = os.write(stdin_fd, view)
            view = view[written:]
    except OSError:
        # The wrapper is already gone; its exit status says why.
        pass
    finally:
        os.close(stdin_fd)
    return pid, out, err


def _child_setup(*_args):
    """Put the fisherman wrapper in its own process group.

    GLib calls child_setup with no arguments on some versions and with a
    user-data argument on others (newer gi passes one -- a bare os.setpgrp
    then fails with "takes no arguments" and the wrapper stays in the
    installer's group), so this swallows whatever it is given. The group is
    what terminate_process_group() signals; without it the wrapper would
    share the installer's group and the signal would hit this process too.
    """
    os.setpgrp()


def terminate_process_group(pid):
    """SIGTERM the install wrapper's process group (GNOME's
    BootcProgress.terminate, which signals the wrapper's group so fisherman
    notices its parent's death and runs its cleanup handler).

    Falls back to the wrapper alone when it has no group, and treats a dead
    or missing pid as a no-op: cancelling twice, or after a finished
    install, must not raise.
    """
    if not pid:
        return
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


class InstallerWindow(Gtk.ApplicationWindow):
    def __init__(self, app, autoinstall_recipe=None):
        super().__init__(application=app, title=f"{core.PRODUCT_NAME} Installer",
                         default_width=640, default_height=520)
        # The running install, if any: spawn_fisherman's wrapper pid (the
        # group leader terminate_process_group() signals). None otherwise.
        # _closing guards _on_exit against touching widgets after the user
        # confirmed quitting mid-install and the window is already gone.
        self._install_pid = None
        self._closing = False
        self._autoinstall_pending = None
        # True once the person confirmed the progress page's Cancel: the
        # wrapper's death by signal is then a cancel, not a failure.
        self._cancel_requested = False
        # The dry run's timer, so that Cancel works there too.
        self._dry_run_source = None
        # Closing the window mid-install asks first (GNOME's
        # __on_exit_clicked AlertDialog) and kills the install on confirm;
        # anywhere else the close goes through untouched.
        self.connect("delete-event", self._on_delete)
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
        # The wizard's own Back/Next bar. Hidden on the progress and done
        # pages: mid-install there is nowhere to go, and the done page has
        # its own Close and Restart now row (DonePage).
        self.nav = nav

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
        if autoinstall_recipe is not None:
            # Skip the wizard and start immediately (GNOME's
            # _start_autoinstall via GLib.idle_add).
            GLib.idle_add(self._start_autoinstall, autoinstall_recipe)

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
        # Back is hidden, not just greyed out, where it has no meaning: the
        # welcome page has nothing behind it, an install cannot be backed out
        # of, and the done page is the end. The other frontends hide it the
        # same way.
        terminal = name in ("progress", "done")
        self.back_btn.set_visible(self.index > 0 and not terminal)
        self.back_btn.set_sensitive(self.index > 0 and not terminal)
        self.next_btn.set_visible(not terminal)
        nav = getattr(self, "nav", None)
        if nav is not None:
            nav.set_visible(not terminal)
        self.next_btn.set_sensitive(page.can_continue())
        # Branding copy on the two buttons that carry a product's voice:
        # leaving the welcome page and starting the install.
        branded = {"welcome": "welcome_button", "confirm": "confirm_button"}.get(name)
        self.next_btn.set_label(core.BRANDING.text(branded) if branded else "Next")
        ctx = self.next_btn.get_style_context()
        if name == "confirm":
            ctx.add_class("destructive-action")
        else:
            ctx.remove_class("destructive-action")

    def selected_leaf(self):
        sel = self.pages["source"].selection() or {}
        return sel.get("leaf")

    def needs_user_creation(self):
        """Whether the installer creates the first account
        (shared/catalog/README.md, "The account"): the selected leaf's flag;
        for "install this system" on live media, the flag of the catalog
        leaf the probe's live image names. An image the catalog does not
        have needs an account."""
        source = self.pages["source"]
        sel = source.selection() or {}
        leaf = sel.get("leaf")
        if leaf is not None:
            return leaf.needs_user_creation
        if sel.get("live"):
            return source.catalog.needs_user_creation(source.live_image)
        return True

    def source_and_target(self):
        """(image, targetImgref) of the selected leaf on this machine, or
        ("", "") for "install this system"."""
        leaf = self.selected_leaf()
        if leaf is None:
            return "", ""
        source = self.pages["source"]
        return core.source_and_target(leaf, core.has_nvidia_gpu(),
                                      bool(source.live), core.offline_images())

    def build_recipe(self):
        """Read page widgets and adapt their values to the core recipe API."""
        setup = self.pages["setup"]
        leaf = self.selected_leaf()
        disk = self.pages["destination"].selected_disk()
        identity = self.pages["identity"]
        fields = dict(
            disk=disk["path"],
            filesystem=setup.default_filesystem(leaf.filesystem if leaf else ""),
            btrfs_subvolumes=setup.subvol_check.get_active(),
            encryption_type=setup.enc_type(),
            passphrase=setup.pass1.get_text(),
            hostname=identity.hostname.get_text(),
            username=identity.username.get_text(),
            fullname=identity.fullname.get_text(),
            password=identity.password.get_text(),
            groups=core.account_groups(),
        )
        if leaf is None:
            # "Install this system": an empty image, which fisherman accepts
            # on live media only.
            return core.build_recipe(needs_user=self.needs_user_creation(), **fields)
        source = self.pages["source"]
        return core.recipe_for_leaf(
            leaf, has_nvidia=core.has_nvidia_gpu(), live=bool(source.live),
            offline=core.offline_images(), **fields)

    def _install_running(self):
        """Whether fisherman is currently running under this window."""
        if not self._install_pid:
            return False
        try:
            os.kill(self._install_pid, 0)
        except OSError:
            return False
        return True

    def terminate_install(self):
        """Cancel the running install: SIGTERM the wrapper's process group
        (GNOME's BootcProgress.terminate). fisherman runs as root and cannot
        be signalled directly; it notices its parent's death and cleans up.
        A finished or absent install is a no-op."""
        terminate_process_group(self._install_pid)
        self._install_pid = None

    def request_cancel(self, confirm=None):
        """The progress page's Cancel: ask first, then stop the install.

        Returns whether the install was cancelled. `confirm` answers the
        question (a test passes one); the default is ConfirmCancelDialog.
        Nothing is asked, and nothing happens, when no install runs."""
        if not (self._install_running() or self._dry_run_source):
            return False
        if not (confirm or self._confirm_cancel)():
            return False
        self.cancel_install()
        return True

    def _confirm_cancel(self):
        dialog = gates.ConfirmCancelDialog(self)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def cancel_install(self):
        """Stop the install after a confirmed cancel: SIGTERM the wrapper's
        whole process group. fisherman runs as root and cannot be signalled;
        it sees its parent die, cleans up and exits 130. The wrapper's exit
        then reaches _on_exit, which shows the cancelled page."""
        self._cancel_requested = True
        self.pages["progress"].cancel_btn.set_sensitive(False)
        if self._dry_run_source:
            GLib.source_remove(self._dry_run_source)
            self._dry_run_source = None
            self._show_result(False, cancelled=True)
            return
        terminate_process_group(self._install_pid)

    def _show_result(self, ok, cancelled=False, message=None):
        """Fill the done page and show it."""
        log_tail = "".join(self._log_tail) if message is None else message
        self.pages["done"].set_result(
            ok, log_tail, self.pages["progress"].recovery_key(), cancelled=cancelled)
        self._enter(PAGE_ORDER.index("done"))

    def _on_delete(self, *_args):
        """Guard the window close: confirm and kill the install when one is
        running (GNOME's __on_exit_clicked/__on_exit_response), otherwise
        let the close through."""
        if not self._install_running():
            return False
        dialog = gates.ConfirmExitDialog(self)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self._closing = True
            self.terminate_install()
            self.destroy()
        return True

    def check_connectivity(self):
        """Marker the confirm page looks for: this window answers
        connectivity questions (describe_connectivity). Kept as a method so
        test doubles without it keep the old always-continue behavior."""
        return self.describe_connectivity()[0]

    def describe_connectivity(self):
        """(needs_network, offline): whether this install must download
        anything. Live media installs the running system, and an image
        already in the host's offline stores needs no download -- both are
        fisherman's facts (probe's live/offline), the same condition
        GNOME's conn_check.should_show inverts."""
        sel = self.pages["source"].selection() or {}
        # The image the install reads: the NVIDIA one on an NVIDIA machine.
        image = self.source_and_target()[0]
        offline = bool(sel.get("live")) or (bool(image)
                                            and image in core.offline_images())
        return (locale_checks.needs_network(offline), offline)

    @staticmethod
    def _load_autoinstall_recipe(path):
        """The --autoinstall recipe file, read here and handed to fisherman
        on stdin like any other recipe. None when it cannot be read or is
        not a JSON object (GNOME's _load_autoinstall_recipe)."""
        try:
            with open(path, encoding="utf-8") as recipe_file:
                recipe = json.load(recipe_file)
        except (OSError, ValueError) as exc:
            print(f"Failed to read install recipe {path}: {exc}",
                  file=sys.stderr)
            return None
        if not isinstance(recipe, dict):
            print(f"Install recipe {path} is not a JSON object.",
                  file=sys.stderr)
            return None
        return recipe

    def _start_autoinstall(self, path):
        """Go straight to the progress page and start fisherman with the
        pre-built recipe, bypassing the wizard (GNOME's _start_autoinstall).
        An unreadable recipe falls back to the wizard instead of installing
        nothing. A recipe that fisherman does not accept starts nothing
        either: the result page says why (core.recipe_problems)."""
        recipe = self._load_autoinstall_recipe(path)
        if recipe is None:
            return False
        problems = core.recipe_problems(recipe)
        if problems:
            print("Install recipe refused: " + " ".join(problems), file=sys.stderr)
            self._show_result(False, message="\n".join(problems) + "\n")
            return False
        self._autoinstall_pending = recipe
        self._enter(PAGE_ORDER.index("progress"))
        return False

    def start_install(self, progress_page, recipe=None):
        if self._install_running() or self._dry_run_source:
            # One install at a time: entering the page twice starts one.
            return
        self._cancel_requested = False
        if core.dry_run():
            self._start_dry_run(progress_page)
            return

        if self._autoinstall_pending is not None:
            recipe = self._autoinstall_pending
            self._autoinstall_pending = None
        if recipe is None:
            recipe = self.build_recipe()
        self._log_tail = []
        try:
            # In a Flatpak this stages the bundled fisherman and checks its
            # SHA256 on the host; nothing runs when that fails.
            argv = core.fisherman_argv()
        except core.StageError as exc:
            self._show_result(False, message=str(exc) + "\n")
            return
        self._install_log = core.open_install_log()
        self._install_log.write(
            f"=== install started: {core.shell_line(argv)} (recipe on stdin) ===\n")
        self._install_log.flush()
        pid, out, err = spawn_fisherman(argv, core.recipe_stdin(recipe))
        self._install_pid = pid
        for fd in (out, err):
            channel = GLib.IOChannel.unix_new(fd)
            channel.set_flags(GLib.IOFlags.NONBLOCK)
            GLib.io_add_watch(channel, GLib.IO_IN | GLib.IO_HUP,
                              self._on_output, progress_page)
        GLib.child_watch_add(pid, self._on_exit)

    def _start_dry_run(self, progress_page):
        """Play a fisherman transcript through the real progress page."""
        self._autoinstall_pending = None
        self._log_tail = []
        lines = list(core.DRY_RUN_TRANSCRIPT)

        def pump():
            if not lines:
                self._dry_run_source = None
                self._show_result(True)
                return False
            text = lines.pop(0)
            self._log_tail = (self._log_tail + [text])[-15:]
            progress_page.append_log(text)
            return True

        self._dry_run_source = GLib.timeout_add(400, pump)

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

    def _on_exit(self, pid, status, *_args):
        GLib.spawn_close_pid(pid)
        self._install_pid = None
        if self._closing:
            # The user confirmed quitting mid-install; the window is gone.
            return
        code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else None
        ok = code == 0
        # fisherman exits 130 when it is cancelled. After a cancel the
        # person confirmed, the wrapper dies by the signal this app sent;
        # that is a cancel too, not a failure (#299).
        cancelled = not ok and (code == EXIT_CANCELLED or self._cancel_requested)
        if self._install_log:
            outcome = "ok" if ok else (
                "cancelled" if cancelled else f"failed (status {status})")
            self._install_log.write(f"=== fisherman exited: {outcome} ===\n")
            self._install_log.close()
            self._install_log = None
        self._show_result(ok, cancelled=cancelled)


# fisherman's exit code for a cancelled install (shared/recipe/README.md).
EXIT_CANCELLED = 130

APP_ID = "org.tunaos.InstallerXfce"


class InstallerApp(Gtk.Application):
    def __init__(self, autoinstall_recipe=None):
        super().__init__(application_id=APP_ID)
        self._autoinstall_recipe = autoinstall_recipe

    def do_activate(self):
        if self._autoinstall_recipe is not None:
            # Skip the gates and the wizard: install straight from the file
            # (GNOME's do_activate autoinstall branch).
            win = (self.get_active_window()
                   or InstallerWindow(self,
                                      autoinstall_recipe=self._autoinstall_recipe))
            readiness.arm(win, APP_ID, page_getter=lambda: PAGE_ORDER[win.index])
            win.present()
            return
        # Below-minimum machines never see the wizard: a blocking gate
        # instead (GNOME's do_activate RAM/CPU/UEFI branches). The stamp
        # names the gate class, so the smoke test can require the wizard
        # rather than merely a window.
        gate = gates.required_gate()
        if gate is not None:
            win = self.get_active_window() or gates.GATE_BUILDERS[gate]()
            self.add_window(win)
            readiness.arm(win, APP_ID, page=gate)
            win.show_all()
            win.present()
            return
        win = self.get_active_window() or InstallerWindow(self)
        readiness.arm(win, APP_ID, page_getter=lambda: PAGE_ORDER[win.index])
        win.present()


def parse_argv(argv):
    """(autoinstall_path_or_None, rest): split --autoinstall/-a out.

    GNOME registers --autoinstall as a GApplication option; this frontend
    parses sys.argv before Gtk.Application takes it (GTK3 has no
    add_main_option), with the same long and short spellings.
    """
    autoinstall = None
    rest = []
    take_next = False
    for arg in argv:
        if take_next:
            autoinstall = arg
            take_next = False
        elif arg in ("--autoinstall", "-a"):
            take_next = True
        elif arg.startswith("--autoinstall="):
            autoinstall = arg.split("=", 1)[1]
        else:
            rest.append(arg)
    return autoinstall, rest


def main(argv=None):
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    prog = sys.argv[0] if argv is None else "tuna-installer-xfce"
    autoinstall, rest = parse_argv(sys.argv[1:] if argv is None else argv)
    # run() takes a full argv (program name first); the --autoinstall pair
    # stays out of it so GTK never sees an option it does not know.
    InstallerApp(autoinstall_recipe=autoinstall).run([prog] + rest)
