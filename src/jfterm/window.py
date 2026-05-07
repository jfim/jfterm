from __future__ import annotations

import contextlib
import os
import signal
import sys
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402, I001

from jfterm.flash import wrap_flash_command  # noqa: E402
from jfterm.models import (  # noqa: E402
    FlashCommand,
    Group,
    LinkedTab,
    Project,
    StartupCommand,
    Tab,
    TerminalTab,
    WebTab,
    Workspace,
)
from jfterm.persistence import default_path, load_projects, save_projects  # noqa: E402
from jfterm.preferences import AppPreferencesDialog  # noqa: E402
from jfterm.settings import (  # noqa: E402
    AppSettings,
    default_path as default_settings_path,
    load as load_settings,
    save as save_settings,
)
from jfterm.sidebar import Sidebar  # noqa: E402
from jfterm.terminal import JFTermTerminal  # noqa: E402

if TYPE_CHECKING:
    from jfterm.mcp_types import ProjectInfo, TabInfo


class JFTermWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="JFTerm")

        self.ws = Workspace()
        load_projects(self.ws, default_path())

        self._settings_path = default_settings_path()
        self._settings: AppSettings = load_settings(self._settings_path)

        self.set_default_size(self._settings.window_width, self._settings.window_height)
        if self._settings.window_maximized:
            self.maximize()
        self._window_save_source: int | None = None
        self.connect("notify::default-width", self._on_window_geometry_changed)
        self.connect("notify::default-height", self._on_window_geometry_changed)
        self.connect("notify::maximized", self._on_window_geometry_changed)
        self.connect("close-request", self._on_close_request)

        self.sidebar = Sidebar(self.ws)
        self.terminal_stack = Gtk.Stack()
        self.terminal_stack.set_vexpand(True)
        self.terminal_stack.set_hexpand(True)

        # The "current group" is the group whose context the right pane is
        # showing. None at startup; set when the user picks/creates a tab or
        # opens a per-group empty state.
        self._current_group: Group | None = None
        self._empty_state = self._build_empty_state()
        self.terminal_stack.add_named(self._empty_state, "__empty__")
        self.terminal_stack.set_visible_child_name("__empty__")

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_start_child(self.sidebar)
        paned.set_end_child(self.terminal_stack)
        paned.set_shrink_start_child(False)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
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

        # Hamburger menu (right end of header bar).
        menu = Gio.Menu()
        menu.append("New project", "win.new-project")
        menu.append("Preferences", "win.preferences")
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_tooltip_text("Main menu")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)

        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", self._on_preferences)
        self.add_action(prefs_action)

        new_project_action = Gio.SimpleAction.new("new-project", None)
        new_project_action.connect("activate", lambda _a, _p: self._on_new_project())
        self.add_action(new_project_action)

        toolbar.add_top_bar(header)
        toolbar.set_content(paned)
        self.set_content(toolbar)

        # Wire sidebar signals
        self.sidebar.connect("tab-activated", self._on_tab_activated)
        self.sidebar.connect("new-tab-requested", self._on_new_tab)
        self.sidebar.connect("new-web-tab-requested", self._on_new_web_tab)
        self.sidebar.connect("close-tab-requested", self._on_close_tab)
        self.sidebar.connect("restart-tab-requested", self._on_restart_tab)
        self.sidebar.connect("configure-project-requested", self._on_configure_project)
        self.sidebar.connect("archive-project-requested", self._on_archive_project)
        self.sidebar.connect("delete-project-requested", self._on_delete_project)
        self.sidebar.connect("launch-project-requested", self._on_launch_project)
        self.sidebar.connect("flash-command-launched", self._on_flash_command_launched)
        self.sidebar.connect("toggle-expanded-requested", self._on_toggle_expanded)
        self.sidebar.connect("dot-clicked", self._on_dot_clicked)
        self.sidebar.connect("tab-dropped", self._on_tab_dropped)
        self.sidebar.connect("project-dropped", self._on_project_dropped)
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

        # Embedded MCP server. See docs/superpowers/specs/2026-05-06-mcp-server-design.md.
        # Host/port/enabled are read from AppSettings; changes apply on next launch.
        self._mcp_controller = None
        self._mcp_server = None
        if self._settings.mcp_enabled:
            from jfterm.mcp_gtk import GtkMCPController
            from jfterm.mcp_server import MCPServerThread

            self._mcp_controller = GtkMCPController(self)
            self._mcp_server = MCPServerThread(
                self._mcp_controller,
                host=self._settings.mcp_host,
                port=self._settings.mcp_port,
            )
            self._mcp_server.start()

        # Command launcher (issue #19)
        from jfterm.double_tap import DoubleTapDetector
        from jfterm.launcher import Launcher

        self._launcher = Launcher(self, dispatch=self._dispatch_launcher_action)
        self._double_shift = DoubleTapDetector(
            target_keyval=Gdk.KEY_Shift_L,
            interval_ms=300,
            callback=self._open_launcher,
        )
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", self._on_window_key_pressed)
        self.add_controller(key_ctrl)

    # --- handlers ---

    def _on_tab_activated(self, _sb, tab: Tab) -> None:
        if tab.widget is not None:
            self._current_group = self.ws._find_group(tab)
            self.terminal_stack.set_visible_child(tab.widget)
            self.sidebar.set_active_tab(tab)
            tab.widget.grab_focus()

    def _on_new_tab(self, _sb, group: Group) -> None:
        self._spawn_tab(group)

    def _spawn_tab(
        self,
        group: Group,
        *,
        command: str | None = None,
        focus: bool = True,
    ) -> TerminalTab:
        cwd = group.directory if isinstance(group, Project) else None
        terminal = JFTermTerminal(cwd=cwd, send_after_spawn=command, appearance=self._settings)
        terminal.set_vexpand(True)
        terminal.set_hexpand(True)
        tab = TerminalTab(
            title=command or "(starting…)",
            terminal=terminal,
            launched_command=command,
        )
        self._wire_terminal(tab, terminal)
        self.terminal_stack.add_child(terminal)
        group.add_tab(tab)
        if focus:
            self._current_group = group
            self.terminal_stack.set_visible_child(terminal)
            self.sidebar.set_active_tab(tab)
            terminal.grab_focus()
        self.sidebar.refresh()
        return tab

    def _wire_terminal(self, tab: TerminalTab, terminal: JFTermTerminal) -> None:
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

    def _on_new_web_tab(self, _sb, group: Group, url: str) -> None:
        if url:
            self._spawn_web_tab(group, url=url)
            return
        from jfterm.dialogs import show_new_web_tab_dialog

        def _confirm(submitted: str) -> None:
            self._spawn_web_tab(group, url=submitted)

        show_new_web_tab_dialog(self, on_confirm=_confirm)

    def _spawn_web_tab(
        self,
        group: Group,
        *,
        url: str,
        focus: bool = True,
        from_startup: bool = False,
        flash_name: str | None = None,
    ) -> WebTab:
        from jfterm.webtab import JFTermWebView

        web_view = JFTermWebView(url=url)
        web_view.set_vexpand(True)
        web_view.set_hexpand(True)

        if flash_name is not None:
            initial_title = f"⚡ {flash_name}"
        elif from_startup:
            initial_title = f"▶ {url}"
        else:
            initial_title = url
        tab = WebTab(
            title=initial_title,
            url=url,
            web_view=web_view,
            from_startup=from_startup,
            flash_name=flash_name,
        )
        self._wire_web_view(tab, web_view)
        self.terminal_stack.add_child(web_view)
        group.add_tab(tab)
        if focus:
            self._current_group = group
            self.terminal_stack.set_visible_child(web_view)
            self.sidebar.set_active_tab(tab)
            web_view.grab_focus()
        self.sidebar.refresh()
        return tab

    def _spawn_linked_tab(
        self,
        group: Group,
        *,
        spec,  # jfterm.linked.LinkedSpec
        flash_name: str,
        focus: bool = True,
    ) -> LinkedTab:
        from jfterm.linkedtab import JFTermLinkedView, is_available
        from jfterm.models import LinkedTab
        from jfterm.url_scanner import UrlScanner

        if not is_available():
            # Fall back to a plain terminal tab with a "WebKit missing" note.
            from jfterm.webtab import WEBKIT_PACKAGE

            fb = self._spawn_tab(
                group,
                command=f'echo "JFTerm: linked: needs {WEBKIT_PACKAGE}"',
                focus=focus,
            )
            fb.flash_name = flash_name
            fb.title = f"⚡ {flash_name}"
            return fb  # type: ignore[return-value]  # caller treats as best-effort

        cwd = group.directory if isinstance(group, Project) else None
        wrapped = wrap_flash_command(
            FlashCommand(name=flash_name, command=spec.command),
        )
        view = JFTermLinkedView(
            cwd=cwd,
            send_after_spawn=wrapped,
            appearance=self._settings,
            initial_url=spec.url,  # None means auto-detect
        )

        tab = LinkedTab(
            title=f"⚡ {flash_name}",
            terminal=view.terminal,
            web_view=view.web_view,
            paned=view,
            launched_command=spec.command,
            flash_name=flash_name,
            linked_url=spec.url,
        )

        # Wire terminal lifecycle signals — same handlers as TerminalTab
        # so dot/progress/title plumbing still works. We replace the
        # close-tab handler with a linked-tab-aware version that decides
        # whether to collapse the webview or close the whole tab.
        term = view.terminal
        term.connect(
            "cwd-changed",
            lambda _t, path, t=tab, x=term: (
                self._on_tab_cwd_changed(t, path) if t.terminal is x else None
            ),
        )
        term.connect(
            "running-changed",
            lambda _t, running, t=tab, x=term: (
                self._on_tab_running_changed(t, running) if t.terminal is x else None
            ),
        )
        term.connect(
            "title-changed",
            lambda _t, title, t=tab, x=term: (
                self._on_tab_title_changed(t, title) if t.terminal is x else None
            ),
        )
        term.connect(
            "progress-changed",
            lambda _t, state, value, t=tab, x=term: (
                self._on_tab_progress(t, state, value) if t.terminal is x else None
            ),
        )
        term.connect(
            "child-exited",
            lambda _t, status, t=tab, v=view, x=term: (
                self._on_linked_child_exited(t, v, status) if t.terminal is x else None
            ),
        )

        # auto-detect URL: scan terminal output for the first http(s) URL.
        if spec.url is None:
            scanner = UrlScanner()

            def _on_output(_t, data, sc=scanner, v=view, t=tab, x=term):
                if t.terminal is not x or t.linked_url is not None:
                    return
                sc.feed(data)
                found = sc.first_url()
                if found is not None:
                    t.linked_url = found
                    v.set_url(found)

            term.connect("output-data", _on_output)

        # Mount in the same stack used by terminal/web tabs.
        self.terminal_stack.add_child(view)
        group.add_tab(tab)
        if focus:
            self._current_group = group
            self.terminal_stack.set_visible_child(view)
            self.sidebar.set_active_tab(tab)
            view.grab_focus()
        self.sidebar.refresh()
        return tab

    def _on_linked_child_exited(self, tab, view, status: int) -> None:
        # Mirror wrap_flash_command's contract: on exit 0 the wrapper
        # ran `exit` itself, so close the whole tab. On non-zero, the
        # shell stays alive at a prompt — collapse the webview so the
        # error output fills the tab.
        if status == 0:
            self._on_close_tab(self.sidebar, tab)
        else:
            view.collapse_webview()

    def _wire_web_view(self, tab: WebTab, web_view: Any) -> None:
        web_view.connect(
            "title-changed",
            lambda _w, title, t=tab, wv=web_view: (
                self._on_web_tab_title_changed(t, title) if t.web_view is wv else None
            ),
        )
        web_view.connect(
            "url-changed",
            lambda _w, url, t=tab, wv=web_view: (
                self._on_web_tab_url_changed(t, url) if t.web_view is wv else None
            ),
        )
        web_view.connect(
            "progress-changed",
            lambda _w, state, value, t=tab, wv=web_view: (
                self._on_tab_progress(t, state, value) if t.web_view is wv else None
            ),
        )

    def _on_web_tab_title_changed(self, tab: WebTab, title: str) -> None:
        base = title or tab.url
        if tab.flash_name is not None:
            tab.title = f"⚡ {tab.flash_name}: {base}" if title else f"⚡ {tab.flash_name}"
        elif tab.from_startup:
            tab.title = f"▶ {base}"
        else:
            tab.title = base
        self.sidebar.refresh()

    def _on_web_tab_url_changed(self, tab: WebTab, url: str) -> None:
        if url:
            tab.url = url

    def _on_close_tab(self, _sb, tab: Tab) -> None:
        if isinstance(tab, TerminalTab) and tab.is_restarting:
            return
        group = self.ws._find_group(tab)
        was_visible = (
            tab.widget is not None and self.terminal_stack.get_visible_child() is tab.widget
        )
        # Capture next-tab-in-group BEFORE removing.
        idx = group.tabs.index(tab)
        # Eagerly send SIGHUP via the proxy so port-bound processes
        # release their sockets before the user re-spawns. Otherwise
        # cleanup runs only when Python GC + GTK dispose execute, which
        # can be many seconds after the tab visually disappears.
        terminal = getattr(tab, "terminal", None)
        if terminal is not None and terminal._proxy is not None:
            terminal._proxy.close()
        group.remove_tab(tab)
        if tab.widget is not None:
            self.terminal_stack.remove(tab.widget)
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
            self.sidebar.set_active_tab(promoted)
            if promoted.widget is not None:
                self.terminal_stack.set_visible_child(promoted.widget)
                promoted.widget.grab_focus()
        else:
            self._show_empty(group)

    def _on_restart_tab(self, _sb, tab: TerminalTab) -> None:
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

        new_terminal = JFTermTerminal(cwd=cwd, send_after_spawn=command, appearance=self._settings)
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

    def _on_new_project(self) -> None:
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
            self._refresh_empty_state()

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
            self._confirm_delete_project(project)

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
        self._confirm_delete_project(project)

    def _confirm_delete_project(self, project: Project) -> None:
        n = len(project.tabs)
        body = "This will permanently delete the project."
        if n > 0:
            body += f" {n} open tab{'s' if n != 1 else ''} will be moved to Unsorted."
        confirm = Adw.MessageDialog(
            transient_for=self,
            modal=True,
            heading=f"Delete {project.name}?",
            body=body,
        )
        confirm.add_response("cancel", "Cancel")
        confirm.add_response("delete", "Delete")
        confirm.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        confirm.set_default_response("cancel")
        confirm.set_close_response("cancel")

        def _on_response(_d, response):
            if response == "delete":
                self._delete_project(project)

        confirm.connect("response", _on_response)
        confirm.present()

    def _delete_project(self, project: Project) -> None:
        self.ws.disband(project)
        if self._current_group is project:
            self._current_group = self.ws.unsorted
        save_projects(self.ws, default_path())
        self.sidebar.refresh()
        self._refresh_empty_state()

    def _archive_project(self, project: Project) -> None:
        # Close every tab via the standard close path so child processes
        # terminate cleanly. Iterate over a copy because _on_close_tab
        # mutates project.tabs.
        for tab in list(project.tabs):
            self._on_close_tab(self.sidebar, tab)
        project.archived = True
        if self._current_group is project:
            self._show_empty(self.ws.unsorted)
        save_projects(self.ws, default_path())
        self.sidebar.refresh()
        self._refresh_empty_state()

    def _on_unarchive_project(self, _sb, project: Project) -> None:
        project.archived = False
        save_projects(self.ws, default_path())
        self.sidebar.refresh()
        self._refresh_empty_state()

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

        from jfterm.url_routing import is_web_url

        running_terminal = {
            t.launched_command
            for t in project.tabs
            if isinstance(t, TerminalTab) and t.launched_command
        }
        running_web = {t.url for t in project.tabs if isinstance(t, WebTab)}
        cmds = [
            sc
            for sc in project.startup_commands
            if sc.command not in running_terminal and sc.command.strip() not in running_web
        ]
        spawn_blank = project.spawn_blank_after_startup

        def _step(idx: int) -> bool:
            if idx >= len(cmds):
                if spawn_blank:
                    self._spawn_tab(project, focus=True)
                return False  # remove timeout
            sc = cmds[idx]
            is_last = idx == len(cmds) - 1
            focus = sc.delay > 0 or (is_last and not spawn_blank)
            if is_web_url(sc.command):
                try:
                    self._spawn_web_tab(
                        project,
                        url=sc.command.strip(),
                        focus=focus,
                        from_startup=True,
                    )
                except RuntimeError as e:
                    fb = self._spawn_tab(
                        project,
                        command=f'echo "JFTerm: {e}"',
                        focus=focus,
                    )
                    fb.from_startup = True
                    fb.title = f"▶ {sc.command}"
            else:
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

        from jfterm.linked import parse_linked
        from jfterm.url_routing import is_web_url

        linked_spec = parse_linked(fc.command)
        if linked_spec is not None:
            self._spawn_linked_tab(
                project,
                spec=linked_spec,
                flash_name=fc.name,
                focus=fc.focus_on_launch,
            )
            self.sidebar.refresh()
            return

        if is_web_url(fc.command):
            try:
                self._spawn_web_tab(
                    project,
                    url=fc.command.strip(),
                    focus=fc.focus_on_launch,
                    flash_name=fc.name,
                )
            except RuntimeError as e:
                fb = self._spawn_tab(
                    project,
                    command=f'echo "JFTerm: {e}"',
                    focus=fc.focus_on_launch,
                )
                fb.flash_name = fc.name
                fb.title = f"⚡ {fc.name}"
            self.sidebar.refresh()
            return

        wrapped = wrap_flash_command(fc)
        tab = self._spawn_tab(project, command=wrapped, focus=fc.focus_on_launch)
        tab.flash_name = fc.name
        tab.title = f"⚡ {fc.name}"
        self.sidebar.refresh()

    def _on_toggle_expanded(self, _sb, group: Group) -> None:
        group.expanded = not group.expanded
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    def _on_dot_clicked(self, _sb, tab: TerminalTab, current_group: Group, anchor) -> None:
        from jfterm.menus import build_move_to_popover

        def _move(dest: Group) -> None:
            self.ws.move_tab(tab, dest)
            if tab.widget is not None and self.terminal_stack.get_visible_child() is tab.widget:
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
        if tab.widget is not None and self.terminal_stack.get_visible_child() is tab.widget:
            self._current_group = dest_group
        if isinstance(tab, (TerminalTab, LinkedTab)):
            self._refresh_tab_dot(tab)
        self.sidebar.refresh()

    def _on_project_dropped(self, _sb, project, position: int) -> None:
        active = self.ws.active_projects
        src_idx = active.index(project)
        adjusted = position
        if src_idx < position:
            adjusted -= 1
        self.ws.move_project(project, adjusted)
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    def _on_tab_cwd_changed(self, tab: TerminalTab | LinkedTab, path: str) -> None:
        tab.current_cwd = path
        self._refresh_tab_dot(tab)

    def _on_tab_running_changed(self, tab: TerminalTab | LinkedTab, running: bool) -> None:
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

    def _on_tab_title_changed(self, tab: TerminalTab | LinkedTab, title: str) -> None:
        if tab.flash_name is not None:
            tab.title = f"⚡ {tab.flash_name}: {title}" if title else f"⚡ {tab.flash_name}"
        elif getattr(tab, "from_startup", False):
            base = title or tab.launched_command or "tab"
            tab.title = f"▶ {base}"
        else:
            tab.title = title
        self.sidebar.refresh()

    # --- helpers ---

    def _refresh_tab_dot(self, tab: TerminalTab | LinkedTab) -> None:
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

    def mcp_list_projects(self) -> list[ProjectInfo]:
        from jfterm.mcp_types import ProjectInfo

        out: list[ProjectInfo] = []
        for g in self.ws.all_groups():
            directory = g.directory if isinstance(g, Project) else ""
            out.append(ProjectInfo(name=g.name, directory=directory, tab_count=len(g.tabs)))
        return out

    def mcp_list_tabs(self, project_name: str | None) -> list[TabInfo]:
        from jfterm.mcp_types import ProjectNotFound

        groups: list[Group]
        if project_name is None:
            groups = self.ws.all_groups()
        else:
            match = next((g for g in self.ws.all_groups() if g.name == project_name), None)
            if match is None:
                raise ProjectNotFound(project_name)
            groups = [match]
        out: list[TabInfo] = []
        for g in groups:
            for t in g.tabs:
                out.append(self._tab_to_info(t, g.name))
        return out

    def _tab_to_info(self, tab: Tab, project_name: str) -> TabInfo:
        from jfterm.mcp_types import TabInfo

        if isinstance(tab, TerminalTab):
            cwd = tab.current_cwd
            busy = tab.is_running
            launched_command = tab.launched_command
        else:
            cwd = None
            busy = False
            launched_command = None
        return TabInfo(
            id=tab.id,
            title=tab.title,
            project=project_name,
            cwd=cwd,
            busy=busy,
            launched_command=launched_command,
        )

    def mcp_spawn_tab(self, project_name: str, command: str) -> TabInfo:
        from jfterm.mcp_types import EmptyCommand, ProjectNotFound

        if not command:
            raise EmptyCommand()
        group = next((g for g in self.ws.all_groups() if g.name == project_name), None)
        if group is None:
            raise ProjectNotFound(project_name)
        tab = self._spawn_tab(group, command=command, focus=False)
        return self._tab_to_info(tab, group.name)

    def mcp_spawn_web_tab(self, project_name: str, url: str) -> TabInfo:
        from jfterm.mcp_types import EmptyUrl, ProjectNotFound

        if not url:
            raise EmptyUrl()
        group = next((g for g in self.ws.all_groups() if g.name == project_name), None)
        if group is None:
            raise ProjectNotFound(project_name)
        tab = self._spawn_web_tab(group, url=url, focus=False)
        return self._tab_to_info(tab, group.name)

    def mcp_restart_tab(self, tab_id: str) -> TabInfo:
        from jfterm.mcp_types import TabHasNoCommand, TabNotFound

        for g in self.ws.all_groups():
            for t in g.tabs:
                if t.id == tab_id:
                    if not isinstance(t, TerminalTab) or not t.launched_command:
                        raise TabHasNoCommand(tab_id)
                    self._on_restart_tab(self.sidebar, t)
                    return self._tab_to_info(t, g.name)
        raise TabNotFound(tab_id)

    def mcp_focus_tab(self, tab_id: str) -> TabInfo:
        from jfterm.mcp_types import TabNotFound

        for g in self.ws.all_groups():
            for t in g.tabs:
                if t.id == tab_id:
                    self._on_tab_activated(self.sidebar, t)
                    return self._tab_to_info(t, g.name)
        raise TabNotFound(tab_id)

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
                if t.widget is visible:
                    return t
        return None

    def _cycle_tab(self, delta: int) -> None:
        flat = [t for g in self.ws.all_groups() for t in g.tabs]
        if not flat:
            return
        cur = self._current_tab()
        idx = flat.index(cur) if cur in flat else -1
        nxt = flat[(idx + delta) % len(flat)]
        if nxt.widget is not None:
            self._current_group = self.ws._find_group(nxt)
            self.terminal_stack.set_visible_child(nxt.widget)
            self.sidebar.set_active_tab(nxt)
            nxt.widget.grab_focus()

    def _on_preferences(self, _action, _param) -> None:
        dialog = AppPreferencesDialog(self._settings)
        dialog.connect("changed", self._on_settings_changed)
        dialog.present(self)

    def _on_settings_changed(self, _dialog, settings: AppSettings) -> None:
        # Preferences dialog only edits its own subset of fields; carry the
        # window geometry across so we don't clobber it on save.
        settings.window_width = self._settings.window_width
        settings.window_height = self._settings.window_height
        settings.window_maximized = self._settings.window_maximized
        self._settings = settings
        try:
            save_settings(settings, self._settings_path)
        except OSError as e:
            print(f"jfterm: failed to save settings: {e}", file=sys.stderr)
        for terminal in self._iter_terminals():
            terminal.apply_appearance(settings)

    def _iter_terminals(self) -> Iterator[JFTermTerminal]:
        for group in self.ws.all_groups():
            for tab in group.tabs:
                widget = getattr(tab, "widget", None)
                if isinstance(widget, JFTermTerminal):
                    yield widget

    def _on_sidebar_toggled(self, btn: Gtk.ToggleButton) -> None:
        visible = btn.get_active()
        self.sidebar.set_visible(visible)
        btn.set_tooltip_text("Hide sidebar" if visible else "Show sidebar")

    def _on_window_geometry_changed(self, *_args) -> None:
        from gi.repository import GLib

        if self._window_save_source is not None:
            GLib.source_remove(self._window_save_source)

        def _flush() -> bool:
            self._window_save_source = None
            self._persist_window_geometry()
            return False

        self._window_save_source = GLib.timeout_add(500, _flush)

    def _persist_window_geometry(self) -> None:
        maximized = bool(self.is_maximized())
        # default-width/height track the windowed size, not the maximized size,
        # so they're the right values to restore on next launch.
        width, height = self.get_default_size()
        if width > 0:
            self._settings.window_width = width
        if height > 0:
            self._settings.window_height = height
        self._settings.window_maximized = maximized
        with contextlib.suppress(OSError):
            save_settings(self._settings, self._settings_path)

    def _on_close_request(self, _win) -> bool:
        from gi.repository import GLib

        if self._window_save_source is not None:
            GLib.source_remove(self._window_save_source)
            self._window_save_source = None
        self._persist_window_geometry()
        return False  # allow close

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

    def _show_empty(self, group: Group | None = None) -> None:
        self._current_group = group
        self._refresh_empty_state()
        self.terminal_stack.set_visible_child_name("__empty__")
        self.sidebar.set_active_tab(None)

    def _build_empty_state(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_vexpand(True)
        box.set_hexpand(True)

        self._empty_message = Gtk.Label()
        self._empty_message.add_css_class("title-2")
        box.append(self._empty_message)

        self._empty_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._empty_buttons.set_halign(Gtk.Align.CENTER)
        box.append(self._empty_buttons)

        self._refresh_empty_state()
        return box

    def _refresh_empty_state(self) -> None:
        active_projects = self.ws.active_projects
        has_projects = bool(active_projects)
        if has_projects:
            self._empty_message.set_text("Open a new tab by clicking +")
        else:
            self._empty_message.set_text("Create a project or open a new tab by clicking +")

        while (child := self._empty_buttons.get_first_child()) is not None:
            self._empty_buttons.remove(child)

        shell_btn = Gtk.Button(label="New shell tab")
        shell_btn.connect("clicked", lambda _b: self._on_new_tab(self.sidebar, self.ws.unsorted))
        self._empty_buttons.append(shell_btn)

        web_btn = Gtk.Button(label="New web tab")
        web_btn.connect(
            "clicked", lambda _b: self._on_new_web_tab(self.sidebar, self.ws.unsorted, "")
        )
        self._empty_buttons.append(web_btn)

        if not has_projects:
            new_proj_btn = Gtk.Button(label="New project")
            new_proj_btn.connect("clicked", lambda _b: self._on_new_project())
            self._empty_buttons.append(new_proj_btn)

        launchable = [p for p in active_projects if p.startup_commands]
        if len(launchable) == 1:
            sole = launchable[0]
            launch_btn = Gtk.Button(label=f"Launch {sole.name}")
            launch_btn.connect("clicked", lambda _b: self._on_launch_project(self.sidebar, sole))
            self._empty_buttons.append(launch_btn)
        elif len(launchable) > 1:
            launch_btn = Gtk.MenuButton(label="Launch project")
            popover = Gtk.Popover()
            pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            for p in launchable:
                item = Gtk.Button(label=p.name)
                item.add_css_class("flat")

                def _launch(_b, proj=p, pop=popover) -> None:
                    pop.popdown()
                    self._on_launch_project(self.sidebar, proj)

                item.connect("clicked", _launch)
                pbox.append(item)
            popover.set_child(pbox)
            launch_btn.set_popover(popover)
            self._empty_buttons.append(launch_btn)

    def _on_window_key_pressed(self, _ctrl, keyval, _keycode, _state) -> bool:
        from gi.repository import GLib

        self._double_shift.on_press(keyval, GLib.get_monotonic_time() // 1000)
        return False

    def _open_launcher(self) -> None:
        self._double_shift.reset()
        self._launcher.open(self.ws)

    def _dispatch_launcher_action(self, action) -> None:
        from jfterm.launcher_items import (
            FlashAction,
            JumpAction,
            NewTabAction,
            NewWebTabAction,
            StartupAction,
        )

        if isinstance(action, FlashAction):
            self._on_flash_command_launched(self.sidebar, action.project, action.flash)
        elif isinstance(action, NewTabAction):
            self._spawn_tab(action.group)
        elif isinstance(action, NewWebTabAction):
            self._on_new_web_tab(self.sidebar, action.group, "")
        elif isinstance(action, StartupAction):
            self._on_launch_project(self.sidebar, action.project)
        elif isinstance(action, JumpAction):
            self._on_tab_activated(self.sidebar, action.tab)
