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
class Tab:
    title: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
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
    # True while a restart is in flight, so the old terminal's child-exited
    # signal does not remove the tab from its group.
    is_restarting: bool = False


class Group:
    """Either a Project or the Unsorted singleton. Owns an ordered tab list."""

    name: str

    def __init__(self) -> None:
        self.tabs: list[Tab] = []

    def add_tab(self, tab: Tab, position: int | None = None) -> None:
        if position is None:
            self.tabs.append(tab)
        else:
            self.tabs.insert(position, tab)

    def remove_tab(self, tab: Tab) -> None:
        self.tabs.remove(tab)


class Unsorted(Group):
    name = "Unsorted"

    def __init__(self) -> None:
        super().__init__()
        self.expanded: bool = True


class Project(Group):
    def __init__(
        self,
        name: str,
        directory: str,
        expanded: bool = True,
        id: str | None = None,
        startup_commands: list[StartupCommand] | None = None,
        spawn_blank_after_startup: bool = False,
    ) -> None:
        super().__init__()
        self.name = name
        self.directory = directory
        self.expanded = expanded
        self.id = id if id is not None else uuid.uuid4().hex
        self.startup_commands: list[StartupCommand] = list(startup_commands or [])
        self.spawn_blank_after_startup = spawn_blank_after_startup


class Workspace:
    """Top-level container: ordered project list + Unsorted singleton."""

    def __init__(self) -> None:
        self.projects: list[Project] = []
        self.unsorted = Unsorted()
        self.sidebar_width: int = 220

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

    def _find_group(self, tab: Tab) -> Group:
        for g in (*self.projects, self.unsorted):
            if tab in g.tabs:
                return g
        raise ValueError(f"tab {tab} not in any group")

    def all_groups(self) -> list[Group]:
        return [*self.projects, self.unsorted]
