from __future__ import annotations

from gi.repository import GObject, Gtk

from jfterm.models import Group, Project, Tab, Workspace


class Sidebar(Gtk.ScrolledWindow):
    """Sidebar listing projects and their tabs, plus Unsorted.

    Rebuild-from-model strategy: simple and good enough at our scale.
    """

    __gsignals__ = {
        "tab-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "new-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "close-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "configure-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "new-project-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "toggle-expanded-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
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

        for project in self._ws.projects:
            self._add_project_row(project)
            if project.expanded:
                for tab in project.tabs:
                    self._add_tab_row(project, tab)

        new_proj_btn = Gtk.Button(label="+ New project")
        new_proj_btn.add_css_class("flat")
        new_proj_btn.connect("clicked", lambda _b: self.emit("new-project-requested"))
        self._box.append(new_proj_btn)

        self._add_unsorted_row(self._ws.unsorted)
        for tab in self._ws.unsorted.tabs:
            self._add_tab_row(self._ws.unsorted, tab)

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

        cog = Gtk.Button.new_from_icon_name("emblem-system-symbolic")
        cog.add_css_class("flat")
        cog.connect(
            "clicked",
            lambda _b, p=project: self.emit("configure-project-requested", p),
        )

        plus = Gtk.Button.new_from_icon_name("list-add-symbolic")
        plus.add_css_class("flat")
        plus.connect(
            "clicked", lambda _b, p=project: self.emit("new-tab-requested", p)
        )

        for w in (chevron, label_btn, cog, plus):
            row.append(w)
        self._box.append(row)

    def _add_unsorted_row(self, group: Group) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_margin_start(4)
        row.set_margin_end(4)

        label = Gtk.Label(label="Unsorted", xalign=0)
        label.set_hexpand(True)

        plus = Gtk.Button.new_from_icon_name("list-add-symbolic")
        plus.add_css_class("flat")
        plus.connect(
            "clicked", lambda _b, g=group: self.emit("new-tab-requested", g)
        )

        row.append(label)
        row.append(plus)
        self._box.append(row)

    def _add_tab_row(self, group: Group, tab: Tab) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_margin_start(20)
        row.set_margin_end(4)

        title = Gtk.Button(label=tab.title or "tab")
        title.add_css_class("flat")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        title.connect("clicked", lambda _b, t=tab: self.emit("tab-activated", t))

        close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close.add_css_class("flat")
        close.connect(
            "clicked", lambda _b, t=tab: self.emit("close-tab-requested", t)
        )

        row.append(title)
        row.append(close)
        self._box.append(row)
