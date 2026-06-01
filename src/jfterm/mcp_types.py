"""Types and Protocol for the MCP layer.

This module deliberately has no dependency on GTK or the mcp SDK so it
can be imported by both the tool layer (mcp_tools) and the GTK adapter
(mcp_gtk) without pulling in either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    directory: str
    tab_count: int


@dataclass(frozen=True)
class TabInfo:
    id: str
    title: str
    project: str
    cwd: str | None
    busy: bool
    launched_command: str | None


class MCPError(Exception):
    """Base for errors that should be returned to the MCP client as
    isError tool results rather than tracebacks."""


class ProjectNotFound(MCPError):
    pass


class TabNotFound(MCPError):
    pass


class TabHasNoCommand(MCPError):
    pass


class EmptyCommand(MCPError):
    pass


class ControlCharInCommand(MCPError):
    pass


class EmptyUrl(MCPError):
    pass


class MCPController(Protocol):
    def list_projects(self) -> list[ProjectInfo]: ...
    def list_tabs(self, project_name: str | None) -> list[TabInfo]: ...
    def spawn_tab(self, project_name: str, command: str) -> TabInfo: ...
    def spawn_web_tab(self, project_name: str, url: str) -> TabInfo: ...
    def restart_tab(self, tab_id: str) -> TabInfo: ...
    def focus_tab(self, tab_id: str) -> TabInfo: ...
