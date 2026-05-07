import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Graphene, Gtk  # noqa: E402

_STATE_CLASSES = {
    1: "progress-normal",
    2: "progress-error",
    3: "progress-indeterminate",
    4: "progress-paused",
}

_BAR_HEIGHT = 3
_INDETERMINATE_PERIOD_MS = 1500
_INDETERMINATE_TICK_MS = 33  # ~30 fps
_INDETERMINATE_WIDTH_FRAC = 0.30


class TabProgressBar(Gtk.Widget):
    """Thin progress bar overlaid on a tab title.

    Reads its color from the resolved CSS color of whichever
    `progress-*` class is active.
    """

    def __init__(self) -> None:
        super().__init__()
        self._state = 0
        self._value = 0
        self._anim_phase = 0.0  # 0..1
        self._anim_source: int | None = None
        self.set_visible(False)
        self.set_size_request(-1, _BAR_HEIGHT)
        self.set_valign(Gtk.Align.END)
        self.set_hexpand(True)
        # Don't intercept input.
        self.set_can_target(False)
        self.set_can_focus(False)

    def set_progress(self, state: int, value: int) -> None:
        if state == self._state and value == self._value:
            return
        # Swap CSS class.
        for cls in _STATE_CLASSES.values():
            if self.has_css_class(cls):
                self.remove_css_class(cls)
        new_class = _STATE_CLASSES.get(state)
        if new_class is not None:
            self.add_css_class(new_class)
        self._state = state
        self._value = max(0, min(100, value))
        self.set_visible(state != 0)
        if state == 3:
            self._start_animation()
        else:
            self._stop_animation()
        self.queue_draw()

    def _start_animation(self) -> None:
        if self._anim_source is not None:
            return
        self._anim_source = GLib.timeout_add(_INDETERMINATE_TICK_MS, self._tick)

    def _stop_animation(self) -> None:
        if self._anim_source is not None:
            GLib.source_remove(self._anim_source)
            self._anim_source = None
        self._anim_phase = 0.0

    def _tick(self) -> bool:
        self._anim_phase = (
            self._anim_phase + _INDETERMINATE_TICK_MS / _INDETERMINATE_PERIOD_MS
        ) % 1.0
        self.queue_draw()
        return True

    def do_unmap(self) -> None:  # type: ignore[override]
        self._stop_animation()
        Gtk.Widget.do_unmap(self)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:  # type: ignore[override]
        if self._state == 0:
            return
        width = self.get_width()
        height = self.get_height()
        if width <= 0 or height <= 0:
            return

        color = self._resolve_color()

        if self._state == 3:
            # Indeterminate: a band of width INDETERMINATE_WIDTH_FRAC sweeps
            # across the bar; the leading edge moves from -W to width.
            band_w = max(1.0, width * _INDETERMINATE_WIDTH_FRAC)
            x_start = -band_w + (width + band_w) * self._anim_phase
            rect = Graphene.Rect().init(x_start, 0, band_w, height)
            snapshot.append_color(color, rect)
            return

        if self._state == 2 and self._value == 0:
            fill_w = float(width)
        else:
            fill_w = width * (self._value / 100.0)
        if fill_w <= 0:
            return
        rect = Graphene.Rect().init(0, 0, fill_w, height)
        snapshot.append_color(color, rect)

    def _resolve_color(self) -> Gdk.RGBA:
        # Pull the color the active CSS class resolves to.
        return self.get_color()
