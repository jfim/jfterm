from __future__ import annotations

from collections.abc import Callable

from gi.repository import Gdk, GObject, Gtk

from jfterm.matching import is_inside, matching_projects
from jfterm.models import Group, Project, Tab, Workspace
from jfterm.status_dot import StatusDot


class _TabRef(GObject.Object):
    """GObject wrapper around a Tab so it can travel through GValue/Gdk DnD.

    GValue's TYPE_PYOBJECT path doesn't accept Python objects via set_object;
    a real GObject does. This carrier holds the actual Tab as a Python attr.
    """

    def __init__(self, tab: Tab) -> None:
        super().__init__()
        self.tab = tab


class Sidebar(Gtk.ScrolledWindow):
    """Sidebar listing projects and their tabs, plus Unsorted.

    Rebuild-from-model strategy: simple and good enough at our scale.
    """

    __gsignals__ = {
        "tab-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "new-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "close-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "restart-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "configure-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "launch-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "new-project-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "toggle-expanded-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "dot-clicked": (GObject.SignalFlags.RUN_FIRST, None, (object, object, object)),
        "tab-dropped": (GObject.SignalFlags.RUN_FIRST, None, (object, object, int)),
    }

    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_min_content_width(200)
        self._ws = ws

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._box.add_css_class("navigation-sidebar")
        self.set_child(self._box)
        self.refresh()

    # --- public API ---

    def refresh(self) -> None:
        child = self._box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._box.remove(child)
            child = nxt

        new_proj_btn = Gtk.Button(label="+ New project")
        new_proj_btn.add_css_class("flat")
        new_proj_btn.connect("clicked", lambda _b: self.emit("new-project-requested"))
        self._box.append(new_proj_btn)

        for project in self._ws.projects:
            self._add_project_row(project)
            if project.expanded:
                for tab in project.tabs:
                    self._add_tab_row(project, tab)
                self._add_drop_sentinel(project)

        self._add_unsorted_row(self._ws.unsorted)
        if self._ws.unsorted.expanded:
            for tab in self._ws.unsorted.tabs:
                self._add_tab_row(self._ws.unsorted, tab)
            self._add_drop_sentinel(self._ws.unsorted)

    # --- DnD helpers ---

    def _attach_drag(self, row: Gtk.Widget, tab: Tab) -> None:
        src = Gtk.DragSource()
        src.set_actions(Gdk.DragAction.MOVE)

        def _prepare(_s, _x, _y):
            v = GObject.Value()
            v.init(_TabRef.__gtype__)
            v.set_object(_TabRef(tab))
            return Gdk.ContentProvider.new_for_value(v)

        src.connect("prepare", _prepare)
        row.add_controller(src)

    def _attach_drop(
        self,
        row: Gtk.Widget,
        target_group: Group,
        target_position_callable: Callable[[], int],
    ) -> None:
        target = Gtk.DropTarget.new(_TabRef.__gtype__, Gdk.DragAction.MOVE)

        def _on_drop(_t, value, _x, _y):
            tab = value.tab if isinstance(value, _TabRef) else value
            self.emit("tab-dropped", tab, target_group, target_position_callable())
            return True

        target.connect("drop", _on_drop)
        row.add_controller(target)

    def _add_drop_sentinel(self, group: Group) -> None:
        sentinel = Gtk.Box()
        sentinel.set_size_request(-1, 6)
        self._attach_drop(sentinel, group, lambda g=group: len(g.tabs))
        self._box.append(sentinel)

    # --- row builders ---

    def _add_project_row(self, project: Project) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_margin_start(4)
        row.set_margin_end(4)

        chevron = Gtk.Button.new_from_icon_name(
            "pan-down-symbolic" if project.expanded else "pan-end-symbolic"
        )
        chevron.add_css_class("flat")
        chevron.connect(
            "clicked",
            lambda _b, p=project: self.emit("toggle-expanded-requested", p),
        )

        label_btn = Gtk.Button(label=project.name)
        label_btn.add_css_class("flat")
        label_btn.set_hexpand(True)
        label_btn.set_halign(Gtk.Align.START)
        label_btn.connect(
            "clicked",
            lambda _b, p=project: self.emit("toggle-expanded-requested", p),
        )

        play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        play.add_css_class("flat")
        play.set_tooltip_text("Launch project")
        play.set_sensitive(bool(project.startup_commands))
        play.connect(
            "clicked",
            lambda _b, p=project: self.emit("launch-project-requested", p),
        )

        cog = Gtk.Button.new_from_icon_name("emblem-system-symbolic")
        cog.add_css_class("flat")
        cog.set_tooltip_text("Settings")
        cog.connect(
            "clicked",
            lambda _b, p=project: self.emit("configure-project-requested", p),
        )

        plus = Gtk.Button.new_from_icon_name("list-add-symbolic")
        plus.add_css_class("flat")
        plus.set_tooltip_text("New tab")
        plus.connect("clicked", lambda _b, p=project: self.emit("new-tab-requested", p))

        for w in (chevron, label_btn, play, cog, plus):
            row.append(w)
        self._box.append(row)

    def _add_unsorted_row(self, group: Group) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_margin_start(4)
        row.set_margin_end(4)

        chevron = Gtk.Button.new_from_icon_name(
            "pan-down-symbolic" if group.expanded else "pan-end-symbolic"
        )
        chevron.add_css_class("flat")
        chevron.connect(
            "clicked",
            lambda _b, g=group: self.emit("toggle-expanded-requested", g),
        )

        label_btn = Gtk.Button(label="Unsorted")
        label_btn.add_css_class("flat")
        label_btn.set_hexpand(True)
        label_btn.set_halign(Gtk.Align.START)
        label_btn.connect(
            "clicked",
            lambda _b, g=group: self.emit("toggle-expanded-requested", g),
        )

        plus = Gtk.Button.new_from_icon_name("list-add-symbolic")
        plus.add_css_class("flat")
        plus.set_tooltip_text("New tab")
        plus.connect("clicked", lambda _b, g=group: self.emit("new-tab-requested", g))

        for w in (chevron, label_btn, plus):
            row.append(w)
        self._box.append(row)

    def _add_tab_row(self, group: Group, tab: Tab) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_margin_start(20)
        row.set_margin_end(4)

        dot = StatusDot()
        dot.set_valign(Gtk.Align.CENTER)
        if isinstance(group, Project):
            filled = is_inside(tab.current_cwd, group.directory)
        else:
            # Unsorted: filled when no project would match.
            filled = not matching_projects(tab.current_cwd, self._ws.projects)
        dot.set_state(running=tab.is_running, filled=filled)
        tab._dot = dot  # so the runtime layer can update without a full refresh
        dot.connect(
            "clicked",
            lambda _d, t=tab, g=group, anchor=dot: self.emit("dot-clicked", t, g, anchor),
        )

        title = Gtk.Button()
        title.add_css_class("flat")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        title_label = Gtk.Label(label=tab.title or "tab", xalign=0)
        from gi.repository import Pango

        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_label.set_max_width_chars(24)
        title.set_child(title_label)
        title.connect("clicked", lambda _b, t=tab: self.emit("tab-activated", t))

        restart: Gtk.Button | None = None
        if tab.launched_command:
            restart = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
            restart.add_css_class("flat")
            restart.set_tooltip_text("Restart command")
            restart.connect(
                "clicked",
                lambda _b, t=tab: self.emit("restart-tab-requested", t),
            )

        close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close.add_css_class("flat")
        close.connect("clicked", lambda _b, t=tab: self.emit("close-tab-requested", t))

        # DnD: the row is both a drag source (carrying the tab) and a drop
        # target (drop above this row, taking this row's index).
        position_in_group = group.tabs.index(tab)
        self._attach_drag(row, tab)
        self._attach_drop(row, group, lambda pos=position_in_group: pos)

        widgets: list[Gtk.Widget] = [dot, title]
        if restart is not None:
            widgets.append(restart)
        widgets.append(close)
        for w in widgets:
            row.append(w)
        self._box.append(row)
