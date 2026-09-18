"""
Unit tests for confirm.py and related helpers — pure Python, no GTK required.
Covers _ENC_LABELS lookup, quote selection logic, and keyboard formatting.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bootc_installer.utils import copy as copy_text  # noqa: E402
from bootc_installer.views.confirm_data import _ENC_LABELS  # noqa: E402


class TestEncLabels(unittest.TestCase):
    """_ENC_LABELS maps all four encryption type strings to human-readable labels."""

    def test_none_label(self):
        self.assertEqual(_ENC_LABELS["none"], "None")

    def test_luks_passphrase_label(self):
        self.assertIn("passphrase", _ENC_LABELS["luks-passphrase"].lower())

    def test_tpm2_luks_label(self):
        label = _ENC_LABELS["tpm2-luks"]
        self.assertTrue(label, "tpm2-luks should have a non-empty label")
        self.assertNotIn("passphrase", label.lower(),
                         "tpm2-luks-only label should not mention passphrase")

    def test_tpm2_luks_passphrase_label(self):
        label = _ENC_LABELS["tpm2-luks-passphrase"]
        self.assertIn("passphrase", label.lower())

    def test_all_four_keys_present(self):
        expected = {"none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"}
        self.assertEqual(set(_ENC_LABELS.keys()), expected)

    def test_all_labels_are_non_empty_strings(self):
        for key, label in _ENC_LABELS.items():
            self.assertIsInstance(label, str, f"Label for {key!r} is not a string")
            self.assertTrue(label.strip(), f"Label for {key!r} is empty")

    def test_fallback_for_unknown_type(self):
        # Unknown type falls through to raw key — callers use .get(type, type)
        unknown = "custom-encryption"
        result = _ENC_LABELS.get(unknown, unknown)
        self.assertEqual(result, unknown)


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
