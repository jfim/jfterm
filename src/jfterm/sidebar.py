from __future__ import annotations

from collections.abc import Callable

from gi.repository import Gdk, GObject, Gtk

from jfterm.matching import is_inside, matching_projects
from jfterm.models import Group, Project, Tab, TerminalTab, Workspace
from jfterm.progress_bar import TabProgressBar
from jfterm.status_dot import StatusDot


class _TabRef(GObject.Object):
    """GObject wrapper around a Tab so it can travel through GValue/Gdk DnD.

    GValue's TYPE_PYOBJECT path doesn't accept Python objects via set_object;
    a real GObject does. This carrier holds the actual Tab as a Python attr.
    """

    def __init__(self, tab: Tab) -> None:
        super().__init__()
        self.tab = tab


class _ProjectRef(GObject.Object):
    """GObject wrapper around a Project for project DnD.

    Distinct GType from `_TabRef` so project drop targets only accept
    project drags and tab drop targets only accept tab drags.
    """

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project


class Sidebar(Gtk.ScrolledWindow):
    """Sidebar listing projects and their tabs, plus Unsorted.

    Rebuild-from-model strategy: simple and good enough at our scale.
    """

    # new-web-tab-requested(Group, str url): if `url` is empty, the window
    # should prompt the user for one (via show_new_web_tab_dialog); otherwise
    # the window should spawn a web tab pointing at that URL directly.
    __gsignals__ = {
        "tab-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "new-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "new-web-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object, str)),
        "close-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "restart-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "configure-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "archive-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "delete-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "launch-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "flash-command-launched": (GObject.SignalFlags.RUN_FIRST, None, (object, object)),
        "new-project-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "toggle-expanded-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "dot-clicked": (GObject.SignalFlags.RUN_FIRST, None, (object, object, object)),
        "tab-dropped": (GObject.SignalFlags.RUN_FIRST, None, (object, object, int)),
        "project-dropped": (GObject.SignalFlags.RUN_FIRST, None, (object, int)),
        "unarchive-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "toggle-archived-expanded-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    _css_installed = False

    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_min_content_width(200)
        self._ws = ws
        self._active_tab: Tab | None = None

        self._install_css()

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._box.set_vexpand(True)
        self._box.add_css_class("navigation-sidebar")
        self.set_child(self._box)
        self.refresh()

    @classmethod
    def _install_css(cls) -> None:
        if cls._css_installed:
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b".jfterm-active-tab { "
            b"background-color: alpha(@accent_bg_color, 0.25); "
            b"border-radius: 6px; "
            b"}"
            b".progress-normal        { color: @accent_bg_color; }"
            b".progress-error         { color: @error_bg_color; }"
            b".progress-paused        { color: @warning_bg_color; }"
            b".progress-indeterminate { color: @accent_bg_color; }"
        )
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        cls._css_installed = True

    def set_active_tab(self, tab: Tab | None) -> None:
        if self._active_tab is tab:
            return
        self._active_tab = tab
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

        active = self._ws.active_projects
        for idx, project in enumerate(active):
            if idx > 0:
                self._add_separator()
            self._add_project_row(project, idx)
            if project.expanded:
                for tab in project.tabs:
                    self._add_tab_row(project, tab)
                self._add_drop_sentinel(project)
        if active:
            self._add_project_end_sentinel()

        if active:
            self._add_separator()
        self._add_unsorted_row(self._ws.unsorted)
        if self._ws.unsorted.expanded:
            for tab in self._ws.unsorted.tabs:
                self._add_tab_row(self._ws.unsorted, tab)
            self._add_drop_sentinel(self._ws.unsorted)

        archived = self._ws.archived_projects
        if archived:
            spacer = Gtk.Box()
            spacer.set_vexpand(True)
            self._box.append(spacer)
            self._add_separator()
            self._add_archived_header()
            if self._ws.archived_expanded:
                for project in archived:
                    self._add_archived_row(project)

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

    def _attach_project_drag(self, row: Gtk.Widget, project: Project) -> None:
        src = Gtk.DragSource()
        src.set_actions(Gdk.DragAction.MOVE)

        def _prepare(_s, _x, _y):
            v = GObject.Value()
            v.init(_ProjectRef.__gtype__)
            v.set_object(_ProjectRef(project))
            return Gdk.ContentProvider.new_for_value(v)

        src.connect("prepare", _prepare)
        row.add_controller(src)

    def _attach_project_drop(
        self,
        row: Gtk.Widget,
        target_position_callable: Callable[[], int],
    ) -> None:
        target = Gtk.DropTarget.new(_ProjectRef.__gtype__, Gdk.DragAction.MOVE)

        def _on_drop(_t, value, _x, _y):
            project = value.project if isinstance(value, _ProjectRef) else value
            self.emit("project-dropped", project, target_position_callable())
            return True

        target.connect("drop", _on_drop)
        row.add_controller(target)

    def _add_separator(self) -> None:
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(6)
        sep.set_margin_bottom(6)
        sep.set_margin_start(8)
        sep.set_margin_end(8)
        self._box.append(sep)

    def _attach_plus_right_click(self, plus_btn: Gtk.Widget, group: Group) -> None:
        """Attach a secondary-click gesture that opens the new-tab kind popover."""
        gesture = Gtk.GestureClick()
        gesture.set_button(Gdk.BUTTON_SECONDARY)

        def _on_pressed(_g: Gtk.GestureClick, _n: int, _x: float, _y: float) -> None:
            self._show_new_tab_popover(plus_btn, group)

        gesture.connect("pressed", _on_pressed)
        plus_btn.add_controller(gesture)

    def _show_new_tab_popover(self, anchor: Gtk.Widget, group: Group) -> None:
        from jfterm.webtab import WEBKIT_PACKAGE, is_available

        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(4)
        box.set_margin_end(4)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        term_btn = Gtk.Button(label="New terminal tab")
        term_btn.add_css_class("flat")
        term_btn.set_halign(Gtk.Align.FILL)

        def _on_term(_b: Gtk.Button, g: Group = group, popover: Gtk.Popover = pop) -> None:
            popover.popdown()
            self.emit("new-tab-requested", g)

        term_btn.connect("clicked", _on_term)
        box.append(term_btn)

        web_btn = Gtk.Button(label="New web tab…")
        web_btn.add_css_class("flat")
        web_btn.set_halign(Gtk.Align.FILL)
        if not is_available():
            web_btn.set_sensitive(False)
            web_btn.set_tooltip_text(f"WebKit not available — install {WEBKIT_PACKAGE}")
        else:

            def _on_web(_b: Gtk.Button, g: Group = group, popover: Gtk.Popover = pop) -> None:
                popover.popdown()
                self.emit("new-web-tab-requested", g, "")

            web_btn.connect("clicked", _on_web)
        box.append(web_btn)

        pop.set_child(box)
        pop.set_parent(anchor)
        pop.popup()

    def _add_drop_sentinel(self, group: Group) -> None:
        sentinel = Gtk.Box()
        sentinel.set_size_request(-1, 6)
        self._attach_drop(sentinel, group, lambda g=group: len(g.tabs))
        self._box.append(sentinel)

    def _add_project_end_sentinel(self) -> None:
        sentinel = Gtk.Box()
        sentinel.set_size_request(-1, 6)
        self._attach_project_drop(sentinel, lambda: len(self._ws.active_projects))
        self._box.append(sentinel)

    # --- row builders ---

    def _add_project_row(self, project: Project, active_index: int) -> None:
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

        flash = Gtk.MenuButton()
        flash.set_icon_name("thunderbolt-symbolic")
        flash.add_css_class("flat")
        flash.set_tooltip_text("Flash commands")
        flash.set_sensitive(bool(project.flash_commands))
        flash.set_popover(self._build_flash_popover(project))

        cog = Gtk.Button.new_from_icon_name("emblem-system-symbolic")
        cog.add_css_class("flat")
        cog.set_tooltip_text("Settings")
        cog.connect(
            "clicked",
            lambda _b, p=project: self.emit("configure-project-requested", p),
        )

        plus = Gtk.Button.new_from_icon_name("list-add-symbolic")
        plus.add_css_class("flat")
        plus.set_tooltip_text("New tab (right-click for web tab)")
        plus.connect("clicked", lambda _b, p=project: self.emit("new-tab-requested", p))
        self._attach_plus_right_click(plus, project)

        for w in (chevron, label_btn, play, flash, cog, plus):
            row.append(w)

        gesture = Gtk.GestureClick()
        gesture.set_button(Gdk.BUTTON_SECONDARY)
        gesture.connect(
            "pressed",
            lambda g, _n, x, y, p=project, r=row: self._show_project_context_menu(r, p, x, y),
        )
        row.add_controller(gesture)

        self._attach_project_drag(row, project)
        self._attach_project_drop(row, lambda i=active_index: i)

        self._box.append(row)

    def _show_project_context_menu(
        self, anchor: Gtk.Widget, project: Project, x: float, y: float
    ) -> None:
        pop = Gtk.Popover()
        pop.set_has_arrow(False)
        pop.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_margin_start(4)
        box.set_margin_end(4)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        def _item(label: str, signal: str) -> Gtk.Button:
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.set_halign(Gtk.Align.FILL)
            btn.set_hexpand(True)

            def _cb(_b):
                pop.popdown()
                self.emit(signal, project)

            btn.connect("clicked", _cb)
            return btn

        box.append(_item("Archive", "archive-project-requested"))
        box.append(_item("Delete", "delete-project-requested"))
        box.append(_item("Settings", "configure-project-requested"))

        pop.set_child(box)
        pop.set_parent(anchor)
        pop.popup()

    def _build_flash_popover(self, project: Project) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(4)
        box.set_margin_end(4)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        if not project.flash_commands:
            empty = Gtk.Label(label="(no flash commands)")
            empty.add_css_class("dim-label")
            box.append(empty)
        else:
            for fc in project.flash_commands:
                btn = Gtk.Button(label=fc.name)
                btn.add_css_class("flat")
                btn.set_halign(Gtk.Align.FILL)

                def _on_click(_b, p=project, c=fc, popover=pop):
                    popover.popdown()
                    self.emit("flash-command-launched", p, c)

                btn.connect("clicked", _on_click)
                box.append(btn)
        pop.set_child(box)
        return pop

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
        plus.set_tooltip_text("New tab (right-click for web tab)")
        plus.connect("clicked", lambda _b, g=group: self.emit("new-tab-requested", g))
        self._attach_plus_right_click(plus, group)

        for w in (chevron, label_btn, plus):
            row.append(w)
        self._box.append(row)

    def _add_archived_header(self) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_margin_start(4)
        row.set_margin_end(4)

        chevron = Gtk.Button.new_from_icon_name(
            "pan-down-symbolic" if self._ws.archived_expanded else "pan-end-symbolic"
        )
        chevron.add_css_class("flat")
        chevron.connect(
            "clicked",
            lambda _b: self.emit("toggle-archived-expanded-requested"),
        )

        label_btn = Gtk.Button(label="Archived")
        label_btn.add_css_class("flat")
        label_btn.set_hexpand(True)
        label_btn.set_halign(Gtk.Align.START)
        label_btn.connect(
            "clicked",
            lambda _b: self.emit("toggle-archived-expanded-requested"),
        )

        for w in (chevron, label_btn):
            row.append(w)
        self._box.append(row)

    def _add_archived_row(self, project: Project) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_margin_start(20)
        row.set_margin_end(4)

        from gi.repository import Pango

        name_label = Gtk.Label(label=project.name, xalign=0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.set_max_width_chars(24)
        name_label.set_hexpand(True)

        unarchive = Gtk.Button.new_from_icon_name("view-restore-symbolic")
        unarchive.add_css_class("flat")
        unarchive.set_tooltip_text("Unarchive project")
        unarchive.connect(
            "clicked",
            lambda _b, p=project: self.emit("unarchive-project-requested", p),
        )

        row.append(name_label)
        row.append(unarchive)
        self._box.append(row)

    def _add_tab_row(self, group: Group, tab: Tab) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_margin_start(20)
        row.set_margin_end(4)
        if tab is self._active_tab:
            row.add_css_class("jfterm-active-tab")

        dot: StatusDot | None = None
        if isinstance(tab, TerminalTab):
            dot = StatusDot()
            dot.set_valign(Gtk.Align.CENTER)
            if isinstance(group, Project):
                filled = is_inside(tab.current_cwd, group.directory)
            else:
                filled = not matching_projects(tab.current_cwd, self._ws.projects)
            dot.set_state(running=tab.is_running, filled=filled)
            tab._dot = dot
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

        title_overlay = Gtk.Overlay()
        title_overlay.set_hexpand(True)
        title_overlay.set_child(title)
        progress_bar = TabProgressBar()
        title_overlay.add_overlay(progress_bar)
        tab._progress_bar = progress_bar  # type: ignore[attr-defined]  # runtime back-ref, like _dot

        restart = None
        if isinstance(tab, TerminalTab) and tab.launched_command:
            restart = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
            restart.add_css_class("flat")
            restart.set_tooltip_text("Restart command")
            restart.connect(
                "clicked",
                lambda _b, t=tab: self.emit("restart-tab-requested", t),
            )

        close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close.add_css_class("flat")
        close.set_tooltip_text("Close tab")
        close.connect("clicked", lambda _b, t=tab: self.emit("close-tab-requested", t))

        # DnD: the row is both a drag source (carrying the tab) and a drop
        # target (drop above this row, taking this row's index).
        position_in_group = group.tabs.index(tab)
        self._attach_drag(row, tab)
        self._attach_drop(row, group, lambda pos=position_in_group: pos)

        widgets: list[Gtk.Widget] = []
        if dot is not None:
            widgets.append(dot)
        else:
            spacer = Gtk.Box()
            spacer.set_size_request(12, -1)  # match StatusDot width (see status_dot.py)
            widgets.append(spacer)
        widgets.append(title_overlay)
        if restart is not None:
            widgets.append(restart)
        widgets.append(close)
        for w in widgets:
            row.append(w)
        self._box.append(row)
