from __future__ import annotations

import math

from gi.repository import GObject, Graphene, Gtk


class StatusDot(Gtk.Widget):
    """Small circular indicator. Two axes: filled vs outline, blue vs grey."""

    __gsignals__ = {
        "clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    SIZE = 12
    BLUE = (0.20, 0.50, 1.00, 1.0)
    GREY = (0.55, 0.55, 0.55, 1.0)

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(self.SIZE, self.SIZE)
        self._running = False
        self._filled = True

        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("released", self._on_click_released)
        self.add_controller(click)

    def set_state(self, *, running: bool, filled: bool) -> None:
        if (running, filled) == (self._running, self._filled):
            return
        self._running, self._filled = running, filled
        self.queue_draw()

    def do_snapshot(self, snapshot) -> None:  # type: ignore[override]
        w, h = self.get_width(), self.get_height()
        if w == 0 or h == 0:
            return
        diam = min(w, h) - 2
        cx, cy = w / 2, h / 2

        rect = Graphene.Rect().init(0, 0, w, h)
        cr = snapshot.append_cairo(rect)
        r, g, b, a = self.BLUE if self._running else self.GREY

        cr.arc(cx, cy, diam / 2, 0, 2 * math.pi)
        cr.set_source_rgba(r, g, b, a)
        if self._filled:
            cr.fill()
        else:
            cr.set_line_width(1.5)
            cr.stroke()

    def _on_click_released(self, _gesture, _n_press, _x, _y) -> None:
        self.emit("clicked")
