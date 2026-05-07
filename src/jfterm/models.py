from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StartupCommand:
    """A command to run when launching a project, with a post-spawn delay
    (in seconds) before the next command is spawned."""

    command: str
    delay: int = 0


@dataclass
class FlashCommand:
    """A one-shot command launched from the project's flash menu."""

    name: str
    command: str
    keep_open_on_success: bool = False
    focus_on_launch: bool = True


@dataclass
class Tab:
    """Base class for a tab. Concrete subclasses below mount different
    widgets (a VTE terminal or a WebKit view) in the window's stack."""

    title: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # Sidebar attaches the row's StatusDot here for terminal tabs so the
    # runtime layer can update its visual state without a full sidebar refresh.
    # Web tabs leave this None.
    _dot: Any = None

    @property
    def widget(self) -> Any:
        """The GTK widget mounted in the window's terminal_stack."""
        raise NotImplementedError


@dataclass
class TerminalTab(Tab):
    # Runtime-only fields populated when a real terminal is attached:
    terminal: Any = None
    shell_pid: int | None = None
    pty_fd: int | None = None
    current_cwd: str | None = None
    is_running: bool = False
    osc133_seen: bool = False
    # The startup command this tab was launched with (None for plain shells).
    # Set once at spawn time and reused on restart.
    launched_command: str | None = None
    # Display name of the flash command this tab was launched with (None if
    # not a flash tab). Used to prefix the tab title with "⚡ {name}: ".
    flash_name: str | None = None
    # True when launched from a project's startup commands. Used to prefix
    # the tab title with "▶ ".
    from_startup: bool = False
    # True while a restart is in flight, so the old terminal's child-exited
    # signal does not remove the tab from its group.
    is_restarting: bool = False

    @property
    def widget(self) -> Any:
        return self.terminal


@dataclass
class WebTab(Tab):
    # The URL the tab was launched with — used as title fallback and for the
    # "skip if already running" check during project launch.
    url: str = ""
    # The JFTermWebView widget mounted in the stack.
    web_view: Any = None
    from_startup: bool = False
    flash_name: str | None = None

    @property
    def widget(self) -> Any:
        return self.web_view


class Group:
    """Either a Project or the Unsorted singleton. Owns an ordered tab list."""

    name: str

    def __init__(self) -> None:
        self.tabs: list[Tab] = []
        self.expanded: bool = True

    def add_tab(self, tab: Tab, position: int | None = None) -> None:
        if position is None:
            self.tabs.append(tab)
        else:
            self.tabs.insert(position, tab)

    def remove_tab(self, tab: Tab) -> None:
        self.tabs.remove(tab)


class Unsorted(Group):
    name = "Unsorted"


class Project(Group):
    def __init__(
        self,
        name: str,
        directory: str,
        expanded: bool = True,
        id: str | None = None,
        startup_commands: list[StartupCommand] | None = None,
        spawn_blank_after_startup: bool = False,
        flash_commands: list[FlashCommand] | None = None,
        archived: bool = False,
    ) -> None:
        super().__init__()
        self.name = name
        self.directory = directory
        self.expanded = expanded
        self.id = id if id is not None else uuid.uuid4().hex
        self.startup_commands: list[StartupCommand] = list(startup_commands or [])
        self.spawn_blank_after_startup = spawn_blank_after_startup
        self.flash_commands: list[FlashCommand] = list(flash_commands or [])
        self.archived = archived
        # Forward-compat: unknown fields read from disk are preserved here
        # and re-emitted on save so older code doesn't drop newer schema keys.
        self._extra: dict[str, Any] = {}


class Workspace:
    """Top-level container: ordered project list + Unsorted singleton."""

    def __init__(self) -> None:
        self.projects: list[Project] = []
        self.unsorted = Unsorted()
        self.sidebar_width: int = 220
        self.archived_expanded: bool = False

    @property
    def active_projects(self) -> list[Project]:
        return [p for p in self.projects if not p.archived]

    @property
    def archived_projects(self) -> list[Project]:
        return [p for p in self.projects if p.archived]

    def add_project(self, name: str, directory: str) -> Project:
        p = Project(name=name, directory=directory)
        self.projects.append(p)
        return p

    def disband(self, project: Project) -> None:
        self.projects.remove(project)
        for t in project.tabs:
            self.unsorted.tabs.append(t)
        project.tabs = []

    def move_tab(self, tab: Tab, dest: Group, position: int | None = None) -> None:
        src = self._find_group(tab)
        src.remove_tab(tab)
        dest.add_tab(tab, position=position)

    def move_project(self, project: Project, position: int) -> None:
        if project.archived:
            raise ValueError("cannot move an archived project")
        active = self.active_projects
        if project not in active:
            raise ValueError(f"project {project!r} is not in this workspace")
        if position < 0 or position >= len(active):
            raise ValueError(f"position {position} out of range 0..{len(active) - 1}")

        self.projects.remove(project)
        active_after = [p for p in self.projects if not p.archived]
        if position == len(active_after):
            self.projects.append(project)
            return
        anchor = active_after[position]
        anchor_idx = self.projects.index(anchor)
        self.projects.insert(anchor_idx, project)

    def _find_group(self, tab: Tab) -> Group:
        for g in (*self.projects, self.unsorted):
            if tab in g.tabs:
                return g
        raise ValueError(f"tab {tab} not in any group")

    def all_groups(self) -> list[Group]:
        return [*self.projects, self.unsorted]
