import logging
import os
import subprocess
import threading
import time
from gettext import gettext as _

from bootc_shared import completion

from gi.repository import Adw, Gio, GLib, Gtk


from bootc_installer.widgets.page_header import BootcPageHeader  # noqa: F401
from bootc_installer.windows.dialog_output import BootcDialogOutput

logger = logging.getLogger("Installer::Done")
log = logger


def apply_icon(page_header, icon_spec):
    """Apply the same resource, host file or theme spec as catalog rows."""
    try:
        from bootc_installer.utils.icons import resolve_icon
        resolved = resolve_icon(icon_spec)
        if resolved is None:
            return
        kind, value = resolved
        if kind == "resource":
            page_header.set_from_resource(value)
        elif kind == "file":
            page_header.set_from_file(value)
        else:
            page_header.icon_name = value
    except Exception as e:
        log.warning("Could not apply icon %r: %s", icon_spec, e)


def warmup_registry(image_ref: str):
    """Fire a skopeo inspect to warm DNS, TLS, and CDN routing for the registry.

    Called in a daemon thread 30 seconds after install success. Does not write
    to the target disk (which is finalized/frozen after install).
    """
    try:
        result = subprocess.run(
            ["skopeo", "inspect", f"docker://{image_ref}"],
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0:
            log.info("Registry warmup succeeded for %s", image_ref)
        else:
            log.debug("Registry warmup exited %d for %s: %s",
                      result.returncode, image_ref,
                      result.stderr.decode(errors="replace").strip()[:200])
    except FileNotFoundError:
        log.debug("skopeo not available — registry warmup skipped")
    except subprocess.TimeoutExpired:
        log.debug("Registry warmup timed out for %s", image_ref)
    except Exception as e:
        log.debug("Registry warmup failed for %s: %s", image_ref, e)


def do_reboot(in_flatpak):
    """Attempt to reboot. Returns True if a reboot command succeeded."""
    # Preferred: logind D-Bus — works correctly from inside the Flatpak
    # sandbox and handles polkit transparently.
    try:
        conn = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        conn.call_sync(
            "org.freedesktop.login1",
            "/org/freedesktop/login1",
            "org.freedesktop.login1.Manager",
            "Reboot",
            GLib.Variant("(b)", (False,)),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        return True
    except Exception as e:
        log.warning("logind D-Bus reboot failed: %s", e)

    # Fallback: spawn systemctl / reboot on the host.
    cmds = [["systemctl", "reboot"], ["reboot"]]
    for cmd in cmds:
        argv = (["flatpak-spawn", "--host"] + cmd) if in_flatpak else cmd
        try:
            result = subprocess.run(argv, capture_output=True)
            if result.returncode == 0:
                return True
            log.warning("%s exited %d: %s", argv, result.returncode, result.stderr.decode())
        except Exception as e:
            log.warning("%s failed: %s", argv, e)

    return False


# fisherman's exit code after a cancel (shared/recipe/README.md).
EXIT_CANCELLED = 130


def exit_code_hint(exit_code) -> str:
    """The line for an exit code that says why by itself, or "".

    The wrapper is `pkexec fisherman -` (or sudo). pkexec exits 126 when
    the user closes the password prompt and 127 when the authorization
    fails; bash also uses 126 and 127 for a helper it cannot run or cannot
    find. In each case fisherman did not start, so the log has no reason.
    """
    if exit_code == 126:
        return _("The administrator password prompt was closed, or the installer "
                 "helper cannot run. Nothing was changed on the disk. Try again.")
    if exit_code == 127:
        return _("The installer did not get administrator rights, or its helper "
                 "program is missing. Nothing was changed on the disk.")
    if exit_code == EXIT_CANCELLED:
        return _("The installation was stopped before it finished. "
                 "The disk can hold a partial system that does not start.")
    return ""


def error_event_hint(error, text=None) -> str:
    """The line the failure page shows for fisherman's `error` event.

    `error` is {"message", "code", "field"} (the progress parser's form).
    A `code` is one of `fisherman validate`'s, so the copy line for it
    (`validate_<code>`, read through `text(key)`) is shown when this build
    has one. Otherwise the line is fisherman's own message. "" when the
    event has neither, and the caller then reads the log.
    """
    if not isinstance(error, dict):
        return ""
    code = error.get("code") or ""
    if code and text is not None:
        line = text("validate_" + code)
        if line:
            return line
    message = " ".join(str(error.get("message") or "").split())
    if not message:
        return ""
    if len(message) > 300:
        message = message[:299] + "…"
    return _("Error: {}").format(message)


def _set_picture(picture, spec: str) -> None:
    """A GResource path (/org/...) or a host file path onto a Gtk.Picture."""
    if spec.startswith("/org/"):
        picture.set_resource(spec)
    else:
        picture.set_filename(spec)


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/done.ui")
class BootcDone(Adw.Bin):
    __gtype_name__ = "BootcDone"

    page_header = Gtk.Template.Child()
    btn_reboot = Gtk.Template.Child()
    btn_close = Gtk.Template.Child()
    btn_log = Gtk.Template.Child()
    btn_retry = Gtk.Template.Child()
    store_group = Gtk.Template.Child()
    store_qr = Gtk.Template.Child()
    lbl_store = Gtk.Template.Child()
    group_verification = Gtk.Template.Child()
    lbl_verification = Gtk.Template.Child()

    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__log = None
        self.delta = False

        self.btn_reboot.connect("clicked", self.__on_reboot_clicked)
        self.btn_close.connect("clicked", self.__on_close_clicked)
        self.btn_log.connect("clicked", self.__on_log_clicked)
        self.btn_retry.connect("clicked", self.__on_retry_clicked)
        self.__wrap_store_qr()

    def __wrap_store_qr(self):
        parent = self.store_qr.get_parent()
        if parent is None:
            return

        try:
            parent.remove(self.store_qr)
        except Exception:
            return

        parent.prepend(self.store_qr)

    def set_result(self, result, terminal, boot_id="", elapsed_secs=0, image_ref=None,
                   exit_code=None, cancelled=False, message=None, error=None,
                   receipt=None):
        """Show the result of an install.

        `exit_code` is the wrapper's; 126, 127 and 130 have lines of their
        own. `cancelled` (the user stopped it, or fisherman exited 130)
        shows the cancelled page, not the failure page. `message` is a
        reason the caller already has (an unreadable --autoinstall recipe).
        `boot_id` is not used: fisherman sets BootNext itself (#318).
        `error` is fisherman's last `error` event: its message is the
        reason for a failure, and the log is read only when there is none.
        `receipt` is what the parser kept of fisherman's `receipt` event
        (bootc_shared.progress.receipt_of), None when none came.
        """
        self.__terminal = terminal
        from bootc_installer.utils import copy as copy_text

        cancelled = bool(cancelled) or exit_code == EXIT_CANCELLED

        if result:
            self.page_header.icon_name = "object-select-symbolic"
            pretty_name = getattr(self.__window, "pretty_name", None) \
                or copy_text.product_name(self.__window)
            self.page_header.title = copy_text.text(self.__window, "done_title", name=pretty_name)
            subtitle = copy_text.text(self.__window, "done_subtitle", name=pretty_name)
            if elapsed_secs > 0:
                minutes, secs = divmod(elapsed_secs, 60)
                time_str = f"{minutes}:{secs:02d}"
                subtitle = (_("Installed in %s. ") % time_str) + subtitle
            self.page_header.subtitle = subtitle
            # Installed, restart required: never "verified". Only the new
            # system can check its own start (shared/completion/README.md).
            # The receipt line says what this install set up for that check.
            verification = "\n\n".join(completion.receipt_text(
                receipt, lambda key: copy_text.text(self.__window, key)))
            self.lbl_verification.set_label(verification)
            self.group_verification.set_visible(bool(verification))
            self.btn_reboot.set_label(copy_text.text(self.__window, "done_restart") or _("Restart now"))
            configured_logo = self.__window.recipe.get("distro_logo")
            if configured_logo == "org.bootcinstaller.Installer":
                configured_logo = None  # keep the neutral success checkmark
            icon_spec = getattr(self.__window, "selected_icon", None) or configured_logo
            if icon_spec:
                apply_icon(self.page_header, icon_spec)
            self.btn_reboot.set_visible(True)
            self.btn_close.set_visible(False)
            self.btn_retry.set_visible(False)
            self.btn_log.remove_css_class("suggested-action")
            # Show store widget for US users
            self.store_group.set_visible(False)
            self.__maybe_show_store()
            # Warm the registry connection in the background after 30 seconds.
            # The target disk is finalized (ro + frozen), so we cannot write to it.
            # This fires a skopeo inspect to warm DNS, TLS, and CDN routing so
            # the first `bootc upgrade` after reboot finds a hot connection.
            if image_ref:
                GLib.timeout_add_seconds(30, self.__schedule_registry_warmup, image_ref)
        elif cancelled:
            # Not a failure: the user asked for it (#299).
            self.page_header.icon_name = "process-stop-symbolic"
            self.page_header.title = (copy_text.text(self.__window, "done_cancelled_title")
                                      or _("Installation cancelled"))
            self.page_header.subtitle = exit_code_hint(EXIT_CANCELLED)
            self.group_verification.set_visible(False)
            self.store_group.set_visible(False)
            self.btn_reboot.set_visible(False)
            self.btn_close.set_visible(True)
            self.btn_retry.set_visible(True)
            self.btn_log.remove_css_class("suggested-action")
        else:
            self.page_header.icon_name = "dialog-error-symbolic"
            self.page_header.title = (copy_text.text(self.__window, "done_failed_title")
                                      or _("Installation failed"))
            # A reason the caller has, then an exit code that says why by
            # itself, then fisherman's own `error` event (#64), then the
            # last fatal line of the log.
            hint = (message or exit_code_hint(exit_code)
                    or error_event_hint(
                        error, lambda key: copy_text.text(self.__window, key))
                    or self.__extract_failure_hint())
            self.page_header.subtitle = hint
            self.group_verification.set_visible(False)
            self.store_group.set_visible(False)
            self.btn_reboot.set_visible(False)
            self.btn_close.set_visible(True)
            self.btn_retry.set_visible(True)
            # Show the log button prominently on failure
            self.btn_log.add_css_class("suggested-action")

    def __schedule_registry_warmup(self, image_ref: str) -> bool:
        """Fire off a background thread to warm the registry connection.
        Runs 30 seconds after install success. Does not write to the target disk.
        """
        log.info("Scheduling registry warmup for %s", image_ref)
        t = threading.Thread(
            target=warmup_registry,
            args=(image_ref,),
            daemon=True,
        )
        t.start()
        return False  # don't repeat the GLib timer

    def __registry_warmup_worker(self, image_ref: str):
        """Alias kept for back-compat — delegates to module-level warmup_registry."""
        warmup_registry(image_ref)

    def __extract_failure_hint(self) -> str:
        """Read the fisherman log to determine what failed and suggest a fix."""
        from bootc_installer.views.progress import _FISHERMAN_LOG_PATH
        try:
            with open(_FISHERMAN_LOG_PATH) as f:
                lines = f.readlines()
        except OSError:
            return _("Check the log for details. Click 'Show Log' below.")

        # Find the last "fatal:" line from fisherman
        fatal_msg = ""
        for line in lines:
            if "fatal:" in line.lower():
                fatal_msg = line.strip()

        if not fatal_msg:
            return _("The installer exited unexpectedly. Check the log for details.")

        # Provide actionable hints based on common failure patterns
        lower = fatal_msg.lower()
        if "not found in path" in lower or "missing required host tool" in lower:
            return _("A required system tool is missing. Ensure you are running from the official live media.")
        if "network" in lower or "pull" in lower or "timeout" in lower or "registry" in lower:
            return _("Network error during image download. Check your internet connection and try again.")
        if "no space" in lower or "enospc" in lower:
            return _("Not enough disk space. Select a larger disk or free up space.")
        if "permission" in lower or "denied" in lower:
            return _("Permission denied. The installer needs administrator access to proceed.")
        if "luks" in lower or "cryptsetup" in lower:
            return _("Disk encryption setup failed. Try disabling encryption or check your passphrase.")
        if "partition" in lower or "sfdisk" in lower:
            return _("Disk partitioning failed. The disk may be in use or damaged.")
        if "mount" in lower:
            return _("Filesystem mount failed. The disk may be in use by another process.")

        # Generic fallback with the actual error
        short_msg = fatal_msg.split("fatal:")[-1].strip()[:120]
        return _("Error: {}").format(short_msg)

    def __on_reboot_clicked(self, button):
        in_flatpak = os.path.exists("/.flatpak-info")

        # No BootNext here. fisherman sets it while it is root, when the
        # host booted from live media (tuna-os/fisherman#435); its log line
        # says what it did. This process cannot write an EFI variable (#318).
        if not do_reboot(in_flatpak):
            self.__show_reboot_error()

    def __show_reboot_error(self):
        dialog = Adw.AlertDialog.new(
            _("Could not reboot"),
            _("Please reboot manually by running: systemctl reboot"),
        )
        dialog.add_response("ok", _("OK"))
        dialog.present(self)

    def __on_close_clicked(self, button):
        self.__window.close()

    def __on_retry_clicked(self, button):
        """Run the install again. The window goes to the progress page
        first and refuses while an install is running (#307)."""
        self.__window.retry_installation()

    def __on_log_clicked(self, button):
        dialog = BootcDialogOutput(self.__window)
        dialog.present()

    def __maybe_show_store(self):
        """Show the merch store QR code for US-locale users only.

        Requires ``store_url`` in the recipe. The QR image is loaded from
        ``store_qr_resource`` (a GResource path) if provided, otherwise falls
        back to the built-in ``assets/store-qr.svg``.  If ``store_url`` is
        absent the widget stays hidden regardless of locale.
        """
        store_url = self.__window.recipe.get("store_url", "")
        if not store_url:
            return
        if not self.__is_us_locale():
            return
        qr_resource = self.__window.recipe.get("store_qr_resource", "")
        if not qr_resource:
            return
        try:
            from bootc_installer.utils import copy as copy_text
            _set_picture(self.store_qr, qr_resource)
            self.lbl_store.set_label(copy_text.text(self.__window, "store_label") or store_url)
            self.store_group.set_visible(True)
        except Exception as e:
            log.debug("Could not load store QR: %s", e)

    @staticmethod
    def __is_us_locale() -> bool:
        """Detect US locale via language or timezone."""
        # Check LANG / LC_ALL for US English
        lang = os.environ.get("LANG", "") + os.environ.get("LC_ALL", "")
        if "en_US" in lang:
            return True
        # Check timezone — US zones
        try:
            tz = time.tzname[0] if time.tzname else ""
            us_zones = {"EST", "EDT", "CST", "CDT", "MST", "MDT", "PST", "PDT", "AKST", "AKDT", "HST"}
            if tz in us_zones:
                return True
        except Exception as e:
            log.debug("Could not read timezone name: %s", e)
        # Check /etc/timezone or timedatectl output
        try:
            with open("/etc/timezone") as f:
                tz_file = f.read().strip()
            if tz_file.startswith("America/") or tz_file.startswith("US/"):
                return True
        except OSError:
            pass
        return False
