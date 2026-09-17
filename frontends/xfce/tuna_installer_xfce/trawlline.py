"""The trawl line — this frontend's single signature element (see DESIGN.md).

A GtkDrawingArea rendering the wizard steps as knots on a horizontal line.
During install it doubles as the 9-step pipeline progress bar."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

SONAR = (0x2E / 255, 0xC4 / 255, 0xB6 / 255)


class TrawlLine(Gtk.DrawingArea):
    def __init__(self, n_steps):
        super().__init__()
        self.n_steps = n_steps
        self.current = 0
        self.fill = 0.0  # 0..1, install progress overlay
        self.set_size_request(-1, 28)
        self.connect("draw", self._draw)

    def set_step(self, i):
        self.current = i
        self.queue_draw()

    def set_fill(self, frac):
        self.fill = max(0.0, min(1.0, frac))
        self.queue_draw()

    def _draw(self, _w, cr):
        style = self.get_style_context()
        fg = style.get_color(Gtk.StateFlags.NORMAL)
        w = self.get_allocated_width()
        y = 14.0
        margin = 24.0
        span = w - 2 * margin

        # line
        cr.set_line_width(3)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.25)
        cr.move_to(margin, y)
        cr.line_to(margin + span, y)
        cr.stroke()

        # install-progress fill
        if self.fill > 0:
            cr.set_source_rgb(*SONAR)
            cr.move_to(margin, y)
            cr.line_to(margin + span * self.fill, y)
            cr.stroke()

        # knots
        step = span / max(1, self.n_steps - 1)
        for i in range(self.n_steps):
            x = margin + i * step
            if i < self.current:
                cr.set_source_rgb(*SONAR)
                cr.arc(x, y, 4, 0, 6.2832)
                cr.fill()
            elif i == self.current:
                cr.set_source_rgb(*SONAR)
                cr.set_line_width(2.5)
                cr.arc(x, y, 5, 0, 6.2832)
                cr.stroke()
            else:
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.35)
                cr.arc(x, y, 3.2, 0, 6.2832)
                cr.fill()
        return False
