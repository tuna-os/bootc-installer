"""A first-run tour carousel, mirroring GNOME's views/tour.py.

GNOME renders its tour slides as full wizard steps from recipe.json's tour
pages (title, description, resource or image). This frontend keeps its eight
wizard pages (DESIGN.md, PAGE_ORDER) and shows the tour where a newcomer
actually waits: on the welcome page, as a small carousel of the catalog's
own entries -- each image family in its own words, so the slide text can
never drift from what the source page offers.

Slides come from the catalog roots (a root's name and desc/subtitle), which
is the content this frontend already loads for the source page. No slides
(no catalog, or roots without text) means no carousel: the welcome page is
unchanged.
"""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


def slides_from_catalog(catalog):
    """One {title, description} slide per catalog root that has both.

    `catalog` is core.load_catalog().roots. Roots
    carry the family name and desc; leaves carry imgrefs, which are not tour
    material. Order is the catalog's own.
    """
    slides = []
    for root in catalog or []:
        title = (root.name or "").strip()
        description = (root.desc or root.subtitle or "").strip()
        if title and description:
            slides.append({"title": title, "description": description})
    return slides


class TourCarousel(Gtk.Box):
    """A small slide carousel: title, description, and < > pager.

    GTK3 idioms throughout (Gtk.Stack, plain buttons, theme colors only --
    DESIGN.md forbids hex here). Always advancable: a tour never gates the
    install, which is also why the wizard's Next stays independent of it.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                         margin_top=12)
        self._slides = []
        self._index = 0

        self.stack = Gtk.Stack()
        self.pack_start(self.stack, False, False, 0)

        pager = Gtk.Box(spacing=8)
        pager.set_halign(Gtk.Align.CENTER)
        self.prev_btn = Gtk.Button(label="<")
        self.next_btn = Gtk.Button(label=">")
        self.prev_btn.connect("clicked", lambda *_: self.show(self._index - 1))
        self.next_btn.connect("clicked", lambda *_: self.show(self._index + 1))
        self.position = Gtk.Label()
        pager.pack_start(self.prev_btn, False, False, 0)
        pager.pack_start(self.position, False, False, 0)
        pager.pack_start(self.next_btn, False, False, 0)
        self.pager = pager
        self.pack_start(pager, False, False, 0)

    def set_slides(self, slides):
        """Replace the slides; an empty list hides the whole carousel."""
        for child in self.stack.get_children():
            self.stack.remove(child)
        self._slides = list(slides or [])
        self._index = 0
        for slide in self._slides:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title = Gtk.Label(xalign=0)
            title.set_markup("<b>{}</b>".format(_escape(slide["title"])))
            title.set_line_wrap(True)
            body = Gtk.Label(xalign=0)
            body.set_text(slide["description"])
            body.set_line_wrap(True)
            box.pack_start(title, False, False, 0)
            box.pack_start(body, False, False, 0)
            self.stack.add_named(box, str(len(self.stack.get_children())))
        self.set_visible(bool(self._slides))
        self.set_no_show_all(not self._slides)
        self.show(0)

    def show(self, index):
        """Show slide `index`, clamped. Out-of-range is a no-op past the
        clamp, so holding > parks on the last slide instead of wrapping."""
        if not self._slides:
            return
        self._index = max(0, min(len(self._slides) - 1, index))
        self.stack.set_visible_child_name(str(self._index))
        self.position.set_text(f"{self._index + 1} of {len(self._slides)}")
        self.prev_btn.set_sensitive(self._index > 0)
        self.next_btn.set_sensitive(self._index < len(self._slides) - 1)

    def __len__(self):
        return len(self._slides)


def _escape(text):
    from gi.repository import GLib
    return GLib.markup_escape_text(text)
