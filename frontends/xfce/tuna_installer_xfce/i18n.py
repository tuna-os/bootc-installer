"""Translation: the one place a user-facing string goes through (#300).

Every literal this frontend shows is wrapped in `_()`, standard gettext,
domain `tuna-installer-xfce`. Each `po/<lang>.po` is compiled to
`<localedir>/<lang>/LC_MESSAGES/tuna-installer-xfce.mo` by the Flatpak
(flatpak/org.tunaos.InstallerXfce.json); shared/i18n/catalogs.py writes the
`.po` files. With no catalog for the locale, `_()` returns the English text.
tests/test_i18n.py fails on a bare string literal in a label, title or
text; tests/test_catalogs.py loads the shipped catalogs.

A sentence with a value in it is `_("... {name} ...").format(name=value)`,
never an f-string: gettext looks the template up, and an f-string has
already put the value in.

Branding copy (core.BRANDING.text) is not wrapped: a product owns those
lines through shared/branding, which has its own override mechanism.

Do not name a parameter or a variable `_` in a module that imports this
`_`: the local name would hide the function (the same test checks it).
"""

import gettext
import locale
import os

DOMAIN = "tuna-installer-xfce"

# The Flatpak's prefix, then the system's. gettext also honours the
# LANGUAGE, LC_ALL, LC_MESSAGES and LANG variables by itself.
LOCALE_DIRS = ("/app/share/locale", "/usr/share/locale")


def _bind(localedir):
    """Bind the domain to `localedir` for gettext and for the C library, so
    every lookup of the domain reads the catalog that _() reads."""
    gettext.bindtextdomain(DOMAIN, localedir)
    gettext.textdomain(DOMAIN)
    if hasattr(locale, "bindtextdomain"):
        try:
            locale.bindtextdomain(DOMAIN, localedir)
            locale.textdomain(DOMAIN)
        except OSError:
            pass


def _find_translation():
    override = os.environ.get("TUNA_INSTALLER_LOCALEDIR", "")
    for localedir in ((override,) if override else ()) + LOCALE_DIRS:
        try:
            translation = gettext.translation(DOMAIN, localedir=localedir)
        except OSError:
            continue
        _bind(localedir)
        return translation
    return gettext.NullTranslations()


_translation = _find_translation()


def _(message):
    """The translation of `message`, or `message` when there is none."""
    return _translation.gettext(message)


def ngettext(singular, plural, count):
    return _translation.ngettext(singular, plural, count)
