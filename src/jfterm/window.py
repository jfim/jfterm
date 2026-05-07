from __future__ import annotations

import contextlib
import os
import signal

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from jfterm.flash import wrap_flash_command  # noqa: E402
from jfterm.models import FlashCommand, Group, Project, StartupCommand, Tab, Workspace  # noqa: E402
from jfterm.persistence import default_path, load_projects, save_projects  # noqa: E402
from jfterm.sidebar import Sidebar  # noqa: E402
from jfterm.terminal import JFTermTerminal  # noqa: E402


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
        header = Adw.HeaderBar()
        self._sidebar_toggle = Gtk.ToggleButton()
        self._sidebar_toggle.set_icon_name("sidebar-show-symbolic")
        self._sidebar_toggle.set_tooltip_text("Hide sidebar")
        self._sidebar_toggle.set_active(True)
        self._sidebar_toggle.connect("toggled", self._on_sidebar_toggled)
        header.pack_start(self._sidebar_toggle)
        toolbar.add_top_bar(header)
        toolbar.set_content(paned)
        self.set_content(toolbar)

        # Wire sidebar signals
        self.sidebar.connect("tab-activated", self._on_tab_activated)
        self.sidebar.connect("new-tab-requested", self._on_new_tab)
        self.sidebar.connect("close-tab-requested", self._on_close_tab)
        self.sidebar.connect("restart-tab-requested", self._on_restart_tab)
        self.sidebar.connect("new-project-requested", self._on_new_project)
        self.sidebar.connect("configure-project-requested", self._on_configure_project)
        self.sidebar.connect("archive-project-requested", self._on_archive_project)
        self.sidebar.connect("delete-project-requested", self._on_delete_project)
        self.sidebar.connect("launch-project-requested", self._on_launch_project)
        self.sidebar.connect("flash-command-launched", self._on_flash_command_launched)
        self.sidebar.connect("toggle-expanded-requested", self._on_toggle_expanded)
        self.sidebar.connect("dot-clicked", self._on_dot_clicked)
        self.sidebar.connect("tab-dropped", self._on_tab_dropped)
        self.sidebar.connect("unarchive-project-requested", self._on_unarchive_project)
        self.sidebar.connect(
            "toggle-archived-expanded-requested", self._on_toggle_archived_expanded
        )

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
            self.sidebar.set_active_tab(tab)
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
        tab = Tab(
            title=command or "(starting…)",
            terminal=terminal,
            launched_command=command,
        )
        self._wire_terminal(tab, terminal)
        self.terminal_stack.add_child(terminal)
        group.add_tab(tab)
        self._current_group = group
        if focus:
            self.terminal_stack.set_visible_child(terminal)
            self.sidebar.set_active_tab(tab)
            terminal.grab_focus()
        self.sidebar.refresh()
        return tab

    def _wire_terminal(self, tab: Tab, terminal: JFTermTerminal) -> None:
        # Each handler only acts when the signal comes from the tab's CURRENT
        # terminal. After a restart the old terminal lingers long enough to
        # emit child-exited (and possibly other signals) asynchronously; those
        # must not mutate the tab that now owns a fresh terminal.
        terminal.connect(
            "cwd-changed",
            lambda _t, path, t=tab, term=terminal: (
                self._on_tab_cwd_changed(t, path) if t.terminal is term else None
            ),
        )
        terminal.connect(
            "running-changed",
            lambda _t, running, t=tab, term=terminal: (
                self._on_tab_running_changed(t, running) if t.terminal is term else None
            ),
        )
        terminal.connect(
            "title-changed",
            lambda _t, title, t=tab, term=terminal: (
                self._on_tab_title_changed(t, title) if t.terminal is term else None
            ),
        )
        terminal.connect(
            "child-exited",
            lambda _t, _status, t=tab, term=terminal: (
                self._on_close_tab(self.sidebar, t) if t.terminal is term else None
            ),
        )
        terminal.connect(
            "progress-changed",
            lambda _t, state, value, t=tab, term=terminal: (
                self._on_tab_progress(t, state, value) if t.terminal is term else None
            ),
        )

    def _on_close_tab(self, _sb, tab: Tab) -> None:
        if tab.is_restarting:
            return
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
            self.sidebar.set_active_tab(promoted)
            if promoted.terminal is not None:
                promoted.terminal.grab_focus()
        else:
            self._show_group_empty(group)

    def _on_restart_tab(self, _sb, tab: Tab) -> None:
        if not tab.launched_command:
            return
        from gi.repository import GLib

        group = self.ws._find_group(tab)
        cwd = group.directory if isinstance(group, Project) else None
        command = tab.launched_command
        was_visible = (
            tab.terminal is not None and self.terminal_stack.get_visible_child() is tab.terminal
        )
        old_terminal = tab.terminal
        old_pid = old_terminal.shell_pid if old_terminal is not None else None

        # Block the old terminal's child-exited from closing the tab.
        tab.is_restarting = True

        # SIGTERM now; SIGKILL after grace period if still alive.
        if old_pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(old_pid, signal.SIGTERM)

            def _force_kill(pid: int = old_pid) -> bool:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return False
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
                return False

            GLib.timeout_add(1500, _force_kill)

        # Swap in a fresh terminal for the same tab.
        if old_terminal is not None:
            old_terminal._proxy.close()  # break GLib closure ref before GTK dispose
            self.terminal_stack.remove(old_terminal)

        new_terminal = JFTermTerminal(cwd=cwd, send_after_spawn=command)
        new_terminal.set_vexpand(True)
        new_terminal.set_hexpand(True)

        tab.terminal = new_terminal
        tab.shell_pid = None
        tab.pty_fd = None
        tab.is_running = False
        tab.osc133_seen = False
        tab.title = f"▶ {command}" if tab.from_startup else command

        self._wire_terminal(tab, new_terminal)
        self.terminal_stack.add_child(new_terminal)

        # The flag has done its job — the new terminal's child-exited should
        # close the tab normally.
        tab.is_restarting = False

        if was_visible:
            self.terminal_stack.set_visible_child(new_terminal)
            new_terminal.grab_focus()

        self.sidebar.refresh()

    def _on_new_project(self, _sb) -> None:
        from jfterm.dialogs import show_project_dialog

        def _save(
            name: str,
            directory: str,
            commands: list[StartupCommand],
            spawn_blank_after_startup: bool,
            flash_commands: list[FlashCommand],
        ) -> None:
            p = self.ws.add_project(name=name, directory=directory)
            p.startup_commands = commands
            p.spawn_blank_after_startup = spawn_blank_after_startup
            p.flash_commands = flash_commands
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
            flash_commands: list[FlashCommand],
        ) -> None:
            project.name = name
            project.directory = directory
            project.startup_commands = commands
            project.spawn_blank_after_startup = spawn_blank_after_startup
            project.flash_commands = flash_commands
            save_projects(self.ws, default_path())
            self.sidebar.refresh()

        def _disband() -> None:
            self._delete_project(project)

        def _archive() -> None:
            self._archive_project(project)

        show_project_dialog(
            self,
            title=f"Configure {project.name}",
            initial_name=project.name,
            initial_directory=project.directory,
            initial_commands=project.startup_commands,
            initial_spawn_blank_after_startup=project.spawn_blank_after_startup,
            initial_flash_commands=project.flash_commands,
            on_save=_save,
            on_disband=_disband,
            on_archive=_archive,
            n_open_tabs=len(project.tabs),
        )

    def _on_archive_project(self, _sb, project: Project) -> None:
        n = len(project.tabs)
        if n <= 0:
            self._archive_project(project)
            return
        confirm = Adw.MessageDialog(
            transient_for=self,
            modal=True,
            heading=f"Archive {project.name}?",
            body=f"This will close {n} tab{'s' if n != 1 else ''}.",
        )
        confirm.add_response("cancel", "Cancel")
        confirm.add_response("archive", "Archive")
        confirm.set_response_appearance("archive", Adw.ResponseAppearance.DESTRUCTIVE)
        confirm.set_default_response("cancel")
        confirm.set_close_response("cancel")

        def _on_response(_d, response):
            if response == "archive":
                self._archive_project(project)

        confirm.connect("response", _on_response)
        confirm.present()

    def _on_delete_project(self, _sb, project: Project) -> None:
        self._delete_project(project)

    def _delete_project(self, project: Project) -> None:
        self.ws.disband(project)
        if self._current_group is project:
            self._current_group = self.ws.unsorted
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    def _archive_project(self, project: Project) -> None:
        # Close every tab via the standard close path so child processes
        # terminate cleanly. Iterate over a copy because _on_close_tab
        # mutates project.tabs.
        for tab in list(project.tabs):
            self._on_close_tab(self.sidebar, tab)
        project.archived = True
        if self._current_group is project:
            self._current_group = self.ws.unsorted
            self.terminal_stack.set_visible_child_name("__empty_global__")
            self.sidebar.set_active_tab(None)
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    def _on_unarchive_project(self, _sb, project: Project) -> None:
        project.archived = False
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    def _on_toggle_archived_expanded(self, _sb) -> None:
        self.ws.archived_expanded = not self.ws.archived_expanded
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    def _on_launch_project(self, _sb, project: Project) -> None:
        if not project.startup_commands:
            return
        if not project.expanded:
            project.expanded = True
            save_projects(self.ws, default_path())
            self.sidebar.refresh()
        from gi.repository import GLib

        running = {t.launched_command for t in project.tabs if t.launched_command}
        cmds = [sc for sc in project.startup_commands if sc.command not in running]
        spawn_blank = project.spawn_blank_after_startup

        def _step(idx: int) -> bool:
            if idx >= len(cmds):
                if spawn_blank:
                    self._spawn_tab(project, focus=True)
                return False  # remove timeout
            sc = cmds[idx]
            is_last = idx == len(cmds) - 1
            focus = sc.delay > 0 or (is_last and not spawn_blank)
            tab = self._spawn_tab(project, command=sc.command, focus=focus)
            tab.from_startup = True
            tab.title = f"▶ {sc.command}"
            if idx + 1 < len(cmds) or spawn_blank:
                if sc.delay > 0:
                    GLib.timeout_add_seconds(sc.delay, _step, idx + 1)
                else:
                    GLib.idle_add(_step, idx + 1)
            return False

        _step(0)

    def _on_flash_command_launched(self, _sb, project: Project, fc: FlashCommand) -> None:
        if not project.expanded:
            project.expanded = True
            save_projects(self.ws, default_path())
            self.sidebar.refresh()
        wrapped = wrap_flash_command(fc)
        tab = self._spawn_tab(project, command=wrapped, focus=fc.focus_on_launch)
        tab.flash_name = fc.name
        tab.title = f"⚡ {fc.name}"
        self.sidebar.refresh()

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
        if not running:
            self._clear_tab_progress(tab)
        self._refresh_tab_dot(tab)

    def _on_tab_progress(self, tab: Tab, state: int, value: int) -> None:
        bar = getattr(tab, "_progress_bar", None)
        if bar is not None:
            bar.set_progress(state, value)

    def _clear_tab_progress(self, tab: Tab) -> None:
        bar = getattr(tab, "_progress_bar", None)
        if bar is not None:
            bar.set_progress(0, 0)

    def _on_tab_title_changed(self, tab: Tab, title: str) -> None:
        if tab.flash_name is not None:
            tab.title = f"⚡ {tab.flash_name}: {title}" if title else f"⚡ {tab.flash_name}"
        elif tab.from_startup:
            base = title or tab.launched_command or "tab"
            tab.title = f"▶ {base}"
        else:
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
            self.sidebar.set_active_tab(nxt)
            nxt.terminal.grab_focus()

    def _on_sidebar_toggled(self, btn: Gtk.ToggleButton) -> None:
        visible = btn.get_active()
        self.sidebar.set_visible(visible)
        btn.set_tooltip_text("Hide sidebar" if visible else "Show sidebar")

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
        self.sidebar.set_active_tab(None)
