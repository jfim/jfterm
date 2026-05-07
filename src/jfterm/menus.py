from __future__ import annotations

from collections.abc import Callable

from gi.repository import Gtk

from jfterm.matching import matching_projects
from jfterm.models import Group, Tab, Unsorted, Workspace


def build_move_to_popover(
    ws: Workspace,
    tab: Tab,
    current_group: Group,
    on_move: Callable[[Group], None],
) -> Gtk.Popover:
    pop = Gtk.Popover()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.set_margin_start(4)
    box.set_margin_end(4)
    box.set_margin_top(4)
    box.set_margin_bottom(4)

    def _row(label: str, *, sensitive: bool, dest: Group | None) -> Gtk.Button:
        btn = Gtk.Button(label=label)
        btn.add_css_class("flat")
        btn.set_halign(Gtk.Align.FILL)
        btn.set_hexpand(True)
        btn.set_sensitive(sensitive)
        if sensitive and dest is not None:

            def _cb(_b):
                pop.popdown()
                on_move(dest)

            btn.connect("clicked", _cb)
        return btn

    matches = matching_projects(tab.current_cwd, ws.projects)
    if matches:
        for p in matches:
            sensitive = p is not current_group
            box.append(_row(f"Move to project {p.name}", sensitive=sensitive, dest=p))
    else:
        box.append(_row("No matching projects", sensitive=False, dest=None))

    is_unsorted = isinstance(current_group, Unsorted)
    box.append(
        _row(
            "Move to Unsorted",
            sensitive=not is_unsorted,
            dest=ws.unsorted,
        )
    )

    pop.set_child(box)
    return pop
