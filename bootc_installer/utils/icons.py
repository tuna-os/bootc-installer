"""Logo specs shared by the GNOME welcome, catalog and completion views.

Host /usr and /etc are mounted below /run/host in Flatpak. Never prefix
/app (the application's assets), already-mapped paths or icon names.
"""

import os

from bootc_shared import branding


def resolve_icon(icon_spec, *, in_flatpak=None):
    """Return (resource|file|theme, value), or None when there is nothing
    to show. The rule is bootc_shared.branding.logo_source, which XFCE
    also uses (shared/branding/fixtures/logo-paths.json)."""
    if in_flatpak is None:
        in_flatpak = os.path.exists("/.flatpak-info")
    kind, value = branding.logo_source(icon_spec, in_flatpak)
    return None if kind == "none" else (kind, value)


def set_image_icon(image, icon_spec):
    """Apply a spec to a Gtk.Image (also used by BootcPageHeader)."""
    resolved = resolve_icon(icon_spec)
    if resolved is None:
        return
    kind, value = resolved
    if kind == "resource":
        image.set_from_resource(value)
    elif kind == "file":
        image.set_from_file(value)
    else:
        image.set_from_icon_name(value)
