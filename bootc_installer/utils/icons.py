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


# One paintable for each logo file and size, shared by every image that
# shows it, drawn at the size it shows. Gtk.Image.set_from_file() and
# set_from_resource() decode the file again for each image, at the file's
# own size: the catalog shows about 190 logos, and each catalog page held
# about 180 MB of pixels that draw at 24 or 32 px (#321: the UI suite ran
# out of memory). Three device pixels for each logical pixel keep a logo
# sharp on a scaled display.
_SCALE = 3
_paintables = {}


def _load_paintable(kind, value, size):
    from gi.repository import Gio, Gtk

    gfile = (Gio.File.new_for_uri("resource://" + value) if kind == "resource"
             else Gio.File.new_for_path(value))
    return Gtk.IconPaintable.new_for_file(gfile, size, _SCALE)


def _paintable(kind, value, size):
    key = (kind, value, size)
    if key not in _paintables:
        _paintables[key] = _load_paintable(kind, value, size)
    return _paintables[key]


def set_image_icon(image, icon_spec):
    """Apply a spec to a Gtk.Image (also used by BootcPageHeader)."""
    resolved = resolve_icon(icon_spec)
    if resolved is None:
        return
    kind, value = resolved
    size = image.get_pixel_size()
    if kind in ("resource", "file") and isinstance(size, int) and size > 0:
        image.set_from_paintable(_paintable(kind, value, size))
    elif kind == "resource":
        image.set_from_resource(value)
    elif kind == "file":
        image.set_from_file(value)
    else:
        image.set_from_icon_name(value)
