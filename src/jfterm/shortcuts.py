from __future__ import annotations

from collections.abc import Callable

from gi.repository import Gio, Gtk


def install(
    window: Gtk.ApplicationWindow,
    *,
    actions: dict[str, Callable[[], None]],
) -> None:
    """Register named actions on the window.

    Keys of `actions` must look like 'win.<name>'. Accelerators are bound
    by the caller via `app.set_accels_for_action()`.
    """
    for full_name, fn in actions.items():
        assert full_name.startswith("win."), full_name
        name = full_name.split(".", 1)[1]
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda *_a, _fn=fn: _fn())
        window.add_action(action)
