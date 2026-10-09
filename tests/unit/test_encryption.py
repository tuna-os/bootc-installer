"""Unit tests for defaults/encryption.py pure logic."""

import importlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class _StubWidget:
    def __init__(self, *args, **kwargs):
        pass

    def get_text(self):
        return ""

    def set_text(self, value):
        pass

    def get_active(self):
        return False

    def set_visible(self, value):
        pass

    def set_sensitive(self, value):
        pass

    def remove_css_class(self, css_class):
        pass

    def add_css_class(self, css_class):
        pass


class _Template:
    def __call__(self, *args, **kwargs):
        return lambda cls: cls

    def Child(self, *args, **kwargs):
        return None


def _build_gi_stubs():
    gi_mod = types.ModuleType("gi")
    repo_mod = types.ModuleType("gi.repository")

    gtk_mod = types.ModuleType("gi.repository.Gtk")
    gtk_mod.Template = _Template()
    gtk_mod.Box = _StubWidget

    adw_mod = types.ModuleType("gi.repository.Adw")
    for widget in [
        "Bin",
        "ActionRow",
        "Window",
        "EntryRow",
        "ComboRow",
        "SwitchRow",
        "PreferencesGroup",
        "PreferencesPage",
        "ExpanderRow",
    ]:
        setattr(adw_mod, widget, _StubWidget)

    gobject_mod = types.ModuleType("gi.repository.GObject")
    gobject_mod.Property = lambda *args, **kwargs: (lambda f: property(f))

    for name, mod in [
        ("Gtk", gtk_mod),
        ("Adw", adw_mod),
        ("GObject", gobject_mod),
        ("GLib", MagicMock()),
    ]:
        setattr(repo_mod, name, mod)
        sys.modules[f"gi.repository.{name}"] = mod

    gi_mod.repository = repo_mod
    gi_mod.require_version = lambda *args, **kwargs: None
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repo_mod


def _import_encryption_fresh():
    managed_modules = [
        "gi",
        "gi.repository",
        "gi.repository.Gtk",
        "gi.repository.Adw",
        "gi.repository.GObject",
        "gi.repository.GLib",
    ]
    originals = {name: sys.modules.get(name) for name in managed_modules}

    _build_gi_stubs()
    sys.modules.pop("bootc_installer.defaults.encryption", None)
    import bootc_installer.defaults as defaults_pkg

    defaults_pkg.__dict__.pop("encryption", None)

    try:
        mod = importlib.import_module("bootc_installer.defaults.encryption")
        mod._ = lambda text: text
        return mod
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class TestBootcDefaultEncryptionShouldShow(unittest.TestCase):
    def setUp(self):
        self.mod = _import_encryption_fresh()

    def test_should_show_always_returns_true(self):
        obj = self.mod.BootcDefaultEncryption.__new__(self.mod.BootcDefaultEncryption)

        for context in ({}, {"offline_install": True}, {"disk_count": 1}):
            with self.subTest(context=context):
                self.assertIs(obj.should_show(context), True)


class TestBootcDefaultEncryptionGetFinals(unittest.TestCase):
    def setUp(self):
        self.mod = _import_encryption_fresh()

    def _make_obj(self, *, use_encryption, use_tpm2, passphrase, has_tpm2=True):
        obj = self.mod.BootcDefaultEncryption.__new__(self.mod.BootcDefaultEncryption)
        obj.has_tpm2 = has_tpm2
        obj.use_encryption_switch = MagicMock()
        obj.use_encryption_switch.get_active.return_value = use_encryption
        obj.tpm2_switch = MagicMock()
        obj.tpm2_switch.get_active.return_value = use_tpm2
        obj.encryption_pass_entry = MagicMock()
        obj.encryption_pass_entry.get_text.return_value = passphrase
        return obj

    def test_get_finals_returns_disabled_payload_when_encryption_off(self):
        obj = self._make_obj(use_encryption=False, use_tpm2=True, passphrase="ignored")

        self.assertEqual(
            obj.get_finals(),
            {"encryption": {"use_encryption": False, "encryption_key": ""}},
        )

    def test_get_finals_uses_tpm2_luks_passphrase_when_tpm2_enabled(self):
        obj = self._make_obj(
            use_encryption=True,
            use_tpm2=True,
            passphrase="correct horse battery staple",
        )

        self.assertEqual(
            obj.get_finals(),
            {
                "encryption": {
                    "use_encryption": True,
                    "type": "tpm2-luks-passphrase",
                    "encryption_key": "correct horse battery staple",
                }
            },
        )

    def test_get_finals_uses_luks_passphrase_when_tpm2_disabled(self):
        obj = self._make_obj(
            use_encryption=True,
            use_tpm2=False,
            passphrase="hunter2",
        )

        self.assertEqual(
            obj.get_finals(),
            {
                "encryption": {
                    "use_encryption": True,
                    "type": "luks-passphrase",
                    "encryption_key": "hunter2",
                }
            },
        )


    def test_get_finals_never_writes_tpm2_without_a_tpm(self):
        # The switch claims on, the machine has no TPM 2.0: the recipe must
        # not ask fisherman to enrol a TPM that is not there.
        obj = self._make_obj(
            use_encryption=True,
            use_tpm2=True,
            passphrase="hunter2",
            has_tpm2=False,
        )

        self.assertEqual(obj.get_finals()["encryption"]["type"], "luks-passphrase")


class TestBootcDefaultEncryptionTpmRow(unittest.TestCase):
    """shared/tpm/README.md: TPM choices are offered only with a TPM 2.0.

    The row used to be visible and switchable everywhere, merely defaulting
    off without a TPM.
    """

    def setUp(self):
        self.mod = _import_encryption_fresh()

    def _init(self, has_tpm2):
        from unittest.mock import patch

        cls = self.mod.BootcDefaultEncryption
        obj = cls.__new__(cls)
        for child in (
            "btn_next",
            "page_header",
            "encryption_row",
            "use_encryption_switch",
            "tpm2_row",
            "tpm2_switch",
            "encryption_pass_entry",
            "encryption_pass_entry_confirm",
            "strength_label",
        ):
            setattr(obj, child, MagicMock())
        with patch(
            "bootc_installer.core.system.Systeminfo.has_tpm2",
            return_value=has_tpm2,
        ):
            cls.__init__(obj, MagicMock(), {}, "encryption", 0)
        return obj

    def test_row_hidden_and_off_without_a_tpm(self):
        obj = self._init(False)

        obj.tpm2_row.set_visible.assert_called_once_with(False)
        obj.tpm2_switch.set_active.assert_called_once_with(False)
        self.assertFalse(obj.has_tpm2)

    def test_row_shown_and_on_with_a_tpm(self):
        obj = self._init(True)

        obj.tpm2_row.set_visible.assert_called_once_with(True)
        obj.tpm2_switch.set_active.assert_called_once_with(True)
        self.assertTrue(obj.has_tpm2)

    def test_row_subtitles_are_the_shared_choice_descriptions(self):
        # The switch alone gives luks-passphrase, both give
        # tpm2-luks-passphrase: each row reads that type's copy key.
        obj = self._init(True)

        obj.encryption_row.set_subtitle.assert_called_once_with(
            "You'll type it at every boot.")
        obj.tpm2_row.set_subtitle.assert_called_once_with(
            "Automatic unlock, passphrase as fallback.")

    def test_blueprint_hides_the_row_by_default(self):
        # The template is the state before __init__ runs; it must not offer
        # TPM either. The row must have an id for encryption.py to reach it.
        blp = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "bootc_installer", "gtk", "default-encryption.blp",
        )
        with open(blp, encoding="utf-8") as fh:
            text = fh.read()
        start = text.index("Adw.ActionRow tpm2_row {")
        block = text[start:text.index("}", start)]
        self.assertIn("visible: false;", block)


class TestBootcDefaultEncryptionPasswordChanged(unittest.TestCase):
    def setUp(self):
        self.mod = _import_encryption_fresh()

    def _make_obj(self, password, confirm, *, use_encryption=True):
        obj = self.mod.BootcDefaultEncryption.__new__(self.mod.BootcDefaultEncryption)
        obj.encryption_pass_entry = MagicMock()
        obj.encryption_pass_entry.get_text.return_value = password
        obj.encryption_pass_entry_confirm = MagicMock()
        obj.encryption_pass_entry_confirm.get_text.return_value = confirm
        obj.strength_label = MagicMock()
        obj.use_encryption_switch = MagicMock()
        obj.use_encryption_switch.get_active.return_value = use_encryption
        obj.btn_next = MagicMock()
        obj.password_filled = False
        return obj

    def test_password_changed_hides_strength_label_for_empty_password(self):
        obj = self._make_obj("", "", use_encryption=True)

        obj._BootcDefaultEncryption__on_password_changed()

        self.assertFalse(obj.password_filled)
        obj.strength_label.set_visible.assert_called_once_with(False)
        obj.encryption_pass_entry_confirm.remove_css_class.assert_called_once_with("error")
        obj.btn_next.set_sensitive.assert_called_once_with(False)

    def test_password_changed_marks_short_simple_password_as_weak(self):
        obj = self._make_obj("abc123", "abc123")

        obj._BootcDefaultEncryption__on_password_changed()

        self.assertTrue(obj.password_filled)
        obj.strength_label.set_text.assert_called_once_with(
            "Weak — make it longer or more complex"
        )
        obj.strength_label.add_css_class.assert_called_once_with("error")
        obj.strength_label.set_visible.assert_called_once_with(True)
        obj.encryption_pass_entry_confirm.remove_css_class.assert_called_once_with("error")
        obj.btn_next.set_sensitive.assert_called_once_with(True)

    def test_password_changed_marks_medium_password_as_fair(self):
        obj = self._make_obj("Abcdefgh", "Abcdefgh")

        obj._BootcDefaultEncryption__on_password_changed()

        self.assertTrue(obj.password_filled)
        obj.strength_label.set_text.assert_called_once_with(
            "Fair — consider making it longer"
        )
        obj.strength_label.add_css_class.assert_called_once_with("warning")
        obj.strength_label.set_visible.assert_called_once_with(True)
        obj.btn_next.set_sensitive.assert_called_once_with(True)

    def test_password_changed_marks_long_complex_password_as_strong(self):
        obj = self._make_obj("Abcd1234!xyz", "Abcd1234!xyz")

        obj._BootcDefaultEncryption__on_password_changed()

        self.assertTrue(obj.password_filled)
        obj.strength_label.set_text.assert_called_once_with("Strong passphrase")
        obj.strength_label.add_css_class.assert_called_once_with("success")
        obj.strength_label.set_visible.assert_called_once_with(True)
        obj.btn_next.set_sensitive.assert_called_once_with(True)

    def test_password_changed_marks_nonmatching_confirmation_invalid(self):
        obj = self._make_obj("hunter2", "not-hunter2")

        obj._BootcDefaultEncryption__on_password_changed()

        self.assertFalse(obj.password_filled)
        obj.encryption_pass_entry_confirm.add_css_class.assert_called_once_with("error")
        obj.btn_next.set_sensitive.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()
