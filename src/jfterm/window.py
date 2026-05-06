from __future__ import annotations

from gi.repository import Adw, Gtk

from jfterm.models import Group, Project, Tab, Workspace
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
        self.terminal_stack.add_named(
            self._group_empty_label, "__empty_group__"
        )

        self.terminal_stack.set_visible_child_name("__empty_global__")
        # The "current group" is the group whose context the right pane is
        # showing. None at startup; set when the user picks/creates a tab or
        # opens a per-group empty state.
        self._current_group: Group | None = None

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_start_child(self.sidebar)
        paned.set_end_child(self.terminal_stack)
        paned.set_shrink_start_child(False)
        paned.set_position(220)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(paned)
        self.set_content(toolbar)

        # Wire sidebar signals
        self.sidebar.connect("tab-activated", self._on_tab_activated)
        self.sidebar.connect("new-tab-requested", self._on_new_tab)
        self.sidebar.connect("close-tab-requested", self._on_close_tab)
        self.sidebar.connect("new-project-requested", self._on_new_project)
        self.sidebar.connect(
            "configure-project-requested", self._on_configure_project
        )
        self.sidebar.connect("toggle-expanded-requested", self._on_toggle_expanded)

    # --- handlers ---

    def _on_tab_activated(self, _sb, tab: Tab) -> None:
        if tab.terminal is not None:
            self._current_group = self.ws._find_group(tab)
            self.terminal_stack.set_visible_child(tab.terminal)

    def _on_new_tab(self, _sb, group: Group) -> None:
        cwd = group.directory if isinstance(group, Project) else None
        terminal = JFTermTerminal(cwd=cwd)
        terminal.set_vexpand(True)
        terminal.set_hexpand(True)
        tab = Tab(title="(starting…)", terminal=terminal)
        self.terminal_stack.add_child(terminal)
        group.add_tab(tab)
        self._current_group = group
        self.sidebar.refresh()
        self.terminal_stack.set_visible_child(terminal)

    def _on_close_tab(self, _sb, tab: Tab) -> None:
        group = self.ws._find_group(tab)
        was_visible = (
            tab.terminal is not None
            and self.terminal_stack.get_visible_child() is tab.terminal
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
            self.terminal_stack.set_visible_child(group.tabs[new_idx].terminal)
        else:
            self._show_group_empty(group)

    def _on_new_project(self, _sb) -> None:
        from jfterm.dialogs import show_project_dialog

        def _save(name: str, directory: str) -> None:
            self.ws.add_project(name=name, directory=directory)
            save_projects(self.ws, default_path())
            self.sidebar.refresh()

        show_project_dialog(self, title="New project", on_save=_save)

    def _on_configure_project(self, _sb, project: Project) -> None:
        from jfterm.dialogs import show_project_dialog

        def _save(name: str, directory: str) -> None:
            project.name = name
            project.directory = directory
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
            on_save=_save,
            on_disband=_disband,
        )

    def _on_toggle_expanded(self, _sb, project: Project) -> None:
        project.expanded = not project.expanded
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    # --- helpers ---

    def _show_group_empty(self, group: Group) -> None:
        if isinstance(group, Project):
            self._group_empty_label.set_text(
                f"Project {group.name} has no tabs."
            )
        else:
            self._group_empty_label.set_text("Unsorted has no tabs.")
        self._current_group = group
        self.terminal_stack.set_visible_child_name("__empty_group__")
