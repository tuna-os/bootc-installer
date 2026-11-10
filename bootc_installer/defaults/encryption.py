# encryption.py
#
# Copyright 2024 mirkobrombin
#
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

import logging
from gettext import gettext as _

from gi.repository import Adw, Gtk

logger = logging.getLogger(__name__)

from bootc_shared import validate as fisherman_validate
from bootc_installer.utils import copy as copy_text

# The encryption types in display order, with needs_passphrase and
# needs_tpm2: fisherman's data/encryption-choices.json, read through the
# shared reader (shared/recipe/encryption-choices.json, which the build
# installs with the bootc_shared package). [] when the file is missing, so
# the page degrades to the legacy two-switch page instead of crashing the
# import.
try:
    ENCRYPTION_CHOICES = fisherman_validate.load_choices()
except OSError:
    ENCRYPTION_CHOICES = []


def offered_encryption_types(has_tpm2):
    """The ids this machine may offer, in display order.

    Niri's offeredEncryptionTypes (frontends/niri/ui/installer.qml): every
    choice whose needs_tpm2 flag is set is hidden without a usable TPM 2.0.
    Flag-driven, never name-driven — the file owns the flags.
    """
    return [c["type"] for c in ENCRYPTION_CHOICES
            if has_tpm2 or not c.get("needs_tpm2")]


def needs_passphrase_for(enc_type):
    """Whether `enc_type` takes a passphrase (needs_passphrase in the file).

    True when the choices are unknown: a passphrase demanded in error only
    holds Next, while one skipped in error writes an unusable recipe.
    """
    if not ENCRYPTION_CHOICES:
        return True
    return fisherman_validate.needs_passphrase(enc_type, ENCRYPTION_CHOICES)

@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/default-encryption.ui")
class BootcDefaultEncryption(Adw.Bin):
    __gtype_name__ = "BootcDefaultEncryption"

    btn_next = Gtk.Template.Child()
    page_header = Gtk.Template.Child()

    encryption_row = Gtk.Template.Child()
    use_encryption_switch = Gtk.Template.Child()
    tpm2_row = Gtk.Template.Child()
    tpm2_switch = Gtk.Template.Child()

    encryption_pass_entry = Gtk.Template.Child()
    encryption_pass_entry_confirm = Gtk.Template.Child()
    strength_label = Gtk.Template.Child()

    password_filled = False
    # Whether this machine has a TPM 2.0 (shared/tpm/README.md). Set once in
    # __init__; False until then so a half-built page never offers TPM.
    has_tpm2 = False

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.delta = False

        # Selector state first: set_active() below can emit state-set
        # synchronously, so the switch handlers must already see these.
        # _syncing_selector starts True to hold the mirror still while the
        # defaults are applied; __init__ drops it before building.
        self.selected_type = None
        self.offered_types = []
        self.encryption_type_row = None
        self._syncing_selector = True

        # This page is a switch plus a TPM switch, not the four-way choice
        # the other frontends show, so only the two choice descriptions it
        # can produce apply: the switch alone gives luks-passphrase, both
        # give tpm2-luks-passphrase. The words are the shared copy keys.
        self.encryption_row.set_subtitle(
            copy_text.encryption_text(window, "luks-passphrase", "_description"))
        self.tpm2_row.set_subtitle(
            copy_text.encryption_text(window, "tpm2-luks-passphrase", "_description"))

        self.btn_next.connect("clicked", self.__window.next)
        self.use_encryption_switch.connect(
            "state-set", self.__on_encryption_switch_set)
        self.tpm2_switch.connect("state-set", self.__on_tpm2_switch_set)
        self.encryption_pass_entry.connect(
            "changed", self.__on_password_changed)
        self.encryption_pass_entry_confirm.connect(
            "changed", self.__on_password_changed
        )

        # Default: encryption ON, TPM2 ON if hardware present.
        #
        # Without a TPM 2.0 the TPM row is hidden, not merely switched off.
        # It used to stay visible and switchable on every machine, so a
        # person without a TPM (or with a TPM 1.2) could turn it on and get a
        # tpm2-luks-passphrase recipe that fails at enrolment, after the disk
        # has been partitioned. The other four frontends drop the TPM choices
        # on such a machine; this follows them. BOOTC_INSTALLER_FAKE_TPM
        # forces the row visible for screenshots.
        from bootc_installer.core.system import Systeminfo
        self.has_tpm2 = Systeminfo.has_tpm2()
        self.tpm2_row.set_visible(self.has_tpm2)
        self.use_encryption_switch.set_active(True)
        self.tpm2_switch.set_active(self.has_tpm2)

        # The four-way type selector, Niri-style: every id the choices file
        # lists, minus the needs_tpm2 ones on a machine without a usable
        # TPM. The two switches above stay as the legacy control surface
        # (and the only one the unit harness drives); the selector and the
        # switches mirror each other, and get_finals() prefers the
        # selector's explicit type once it exists.
        #
        # Built only when the toolkit has a combo row: the unit harness
        # imports this module with a stub Adw that has none, and the page
        # must stay constructible there. No try/except — an explicit
        # capability check, so a real API mistake still fails loudly.
        #
        self.offered_types = offered_encryption_types(self.has_tpm2)
        self._syncing_selector = False
        if (self.offered_types
                and getattr(Adw, "ComboRow", None) is not None
                and getattr(Gtk, "StringList", None) is not None):
            self.__build_type_selector(window)

        self.__update_btn_next()

    def should_show(self, context: dict) -> bool:
        return True

    def test_auto_advance(self):
        # Ensure encryption is off — TPM2 won't work on virtual/loop disks
        self.use_encryption_switch.set_active(False)
        self.tpm2_switch.set_active(False)
        self.btn_next.emit("clicked")

    def get_finals(self):
        # The selector's explicit type wins once the user could see it; the
        # ids come from the choices file, never from a literal here, so the
        # page can produce tpm2-luks (TPM without passphrase) — the one type
        # the two switches alone cannot express.
        selected = getattr(self, "selected_type", None)
        offered = getattr(self, "offered_types", [])
        if selected in offered:
            if selected == "none" or not selected:
                return {"encryption": {"use_encryption": False, "encryption_key": ""}}
            payload = {"use_encryption": True, "type": selected}
            if needs_passphrase_for(selected):
                payload["encryption_key"] = self.encryption_pass_entry.get_text()
            else:
                payload["encryption_key"] = ""
            return {"encryption": payload}
        use_enc = self.use_encryption_switch.get_active()
        if not use_enc:
            return {"encryption": {"use_encryption": False, "encryption_key": ""}}
        passphrase = self.encryption_pass_entry.get_text()
        use_tpm2 = self.has_tpm2 and self.tpm2_switch.get_active()
        enc_type = "tpm2-luks-passphrase" if use_tpm2 else "luks-passphrase"
        return {
            "encryption": {
                "use_encryption": True,
                "type": enc_type,
                "encryption_key": passphrase,
            }
        }

    def __choice_label(self, window, enc_type):
        # The shared copy key for the type (encryption_<type>_label), so the
        # selector uses the same words as the confirm page and the other
        # frontends. Labels only: the row subtitles stay the two legacy
        # descriptions the page has always shown.
        return copy_text.encryption_text(window, enc_type, "_label") or enc_type

    def __build_type_selector(self, window):
        labels = [self.__choice_label(window, enc_type)
                  for enc_type in self.offered_types]
        self.encryption_type_row = Adw.ComboRow(
            title=_("Encryption type"),
            model=Gtk.StringList.new(labels),
        )
        self.encryption_type_row.connect(
            "notify::selected", self.__on_type_selected)
        group = Adw.PreferencesGroup(
            title=_("Encryption type"),
            description=_("Choose how to protect the data on your disk."),
        )
        group.add(self.encryption_type_row)
        # The new group goes last on the page, after the switches it
        # mirrors. Walk up to the PreferencesPage: the groups sit inside
        # the page's own container, so the direct parents are internal
        # widgets, never the page itself.
        page = self.encryption_row.get_parent()
        while page is not None and not isinstance(page, Adw.PreferencesPage):
            page = page.get_parent()
        if page is None:
            logger.warning("encryption type selector has no page; skipping it")
            self.encryption_type_row = None
            return
        page.add(group)
        self._sync_selector_to_switches()

    def __on_type_selected(self, combo, _pspec):
        if self._syncing_selector:
            return
        index = combo.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= len(self.offered_types):
            return
        self.selected_type = self.offered_types[index]
        self._syncing_selector = True
        try:
            use_enc = self.selected_type != "none" and bool(self.selected_type)
            use_tpm2 = (self.has_tpm2 and self.selected_type in
                        [c["type"] for c in ENCRYPTION_CHOICES if c.get("needs_tpm2")])
            self.use_encryption_switch.set_active(use_enc)
            self.tpm2_switch.set_active(use_tpm2)
        finally:
            self._syncing_selector = False
        self.__update_btn_next()

    def _sync_selector_to_switches(self):
        """Mirror the switches into the selector after either switch moves."""
        row = getattr(self, "encryption_type_row", None)
        if row is None or self._syncing_selector:
            return
        use_enc = self.use_encryption_switch.get_active()
        use_tpm2 = self.has_tpm2 and self.tpm2_switch.get_active()
        if not use_enc:
            want = "none"
        else:
            want = [c["type"] for c in ENCRYPTION_CHOICES
                    if c.get("needs_tpm2") == use_tpm2
                    and c.get("needs_passphrase")][:1]
            want = want[0] if want else "none"
        if want not in self.offered_types:
            want = self.offered_types[0]
        self._syncing_selector = True
        try:
            row.set_selected(self.offered_types.index(want))
            self.selected_type = want
        finally:
            self._syncing_selector = False

    def __on_encryption_switch_set(self, state, user_data):
        if self.use_encryption_switch.get_active():
            self.page_header.icon_name = "changes-prevent-symbolic"
        else:
            self.page_header.icon_name = "changes-allow-symbolic"
            self.tpm2_switch.set_active(False)

        self._sync_selector_to_switches()
        self.__update_btn_next()

    def __on_tpm2_switch_set(self, state, user_data):
        self._sync_selector_to_switches()
        self.__update_btn_next()

    def __on_password_changed(self, *args):
        password = self.encryption_pass_entry.get_text()
        confirm = self.encryption_pass_entry_confirm.get_text()

        # Passphrase match validation
        if password and password == confirm:
            self.password_filled = True
            self.encryption_pass_entry_confirm.remove_css_class("error")
        else:
            self.password_filled = False
            if confirm:
                self.encryption_pass_entry_confirm.add_css_class("error")
            else:
                self.encryption_pass_entry_confirm.remove_css_class("error")

        # Real-time strength feedback
        if password:
            has_upper = any(c.isupper() for c in password)
            has_lower = any(c.islower() for c in password)
            has_digit = any(c.isdigit() for c in password)
            has_symbol = any(not c.isalnum() for c in password)
            variety = sum([has_upper, has_lower, has_digit, has_symbol])
            length = len(password)

            if length < 8 or variety < 2:
                self.strength_label.set_text(_("Weak \u2014 make it longer or more complex"))
                self.strength_label.remove_css_class("success")
                self.strength_label.remove_css_class("warning")
                self.strength_label.add_css_class("error")
            elif length < 12 or variety < 3:
                self.strength_label.set_text(_("Fair \u2014 consider making it longer"))
                self.strength_label.remove_css_class("error")
                self.strength_label.remove_css_class("success")
                self.strength_label.add_css_class("warning")
            else:
                self.strength_label.set_text(_("Strong passphrase"))
                self.strength_label.remove_css_class("error")
                self.strength_label.remove_css_class("warning")
                self.strength_label.add_css_class("success")
            self.strength_label.set_visible(True)
        else:
            self.strength_label.set_visible(False)

        self.__update_btn_next()

    def __update_btn_next(self):
        use_enc = self.use_encryption_switch.get_active()
        # A selected type that takes no passphrase (the TPM-only choice)
        # needs no typed-twice password before Next.
        selected = getattr(self, "selected_type", None)
        offered = getattr(self, "offered_types", [])
        if selected in offered and not needs_passphrase_for(selected):
            rule = True
        else:
            rule = not use_enc or self.password_filled
        self.btn_next.set_sensitive(rule)
