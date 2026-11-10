import os
from gettext import gettext as _

from gi.repository import Adw, Gtk

from bootc_installer.utils.fisherman_runner import LOG_PATH as _LOG_PATH
from bootc_installer.utils.fisherman_session import read_log_redacted


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/dialog-output.ui")
class BootcDialogOutput(Adw.Window):
    __gtype_name__ = "BootcDialogOutput"

    log_view = Gtk.Template.Child()
    btn_copy = Gtk.Template.Child()

    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)
        self.set_transient_for(window)

        # Without the TPM recovery key: this text is what a user copies
        # into a bug report (#316).
        content = read_log_redacted(_LOG_PATH) if os.path.exists(_LOG_PATH) else None
        if content is None:
            content = _("Log not available.")

        buf = self.log_view.get_buffer()
        buf.set_text(content)
        # Scroll to end so the last (most relevant) output is visible
        self.log_view.scroll_mark_onscreen(buf.get_insert())

        self.btn_copy.connect("clicked", self.__on_copy)

    def __on_copy(self, button):
        buf = self.log_view.get_buffer()
        start, end = buf.get_bounds()
        self.get_clipboard().set(buf.get_text(start, end, False))
        self.btn_copy.set_icon_name("emblem-ok-symbolic")
