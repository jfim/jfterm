from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GObject, Gtk  # noqa: E402

from jfterm.fuzzy import rank  # noqa: E402
from jfterm.launcher_items import Action, LauncherItem, build_items  # noqa: E402
from jfterm.models import Workspace  # noqa: E402

MAX_RECENTS = 8


class _LauncherRow(GObject.Object):
    """Boxed row for the GListStore. Plain attributes on a GObject suffice."""

    __gtype_name__ = "JFTermLauncherRow"

    def __init__(self, *, display: str, action: Action) -> None:
        super().__init__()
        self.display = display
        self.action = action


class Launcher:
    def __init__(
        self,
        parent: Gtk.Window,
        dispatch: Callable[[Action], None],
    ) -> None:
        self._parent = parent
        self._dispatch = dispatch
        self._recents: list[Action] = []
        self._window: Adw.Window | None = None
        self._entry: Gtk.SearchEntry | None = None
        self._list_view: Gtk.ListView | None = None
        self._store: Gio.ListStore | None = None
        self._selection: Gtk.SingleSelection | None = None
        self._items: list[LauncherItem] = []

    @staticmethod
    def filter_items(query: str, items: list[LauncherItem]) -> list[LauncherItem]:
        if query == "":
            return []
        return rank(query, items, key=lambda it: it.display)

    @staticmethod
    def push_recent(recents: list[Action], action: Action, *, max_recents: int) -> None:
        if action in recents:
            recents.remove(action)
        recents.insert(0, action)
        del recents[max_recents:]

    @staticmethod
    def recents_in_items(recents: list[Action], items: list[LauncherItem]) -> list[Action]:
        # List-based membership — Action wraps non-frozen dataclasses
        # (e.g. FlashCommand) so hashing is unavailable; equality works.
        present = [it.action for it in items]
        return [a for a in recents if a in present]

    def open(self, workspace: Workspace) -> None:
        if self._window is not None:
            return
        self._items = build_items(workspace)

        window = Adw.Window(transient_for=self._parent, modal=True)
        window.set_default_size(600, 400)
        window.set_title("Launcher")

        entry = Gtk.SearchEntry()
        entry.set_hexpand(True)
        entry.connect("search-changed", self._on_search_changed)
        entry.connect("activate", self._on_activate)

        store = Gio.ListStore(item_type=_LauncherRow)
        selection = Gtk.SingleSelection(model=store)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._row_setup)
        factory.connect("bind", self._row_bind)
        list_view = Gtk.ListView(model=selection, factory=factory)
        list_view.set_vexpand(True)
        list_view.connect("activate", self._on_row_activate)

        scroller = Gtk.ScrolledWindow()
        scroller.set_child(list_view)
        scroller.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(entry)
        box.append(scroller)
        window.set_content(box)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key_pressed)
        window.add_controller(key)

        self._window = window
        self._entry = entry
        self._list_view = list_view
        self._store = store
        self._selection = selection

        self._refresh()
        window.present()
        entry.grab_focus()

    def _close(self) -> None:
        if self._window is not None:
            self._window.close()
            self._window = None
            self._entry = None
            self._list_view = None
            self._store = None
            self._selection = None

    def _on_key_pressed(self, _ctrl, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._close()
            return True
        return False

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._refresh(entry.get_text())

    def _on_activate(self, _entry: Gtk.SearchEntry) -> None:
        self._activate_selected()

    def _on_row_activate(self, _lv, _pos) -> None:
        self._activate_selected()

    def _activate_selected(self) -> None:
        if self._selection is None or self._store is None:
            return
        idx = self._selection.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION:
            return
        row = self._store.get_item(idx)
        if row is None:
            return
        action = row.action  # type: ignore[attr-defined]
        Launcher.push_recent(self._recents, action, max_recents=MAX_RECENTS)
        self._close()
        self._dispatch(action)

    def _refresh(self, query: str = "") -> None:
        if self._store is None:
            return
        self._store.remove_all()
        if query == "":
            visible_actions = Launcher.recents_in_items(self._recents, self._items)
            rows = []
            for a in visible_actions:
                for it in self._items:
                    if it.action == a:
                        rows.append(_LauncherRow(display=it.display, action=a))
                        break
        else:
            filtered = Launcher.filter_items(query, self._items)
            rows = [_LauncherRow(display=it.display, action=it.action) for it in filtered]
        for r in rows:
            self._store.append(r)
        if self._selection is not None and self._store.get_n_items() > 0:
            self._selection.set_selected(0)

    def _row_setup(self, _factory, list_item: Gtk.ListItem) -> None:
        label = Gtk.Label(xalign=0)
        label.set_margin_start(8)
        label.set_margin_end(8)
        label.set_margin_top(4)
        label.set_margin_bottom(4)
        list_item.set_child(label)

    def _row_bind(self, _factory, list_item: Gtk.ListItem) -> None:
        row = list_item.get_item()
        label = list_item.get_child()
        if row is not None and isinstance(label, Gtk.Label):
            label.set_text(row.display)  # type: ignore[attr-defined]
