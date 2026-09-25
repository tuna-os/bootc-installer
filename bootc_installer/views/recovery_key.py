import logging
from gettext import gettext as _

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from bootc_installer.utils import copy as copy_text

logger = logging.getLogger("Installer::RecoveryKey")

_PLACEHOLDER_KEY = _("Recovery key will be displayed here once the installer reports it.")


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/recovery-key.ui")
class BootcRecoveryKey(Adw.Bin):
    __gtype_name__ = "BootcRecoveryKey"
    __gsignals__ = {
        "recovery-key-acknowledged": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    title_label = Gtk.Template.Child()
    body_label = Gtk.Template.Child()
    key_label = Gtk.Template.Child()
    copy_button = Gtk.Template.Child()
    ack_check = Gtk.Template.Child()
    btn_continue = Gtk.Template.Child()

    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.delta = False
        self.btn_continue.set_sensitive(False)
        self.copy_button.connect("clicked", self.__on_copy)
        self.ack_check.connect("toggled", self.__on_ack_toggled)
        self.btn_continue.connect("clicked", self.__on_continue)
        self.set_recovery_key("")

    def __apply_copy(self):
        """Every string on the page comes from the branding copy contract.

        Applied on each set_recovery_key() rather than once in __init__: the
        branding lands on window.recipe after the views are built. An empty
        title or body hides that line, as elsewhere; the three controls fall
        back to their neutral wording instead, because an unlabelled
        checkbox or button cannot be used.
        """
        w = self.__window
        title = copy_text.text(w, "recovery_key_title")
        self.title_label.set_label(title)
        self.title_label.set_visible(bool(title))
        body = copy_text.text(w, "recovery_key_body")
        self.body_label.set_label(body)
        self.body_label.set_visible(bool(body))
        self.copy_button.set_tooltip_text(
            copy_text.text(w, "recovery_key_copy") or _("Copy to clipboard"))
        self.ack_check.set_label(
            copy_text.text(w, "recovery_key_ack") or _("I have saved my recovery key"))
        self.btn_continue.set_label(
            copy_text.text(w, "recovery_key_button") or _("Continue"))

    def set_recovery_key(self, key: str):
        self.__apply_copy()
        key = (key or "").strip()
        has_key = bool(key)
        self.key_label.set_label(key or _PLACEHOLDER_KEY)
        self.copy_button.set_sensitive(has_key)
        self.copy_button.set_icon_name("edit-copy-symbolic")
        self.ack_check.set_active(False)
        self.btn_continue.set_sensitive(False)

    def __on_copy(self, *args):
        if not self.copy_button.get_sensitive():
            return
        display = Gdk.Display.get_default()
        if display is None:
            return

        clipboard = display.get_clipboard()
        clipboard.set(self.key_label.get_label())
        self.copy_button.set_icon_name("emblem-ok-symbolic")

        def _reset_icon():
            self.copy_button.set_icon_name("edit-copy-symbolic")
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(1500, _reset_icon)

    def __on_ack_toggled(self, check):
        self.btn_continue.set_sensitive(check.get_active())

    def __on_continue(self, *args):
        self.emit("recovery-key-acknowledged")
