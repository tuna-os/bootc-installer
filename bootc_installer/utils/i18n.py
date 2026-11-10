"""The one gettext domain, and the one place that binds it.

Three things must agree or no translation loads (#311): the domain meson
builds the catalogs under (po/meson.build), the domain the C library uses for
the GTK templates, and the domain Python's gettext uses for `_()` in the
modules. tests/unit/test_i18n.py holds them together.
"""

import gettext
import locale
import logging

logger = logging.getLogger("Installer::I18n")

DOMAIN = "bootc-installer"


def bind(localedir):
    """Point every gettext user in the process at DOMAIN in `localedir`."""
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error as e:
        logger.warning("Unsupported locale, the interface stays in English: %s", e)
    # The C library: Gtk.Builder translates the templates through it. A libc
    # without gettext (musl) has none of these; the Python side still works.
    if hasattr(locale, "bindtextdomain"):
        locale.bindtextdomain(DOMAIN, localedir)
        locale.textdomain(DOMAIN)
        if hasattr(locale, "bind_textdomain_codeset"):
            locale.bind_textdomain_codeset(DOMAIN, "UTF-8")
    # Python: the modules do `from gettext import gettext as _`, which reads
    # the module-level default domain. gettext.install() alone does not set
    # it; it only puts a `_` into builtins.
    gettext.bindtextdomain(DOMAIN, localedir)
    gettext.textdomain(DOMAIN)
    gettext.install(DOMAIN, localedir)
