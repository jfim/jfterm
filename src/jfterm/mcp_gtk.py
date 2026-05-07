"""GTK adapter implementing MCPController.

The MCP server runs tools on its own asyncio thread (inside the daemon
thread spawned by MCPServerThread). All workspace mutations have to
happen on the GTK main thread, so each method bounces a callable onto
GLib.idle_add and blocks on a Future for the result.
"""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import GLib

from jfterm.mcp_types import MCPController, ProjectInfo, TabInfo

if TYPE_CHECKING:
    from jfterm.window import JFTermWindow

# Hard ceiling so a wedged GTK thread can't permanently hang the MCP
# request handler. 10s is generous for a UI-thread operation.
_GTK_CALL_TIMEOUT = 10.0


def _on_gtk_thread[T](thunk: Callable[[], T]) -> T:
    fut: concurrent.futures.Future[T] = concurrent.futures.Future()

    def _run() -> bool:
        try:
            fut.set_result(thunk())
        except BaseException as e:
            fut.set_exception(e)
        return False  # GLib.SOURCE_REMOVE

    GLib.idle_add(_run)
    return fut.result(timeout=_GTK_CALL_TIMEOUT)


class GtkMCPController(MCPController):
    def __init__(self, window: JFTermWindow) -> None:
        self._window = window

    def list_projects(self) -> list[ProjectInfo]:
        return _on_gtk_thread(self._window.mcp_list_projects)

    def list_tabs(self, project_name: str | None) -> list[TabInfo]:
        return _on_gtk_thread(lambda: self._window.mcp_list_tabs(project_name))

    def spawn_tab(self, project_name: str, command: str) -> TabInfo:
        return _on_gtk_thread(lambda: self._window.mcp_spawn_tab(project_name, command))

    def restart_tab(self, tab_id: str) -> TabInfo:
        return _on_gtk_thread(lambda: self._window.mcp_restart_tab(tab_id))
