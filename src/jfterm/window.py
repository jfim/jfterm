from __future__ import annotations

from gi.repository import Adw, Gtk

from jfterm.models import Group, Project, StartupCommand, Tab, Workspace
from jfterm.persistence import default_path, load_projects, save_projects
from jfterm.sidebar import Sidebar
from jfterm.terminal import JFTermTerminal


class JFTermWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="JFTerm")
        self.set_default_size(1100, 700)

        self.ws = Workspace()
        load_projects(self.ws, default_path())

        self.sidebar = Sidebar(self.ws)
        self.terminal_stack = Gtk.Stack()
        self.terminal_stack.set_vexpand(True)
        self.terminal_stack.set_hexpand(True)

        empty = Gtk.Label(label="No tabs — click + to create one")
        empty.set_vexpand(True)
        empty.set_hexpand(True)
        self.terminal_stack.add_named(empty, "__empty_global__")

        # Reused per-group empty panel; label updated each time it's shown.
        self._group_empty_label = Gtk.Label()
        self._group_empty_label.set_vexpand(True)
        self._group_empty_label.set_hexpand(True)
        self.terminal_stack.add_named(self._group_empty_label, "__empty_group__")

        self.terminal_stack.set_visible_child_name("__empty_global__")
        # The "current group" is the group whose context the right pane is
        # showing. None at startup; set when the user picks/creates a tab or
        # opens a per-group empty state.
        self._current_group: Group | None = None

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_start_child(self.sidebar)
        paned.set_end_child(self.terminal_stack)
        paned.set_shrink_start_child(False)
        paned.set_position(self.ws.sidebar_width)
        # Persist width on drag, debounced so we don't write on every pixel.
        self._paned = paned
        self._sidebar_save_source: int | None = None
        paned.connect("notify::position", self._on_paned_position_changed)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(paned)
        self.set_content(toolbar)

        # Wire sidebar signals
        self.sidebar.connect("tab-activated", self._on_tab_activated)
        self.sidebar.connect("new-tab-requested", self._on_new_tab)
        self.sidebar.connect("close-tab-requested", self._on_close_tab)
        self.sidebar.connect("new-project-requested", self._on_new_project)
        self.sidebar.connect("configure-project-requested", self._on_configure_project)
        self.sidebar.connect("launch-project-requested", self._on_launch_project)
        self.sidebar.connect("toggle-expanded-requested", self._on_toggle_expanded)
        self.sidebar.connect("dot-clicked", self._on_dot_clicked)
        self.sidebar.connect("tab-dropped", self._on_tab_dropped)

        # Keyboard shortcuts
        from jfterm.shortcuts import install as install_shortcuts

        install_shortcuts(
            self,
            actions={
                "win.new-tab": self._shortcut_new_tab,
                "win.close-tab": self._shortcut_close_tab,
                "win.next-tab": self._shortcut_next_tab,
                "win.prev-tab": self._shortcut_prev_tab,
            },
        )
        app = self.get_application()
        if app is not None:
            app.set_accels_for_action("win.new-tab", ["<Control><Shift>t"])
            app.set_accels_for_action("win.close-tab", ["<Control><Shift>w"])
            app.set_accels_for_action("win.next-tab", ["<Control>Page_Down"])
            app.set_accels_for_action("win.prev-tab", ["<Control>Page_Up"])

    # --- handlers ---

    def _on_tab_activated(self, _sb, tab: Tab) -> None:
        if tab.terminal is not None:
            self._current_group = self.ws._find_group(tab)
            self.terminal_stack.set_visible_child(tab.terminal)
            tab.terminal.grab_focus()

    def _on_new_tab(self, _sb, group: Group) -> None:
        self._spawn_tab(group)

    def _spawn_tab(
        self,
        group: Group,
        *,
        command: str | None = None,
        focus: bool = True,
    ) -> Tab:
        cwd = group.directory if isinstance(group, Project) else None
        terminal = JFTermTerminal(cwd=cwd, send_after_spawn=command)
        terminal.set_vexpand(True)
        terminal.set_hexpand(True)
        tab = Tab(title=command or "(starting…)", terminal=terminal)
        terminal.connect(
            "cwd-changed",
            lambda _t, path, t=tab: self._on_tab_cwd_changed(t, path),
        )
        terminal.connect(
            "running-changed",
            lambda _t, running, t=tab: self._on_tab_running_changed(t, running),
        )
        terminal.connect(
            "title-changed",
            lambda _t, title, t=tab: self._on_tab_title_changed(t, title),
        )
        terminal.connect(
            "child-exited",
            lambda _t, _status, t=tab: self._on_close_tab(self.sidebar, t),
        )
        self.terminal_stack.add_child(terminal)
        group.add_tab(tab)
        self._current_group = group
        self.sidebar.refresh()
        if focus:
            self.terminal_stack.set_visible_child(terminal)
            terminal.grab_focus()
        return tab

    def _on_close_tab(self, _sb, tab: Tab) -> None:
        group = self.ws._find_group(tab)
        was_visible = (
            tab.terminal is not None and self.terminal_stack.get_visible_child() is tab.terminal
        )
        # Capture next-tab-in-group BEFORE removing.
        idx = group.tabs.index(tab)
        group.remove_tab(tab)
        if tab.terminal is not None:
            self.terminal_stack.remove(tab.terminal)
        self.sidebar.refresh()

        if not was_visible:
            return

        # Selection priority within the same group only:
        #   1. Tab that took the closed tab's slot (now at index `idx`).
        #   2. New last tab (index `idx - 1`) if `idx` is past the end.
        #   3. Per-group empty state if the group is empty.
        if group.tabs:
            new_idx = min(idx, len(group.tabs) - 1)
            self._current_group = group
            promoted = group.tabs[new_idx]
            self.terminal_stack.set_visible_child(promoted.terminal)
            if promoted.terminal is not None:
                promoted.terminal.grab_focus()
        else:
            self._show_group_empty(group)

    def _on_new_project(self, _sb) -> None:
        from jfterm.dialogs import show_project_dialog

        def _save(
            name: str,
            directory: str,
            commands: list[StartupCommand],
            spawn_blank_after_startup: bool,
        ) -> None:
            p = self.ws.add_project(name=name, directory=directory)
            p.startup_commands = commands
            p.spawn_blank_after_startup = spawn_blank_after_startup
            save_projects(self.ws, default_path())
            self.sidebar.refresh()

        show_project_dialog(self, title="New project", on_save=_save)

    def _on_configure_project(self, _sb, project: Project) -> None:
        from jfterm.dialogs import show_project_dialog

        def _save(
            name: str,
            directory: str,
            commands: list[StartupCommand],
            spawn_blank_after_startup: bool,
        ) -> None:
            project.name = name
            project.directory = directory
            project.startup_commands = commands
            project.spawn_blank_after_startup = spawn_blank_after_startup
            save_projects(self.ws, default_path())
            self.sidebar.refresh()

        def _disband() -> None:
            self.ws.disband(project)
            if self._current_group is project:
                self._current_group = self.ws.unsorted
            save_projects(self.ws, default_path())
            self.sidebar.refresh()

        show_project_dialog(
            self,
            title=f"Configure {project.name}",
            initial_name=project.name,
            initial_directory=project.directory,
            initial_commands=project.startup_commands,
            initial_spawn_blank_after_startup=project.spawn_blank_after_startup,
            on_save=_save,
            on_disband=_disband,
        )

    def _on_launch_project(self, _sb, project: Project) -> None:
        if not project.startup_commands:
            return
        from gi.repository import GLib

        cmds = list(project.startup_commands)
        spawn_blank = project.spawn_blank_after_startup

        def _step(idx: int) -> bool:
            if idx >= len(cmds):
                if spawn_blank:
                    self._spawn_tab(project, focus=True)
                return False  # remove timeout
            sc = cmds[idx]
            self._spawn_tab(project, command=sc.command, focus=(idx == 0))
            if idx + 1 < len(cmds) or spawn_blank:
                if sc.delay > 0:
                    GLib.timeout_add_seconds(sc.delay, _step, idx + 1)
                else:
                    GLib.idle_add(_step, idx + 1)
            return False

        _step(0)

    def _on_toggle_expanded(self, _sb, group: Group) -> None:
        group.expanded = not group.expanded
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    def _on_dot_clicked(self, _sb, tab: Tab, current_group: Group, anchor) -> None:
        from jfterm.menus import build_move_to_popover

        def _move(dest: Group) -> None:
            self.ws.move_tab(tab, dest)
            if tab.terminal is not None and self.terminal_stack.get_visible_child() is tab.terminal:
                self._current_group = dest
            self._refresh_tab_dot(tab)
            self.sidebar.refresh()

        pop = build_move_to_popover(self.ws, tab, current_group, on_move=_move)
        pop.set_parent(anchor)
        pop.popup()

    def _on_tab_dropped(self, _sb, tab: Tab, dest_group: Group, position: int) -> None:
        # Within-group + drop below source: removing first shifts indices.
        src_group = self.ws._find_group(tab)
        adjusted = position
        if src_group is dest_group:
            src_idx = src_group.tabs.index(tab)
            if src_idx < position:
                adjusted -= 1
        self.ws.move_tab(tab, dest_group, position=adjusted)
        if tab.terminal is not None and self.terminal_stack.get_visible_child() is tab.terminal:
            self._current_group = dest_group
        self._refresh_tab_dot(tab)
        self.sidebar.refresh()

    def _on_tab_cwd_changed(self, tab: Tab, path: str) -> None:
        tab.current_cwd = path
        self._refresh_tab_dot(tab)

    def _on_tab_running_changed(self, tab: Tab, running: bool) -> None:
        if tab.is_running == running:
            return
        tab.is_running = running
        self._refresh_tab_dot(tab)

    def _on_tab_title_changed(self, tab: Tab, title: str) -> None:
        tab.title = title
        self.sidebar.refresh()

    # --- helpers ---

    def _refresh_tab_dot(self, tab: Tab) -> None:
        from jfterm.matching import is_inside, matching_projects

        try:
            group = self.ws._find_group(tab)
        except ValueError:
            return
        if isinstance(group, Project):
            filled = is_inside(tab.current_cwd, group.directory)
        else:
            filled = not matching_projects(tab.current_cwd, self.ws.projects)
        if hasattr(tab, "_dot") and tab._dot is not None:
            tab._dot.set_state(running=tab.is_running, filled=filled)

    # --- shortcut handlers ---

    def _shortcut_new_tab(self) -> None:
        cur = self._current_tab()
        group = self.ws._find_group(cur) if cur is not None else self.ws.unsorted
        self._on_new_tab(self.sidebar, group)

    def _shortcut_close_tab(self) -> None:
        t = self._current_tab()
        if t is not None:
            self._on_close_tab(self.sidebar, t)

    def _shortcut_next_tab(self) -> None:
        self._cycle_tab(+1)

    def _shortcut_prev_tab(self) -> None:
        self._cycle_tab(-1)

    def _current_tab(self) -> Tab | None:
        visible = self.terminal_stack.get_visible_child()
        for g in self.ws.all_groups():
            for t in g.tabs:
                if t.terminal is visible:
                    return t
        return None

    def _cycle_tab(self, delta: int) -> None:
        flat = [t for g in self.ws.all_groups() for t in g.tabs]
        if not flat:
            return
        cur = self._current_tab()
        idx = flat.index(cur) if cur in flat else -1
        nxt = flat[(idx + delta) % len(flat)]
        if nxt.terminal is not None:
            self._current_group = self.ws._find_group(nxt)
            self.terminal_stack.set_visible_child(nxt.terminal)
            nxt.terminal.grab_focus()

    def _on_paned_position_changed(self, _paned, _pspec) -> None:
        from gi.repository import GLib

        self.ws.sidebar_width = self._paned.get_position()
        if self._sidebar_save_source is not None:
            GLib.source_remove(self._sidebar_save_source)

        def _flush() -> bool:
            save_projects(self.ws, default_path())
            self._sidebar_save_source = None
            return False

        # 500ms after the user stops dragging, write to disk.
        self._sidebar_save_source = GLib.timeout_add(500, _flush)

    def _show_group_empty(self, group: Group) -> None:
        if isinstance(group, Project):
            self._group_empty_label.set_text(f"Project {group.name} has no tabs.")
        else:
            self._group_empty_label.set_text("Unsorted has no tabs.")
        self._current_group = group
        self.terminal_stack.set_visible_child_name("__empty_group__")
