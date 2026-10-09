"""
Unit tests for confirm.py and related helpers — pure Python, no GTK required.
Covers encryption labels, quote selection logic, and keyboard formatting.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bootc_installer.utils import copy as copy_text  # noqa: E402


class TestEncryptionLabels(unittest.TestCase):
    """The confirm row names the encryption type with the branding copy every
    frontend uses (encryption_<type>_label), not a GNOME-only table. It used
    to say "None" and "Encrypted with passphrase" where the other four said
    "No encryption" and "Passphrase"."""

    TYPES = ("none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase")

    def _window(self, branding):
        class W:
            recipe = {"branding": branding}
        return W()

    def test_every_type_has_a_label(self):
        w = self._window({})
        for enc_type in self.TYPES:
            self.assertTrue(copy_text.encryption_text(w, enc_type, "_label").strip(), enc_type)

    def test_the_neutral_labels(self):
        w = self._window({})
        self.assertEqual(copy_text.encryption_text(w, "none", "_label"), "No encryption")
        self.assertEqual(copy_text.encryption_text(w, "luks-passphrase", "_label"), "Passphrase")
        self.assertEqual(copy_text.encryption_text(w, "tpm2-luks", "_label"), "TPM")
        self.assertEqual(copy_text.encryption_text(w, "tpm2-luks-passphrase", "_label"),
                         "TPM + passphrase")

    def test_empty_type_is_none(self):
        # fisherman reads "" as no encryption.
        w = self._window({})
        self.assertEqual(copy_text.encryption_text(w, "", "_label"), "No encryption")

    def test_a_product_renames_a_choice_in_its_branding(self):
        w = self._window({"copy": {"encryption_tpm2_luks_label": "Hardware key"}})
        self.assertEqual(copy_text.encryption_text(w, "tpm2-luks", "_label"), "Hardware key")

    def test_unknown_type_has_no_label(self):
        # confirm.py then shows the raw id rather than an empty row.
        w = self._window({})
        self.assertEqual(copy_text.encryption_text(w, "custom-encryption", "_label"), "")


class TestConfirmSubtitleFromBranding(unittest.TestCase):
    """The confirm subtitle is branding copy: a confirm_quotes line for the
    selected language when the product ships one, else confirm_subtitle,
    else nothing. No product quote lives in the installer."""

    def _window(self, branding):
        class W:
            recipe = {"branding": branding}
        return W()

    def test_locale_quote_wins_for_its_language(self):
        w = self._window({"name": "Marlin", "copy": {"confirm_subtitle": "plain"},
                          "confirm_quotes": {"pt_BR": ["only line"]}})
        self.assertEqual(copy_text.confirm_subtitle(w, "pt_BR.UTF-8"), "only line")
        self.assertEqual(copy_text.confirm_subtitle(w, "pt_BR"), "only line")

    def test_other_languages_get_the_plain_subtitle(self):
        w = self._window({"name": "Marlin", "copy": {"confirm_subtitle": "plain"},
                          "confirm_quotes": {"pt_BR": ["only line"]}})
        for lang in ("en_US.UTF-8", "pt_PT", "de_DE", "", None):
            self.assertEqual(copy_text.confirm_subtitle(w, lang), "plain", lang)

    def test_no_branding_means_no_subtitle(self):
        w = self._window({})
        self.assertEqual(copy_text.confirm_subtitle(w, "en_US"), "")

    def test_text_fills_name(self):
        w = self._window({"name": "Marlin", "copy": {}})
        self.assertEqual(copy_text.text(w, "confirm_button"), "Install")
        self.assertEqual(copy_text.text(w, "done_title"), "Marlin is installed")
