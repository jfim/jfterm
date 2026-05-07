"""Pure async tool implementations for the MCP server.

Each tool is a plain async function that takes an MCPController and a
Pydantic input model. Returns plain dicts that FastMCP serializes to
JSON. No SDK or GTK imports — testable in isolation.
"""

from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel

from jfterm.mcp_types import MCPController


class ListProjectsInput(BaseModel):
    pass


async def list_projects(
    controller: MCPController, _params: ListProjectsInput
) -> dict:
    return {"projects": [asdict(p) for p in controller.list_projects()]}


class ListTabsInput(BaseModel):
    project_name: str | None = None


async def list_tabs(controller: MCPController, params: ListTabsInput) -> dict:
    return {
        "tabs": [asdict(t) for t in controller.list_tabs(params.project_name)],
    }


class SpawnTabInput(BaseModel):
    project_name: str
    command: str


async def spawn_tab(controller: MCPController, params: SpawnTabInput) -> dict:
    tab = controller.spawn_tab(params.project_name, params.command)
    return {"tab": asdict(tab)}


class RestartTabInput(BaseModel):
    id: str


async def restart_tab(controller: MCPController, params: RestartTabInput) -> dict:
    tab = controller.restart_tab(params.id)
    return {"tab": asdict(tab)}
