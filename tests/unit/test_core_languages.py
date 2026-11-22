"""core/languages.py: how a locale is named and how the session's is read.

`language_name` must never stop the language step: a missing typelib, a
typelib error or an empty answer all fall back to the locale itself.
`session_locale` returns "" for a session whose locale the list cannot hold.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from bootc_installer.core import languages  # noqa: E402


class LanguageNameTest(unittest.TestCase):
    def test_without_the_typelib_the_locale_is_its_own_name(self):
        with patch.object(languages, "GnomeDesktop", None):
            self.assertEqual(languages.language_name("de_DE.UTF-8"), "de_DE.UTF-8")

    def test_the_typelib_names_the_locale(self):
        gnome = MagicMock()
        gnome.get_language_from_locale.return_value = "Deutsch (Deutschland)"
        with patch.object(languages, "GnomeDesktop", gnome):
            self.assertEqual(languages.language_name("de_DE.UTF-8"), "Deutsch (Deutschland)")
        gnome.get_language_from_locale.assert_called_once_with("de_DE.UTF-8", None)

    def test_a_typelib_error_falls_back_to_the_locale(self):
        gnome = MagicMock()
        gnome.get_language_from_locale.side_effect = RuntimeError("no such locale")
        with patch.object(languages, "GnomeDesktop", gnome):
            self.assertEqual(languages.language_name("xx_XX.UTF-8"), "xx_XX.UTF-8")

    def test_an_empty_name_falls_back_to_the_locale(self):
        for empty in (None, ""):
            gnome = MagicMock()
            gnome.get_language_from_locale.return_value = empty
            with patch.object(languages, "GnomeDesktop", gnome):
                self.assertEqual(languages.language_name("xx_XX.UTF-8"), "xx_XX.UTF-8")


class SessionLocaleTest(unittest.TestCase):
    def _session(self, value):
        return patch.object(languages.locale, "getlocale", return_value=value)

    def test_a_locale_with_an_encoding_is_joined(self):
        with self._session(("en_US", "UTF-8")):
            self.assertEqual(languages.session_locale(), "en_US.UTF-8")

    def test_a_locale_without_an_encoding_is_returned_bare(self):
        with self._session(("en_US", None)):
            self.assertEqual(languages.session_locale(), "en_US")

    def test_c_posix_and_unset_have_no_session_locale(self):
        for value in (("C", "UTF-8"), ("POSIX", None), (None, None), ("", None)):
            with self._session(value):
                self.assertEqual(languages.session_locale(), "", value)


if __name__ == "__main__":
    unittest.main()
