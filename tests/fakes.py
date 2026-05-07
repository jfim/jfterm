"""In-memory fake controller for unit tests.

Mirrors the semantics described in the spec: project lookup by name,
"Unsorted" is a real project name, tab IDs are unique strings.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

from jfterm.mcp_types import (
    EmptyCommand,
    MCPController,
    ProjectInfo,
    ProjectNotFound,
    TabHasNoCommand,
    TabInfo,
    TabNotFound,
)


class FakeController(MCPController):
    def __init__(self) -> None:
        self.projects: dict[str, ProjectInfo] = {
            "Unsorted": ProjectInfo(name="Unsorted", directory="", tab_count=0),
        }
        self.tabs: list[TabInfo] = []
        self.spawn_log: list[tuple[str, str]] = []
        self.restart_log: list[str] = []
        self.focus_log: list[str] = []

    def add_project(self, name: str, directory: str) -> None:
        self.projects[name] = ProjectInfo(name=name, directory=directory, tab_count=0)

    def add_tab(
        self,
        project: str,
        title: str,
        *,
        cwd: str | None = None,
        busy: bool = False,
        launched_command: str | None = None,
    ) -> TabInfo:
        if project not in self.projects:
            raise ProjectNotFound(project)
        tab = TabInfo(
            id=uuid.uuid4().hex,
            title=title,
            project=project,
            cwd=cwd,
            busy=busy,
            launched_command=launched_command,
        )
        self.tabs.append(tab)
        p = self.projects[project]
        self.projects[project] = replace(p, tab_count=p.tab_count + 1)
        return tab

    # --- MCPController surface ---

    def list_projects(self) -> list[ProjectInfo]:
        return list(self.projects.values())

    def list_tabs(self, project_name: str | None) -> list[TabInfo]:
        if project_name is None:
            return list(self.tabs)
        if project_name not in self.projects:
            raise ProjectNotFound(project_name)
        return [t for t in self.tabs if t.project == project_name]

    def spawn_tab(self, project_name: str, command: str) -> TabInfo:
        if not command:
            raise EmptyCommand()
        if project_name not in self.projects:
            raise ProjectNotFound(project_name)
        self.spawn_log.append((project_name, command))
        return self.add_tab(project_name, command, launched_command=command)

    def restart_tab(self, tab_id: str) -> TabInfo:
        for tab in self.tabs:
            if tab.id == tab_id:
                if tab.launched_command is None:
                    raise TabHasNoCommand(tab_id)
                self.restart_log.append(tab_id)
                return tab
        raise TabNotFound(tab_id)

    def focus_tab(self, tab_id: str) -> TabInfo:
        for tab in self.tabs:
            if tab.id == tab_id:
                self.focus_log.append(tab_id)
                return tab
        raise TabNotFound(tab_id)
