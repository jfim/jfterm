"""Embedded MCP server for JFTerm.

Wires the pure tool functions in mcp_tools to a FastMCP instance and
runs streamable-HTTP on a daemon thread bound to 127.0.0.1.
"""

from __future__ import annotations

import logging
import threading

from mcp.server.fastmcp import FastMCP

from jfterm.mcp_tools import (
    FocusTabInput,
    ListProjectsInput,
    ListTabsInput,
    RestartTabInput,
    SpawnTabInput,
    SpawnWebTabInput,
    focus_tab,
    list_projects,
    list_tabs,
    restart_tab,
    spawn_tab,
    spawn_web_tab,
)
from jfterm.mcp_types import MCPController, MCPError

log = logging.getLogger(__name__)


def build_server(controller: MCPController) -> FastMCP:
    """Construct a FastMCP server with the four tools registered.

    Each tool wraps the controller call in a try/except for MCPError so
    user-facing failures (unknown project, unknown tab) surface as MCP
    isError results rather than as 500s.
    """
    mcp = FastMCP("jfterm")

    @mcp.tool()
    async def list_projects_tool() -> dict:
        """List projects, including the Unsorted bucket."""
        return await list_projects(controller, ListProjectsInput())

    @mcp.tool()
    async def list_tabs_tool(project_name: str | None = None) -> dict:
        """List tabs across all projects, or a single named project."""
        try:
            return await list_tabs(controller, ListTabsInput(project_name=project_name))
        except MCPError as e:
            return {"error": type(e).__name__, "message": str(e)}

    @mcp.tool()
    async def spawn_tab_tool(project_name: str, command: str) -> dict:
        """Spawn a new tab running `command` in `project_name`."""
        try:
            return await spawn_tab(
                controller, SpawnTabInput(project_name=project_name, command=command)
            )
        except MCPError as e:
            return {"error": type(e).__name__, "message": str(e)}

    @mcp.tool()
    async def spawn_web_tab_tool(project_name: str, url: str) -> dict:
        """Spawn a new web tab pointing at `url` in `project_name`."""
        try:
            return await spawn_web_tab(
                controller, SpawnWebTabInput(project_name=project_name, url=url)
            )
        except MCPError as e:
            return {"error": type(e).__name__, "message": str(e)}

    @mcp.tool()
    async def restart_tab_tool(id: str) -> dict:
        """Restart a tab in place. Only valid for tabs spawned with a startup command."""
        try:
            return await restart_tab(controller, RestartTabInput(id=id))
        except MCPError as e:
            return {"error": type(e).__name__, "message": str(e)}

    @mcp.tool()
    async def focus_tab_tool(id: str) -> dict:
        """Focus a tab — switch to it and bring its input to the foreground.

        Use deliberately to direct the user's attention; spawn_tab does NOT
        focus the new tab.
        """
        try:
            return await focus_tab(controller, FocusTabInput(id=id))
        except MCPError as e:
            return {"error": type(e).__name__, "message": str(e)}

    return mcp


class MCPServerThread:
    """Runs FastMCP's streamable-HTTP transport on a daemon thread.

    Designed for embedding in a GTK app: `start()` is non-blocking;
    process exit kills the thread (daemon=True). Two instances of
    JFTerm on the same machine collide on the port — the second logs
    the bind error and the app continues without an MCP server.
    """

    def __init__(self, controller: MCPController, host: str = "127.0.0.1", port: int = 7820):
        self._controller = controller
        self._host = host
        self._port = port
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        mcp = build_server(self._controller)
        mcp.settings.host = self._host
        mcp.settings.port = self._port

        def _run() -> None:
            try:
                mcp.run(transport="streamable-http")
            except OSError as e:
                log.warning("MCP server failed to bind %s:%d: %s", self._host, self._port, e)
            except Exception:
                log.exception("MCP server crashed")

        self._thread = threading.Thread(target=_run, name="jfterm-mcp", daemon=True)
        self._thread.start()
        log.info("MCP server starting on http://%s:%d/mcp", self._host, self._port)
