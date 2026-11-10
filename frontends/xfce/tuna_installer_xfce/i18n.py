"""Translation: the one place a user-facing string goes through (#300).

Every literal this frontend shows is wrapped in `_()`, standard gettext,
domain `tuna-installer-xfce`. No translation ships yet: with no catalog
installed `_()` returns the English text, so nothing changes until a
`.mo` file exists under one of LOCALE_DIRS. tests/test_i18n.py fails on a
bare string literal in a label, title or text.

A sentence with a value in it is `_("... {name} ...").format(name=value)`,
never an f-string: gettext looks the template up, and an f-string has
already put the value in.

Branding copy (core.BRANDING.text) is not wrapped: a product owns those
lines through shared/branding, which has its own override mechanism.

Do not name a parameter or a variable `_` in a module that imports this
`_`: the local name would hide the function (the same test checks it).
"""

import gettext
import os

DOMAIN = "tuna-installer-xfce"

# The Flatpak's prefix, then the system's. gettext also honours the
# LANGUAGE, LC_ALL, LC_MESSAGES and LANG variables by itself.
LOCALE_DIRS = ("/app/share/locale", "/usr/share/locale")


def _find_translation():
    override = os.environ.get("TUNA_INSTALLER_LOCALEDIR", "")
    for localedir in ((override,) if override else ()) + LOCALE_DIRS:
        try:
            return gettext.translation(DOMAIN, localedir=localedir)
        except OSError:
            continue
    return gettext.NullTranslations()


_translation = _find_translation()


def _(message):
    """The translation of `message`, or `message` when there is none."""
    return _translation.gettext(message)


def ngettext(singular, plural, count):
    return _translation.ngettext(singular, plural, count)
