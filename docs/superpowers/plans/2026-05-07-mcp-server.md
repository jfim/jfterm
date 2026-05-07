# MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed an HTTP MCP server in JFTerm exposing four tools (`list_projects`, `list_tabs`, `spawn_tab`, `restart_tab`) so Claude Code can drive tabs from inside a JFTerm session.

**Architecture:** A `MCPController` Protocol defines the four operations the tools need. Pure tool functions take a controller and return JSON-shaped dataclasses; tests use a `FakeController` (no GTK). The official `mcp` Python SDK's `FastMCP` registers the tools and runs the streamable-HTTP transport on a daemon thread bound to `127.0.0.1:7820`. A `GtkMCPController` adapter implements the Protocol by bouncing each call onto the GTK main thread via `GLib.idle_add` and a `concurrent.futures.Future`. `JFTermWindow` wires up the adapter and starts/stops the server.

**Tech Stack:** Python 3.12, official `mcp` SDK ≥1.0 (FastMCP + streamable-http), Pydantic (already a transitive of `mcp`), pytest, pytest-asyncio.

Spec: [docs/superpowers/specs/2026-05-06-mcp-server-design.md](../specs/2026-05-06-mcp-server-design.md).

---

## File Structure

- Create: `src/jfterm/mcp_types.py` — `ProjectInfo`, `TabInfo` dataclasses + `MCPController` Protocol + the four custom exceptions (`ProjectNotFound`, `TabNotFound`, `TabHasNoCommand`, `EmptyCommand`).
- Create: `src/jfterm/mcp_tools.py` — pure async tool functions that take a controller; no SDK or GTK imports.
- Create: `src/jfterm/mcp_server.py` — FastMCP server registration + thread runner.
- Create: `src/jfterm/mcp_gtk.py` — `GtkMCPController` adapter that talks to `JFTermWindow` via `GLib.idle_add`.
- Modify: `src/jfterm/window.py` — instantiate `GtkMCPController`, start the MCP server thread; expose helper methods used by the controller.
- Modify: `pyproject.toml` — add `mcp>=1.0` runtime dep and `pytest-asyncio` dev dep.
- Create: `tests/test_mcp_tools.py` — unit tests for each tool against a `FakeController`.
- Create: `tests/test_mcp_server.py` — round-trip smoke test using `FastMCP` + `streamable_http_client`.
- Create: `tests/fakes.py` — `FakeController` shared between tool and server tests.

---

## Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add runtime and dev deps**

In `pyproject.toml`, change `dependencies = []` to:

```toml
dependencies = [
    "mcp>=1.0",
]
```

And in `[dependency-groups]` `dev`, add `pytest-asyncio`:

```toml
[dependency-groups]
dev = [
    "pytest>=9.0.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
    "pyright>=1.1",
]
```

Add a pytest-asyncio config block so async tests don't need a per-file marker:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
```

The `pythonpath = ["."]` line lets the smoke test import `tests.fakes`
without needing a `tests/__init__.py`.

- [ ] **Step 2: Sync the venv**

Run: `uv sync`
Expected: `mcp` and `pytest-asyncio` installed under `.venv`. No errors.

- [ ] **Step 3: Verify import works**

Run: `uv run python -c "from mcp.server.fastmcp import FastMCP; from mcp.client.streamable_http import streamablehttp_client; print('ok')"`
Expected: `ok` printed. (If the second import name is `streamable_http_client`, switch to that — the SDK has had both names; use whichever the installed version exposes and use it consistently in Task 7.)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): add mcp SDK and pytest-asyncio"
```

---

## Task 2: Types + Protocol + custom exceptions

**Files:**
- Create: `src/jfterm/mcp_types.py`
- Test: (none — exercised through tool tests in later tasks)

- [ ] **Step 1: Write the module**

```python
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


class MCPController(Protocol):
    def list_projects(self) -> list[ProjectInfo]: ...
    def list_tabs(self, project_name: str | None) -> list[TabInfo]: ...
    def spawn_tab(self, project_name: str, command: str) -> TabInfo: ...
    def restart_tab(self, tab_id: str) -> TabInfo: ...
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from jfterm.mcp_types import MCPController, ProjectInfo, TabInfo, ProjectNotFound; print('ok')"`
Expected: `ok` printed.

- [ ] **Step 3: Commit**

```bash
git add src/jfterm/mcp_types.py
git commit -m "feat(mcp): types and controller Protocol"
```

---

## Task 3: FakeController for tests

**Files:**
- Create: `tests/fakes.py`

- [ ] **Step 1: Write the fake**

```python
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
```

- [ ] **Step 2: Smoke-import**

Run: `uv run python -c "from tests.fakes import FakeController; c = FakeController(); print(c.list_projects())"`
Expected: a single-element list containing the Unsorted `ProjectInfo`.

- [ ] **Step 3: Commit**

```bash
git add tests/fakes.py
git commit -m "test(mcp): in-memory FakeController"
```

---

## Task 4: `list_projects` tool — TDD

**Files:**
- Create: `src/jfterm/mcp_tools.py` (with just this tool first; later tasks append).
- Create: `tests/test_mcp_tools.py`

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for the pure tool layer (no SDK, no GTK)."""

from __future__ import annotations

import pytest

from jfterm.mcp_tools import list_projects, ListProjectsInput
from tests.fakes import FakeController


async def test_list_projects_includes_unsorted():
    ctrl = FakeController()
    result = await list_projects(ctrl, ListProjectsInput())
    assert [p["name"] for p in result["projects"]] == ["Unsorted"]
    assert result["projects"][0]["tab_count"] == 0


async def test_list_projects_returns_added_projects():
    ctrl = FakeController()
    ctrl.add_project("alpha", "/home/me/alpha")
    ctrl.add_tab("alpha", "vim")
    ctrl.add_tab("alpha", "shell")
    result = await list_projects(ctrl, ListProjectsInput())
    by_name = {p["name"]: p for p in result["projects"]}
    assert by_name["alpha"] == {
        "name": "alpha",
        "directory": "/home/me/alpha",
        "tab_count": 2,
    }
```

- [ ] **Step 2: Run test, expect failure**

Run: `uv run pytest tests/test_mcp_tools.py -v`
Expected: ImportError on `jfterm.mcp_tools` — module doesn't exist yet.

- [ ] **Step 3: Implement the tool**

Create `src/jfterm/mcp_tools.py`:

```python
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
```

- [ ] **Step 4: Run test, expect pass**

Run: `uv run pytest tests/test_mcp_tools.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/mcp_tools.py tests/test_mcp_tools.py
git commit -m "feat(mcp): list_projects tool"
```

---

## Task 5: `list_tabs` tool — TDD

**Files:**
- Modify: `src/jfterm/mcp_tools.py`
- Modify: `tests/test_mcp_tools.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_mcp_tools.py`:

```python
from jfterm.mcp_tools import list_tabs, ListTabsInput
from jfterm.mcp_types import ProjectNotFound


async def test_list_tabs_all_when_project_omitted():
    ctrl = FakeController()
    ctrl.add_project("alpha", "/a")
    ctrl.add_project("beta", "/b")
    ctrl.add_tab("alpha", "vim")
    ctrl.add_tab("beta", "shell")
    result = await list_tabs(ctrl, ListTabsInput())
    titles = sorted(t["title"] for t in result["tabs"])
    assert titles == ["shell", "vim"]


async def test_list_tabs_filters_by_project():
    ctrl = FakeController()
    ctrl.add_project("alpha", "/a")
    ctrl.add_project("beta", "/b")
    ctrl.add_tab("alpha", "vim")
    ctrl.add_tab("beta", "shell")
    result = await list_tabs(ctrl, ListTabsInput(project_name="alpha"))
    assert [t["title"] for t in result["tabs"]] == ["vim"]
    assert result["tabs"][0]["project"] == "alpha"


async def test_list_tabs_unknown_project_raises():
    ctrl = FakeController()
    with pytest.raises(ProjectNotFound):
        await list_tabs(ctrl, ListTabsInput(project_name="nope"))
```

- [ ] **Step 2: Run test, expect failure**

Run: `uv run pytest tests/test_mcp_tools.py -v`
Expected: ImportError on `list_tabs`/`ListTabsInput`.

- [ ] **Step 3: Append the tool implementation**

Append to `src/jfterm/mcp_tools.py`:

```python
class ListTabsInput(BaseModel):
    project_name: str | None = None


async def list_tabs(controller: MCPController, params: ListTabsInput) -> dict:
    return {
        "tabs": [asdict(t) for t in controller.list_tabs(params.project_name)],
    }
```

- [ ] **Step 4: Run test, expect pass**

Run: `uv run pytest tests/test_mcp_tools.py -v`
Expected: 5 passed total.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/mcp_tools.py tests/test_mcp_tools.py
git commit -m "feat(mcp): list_tabs tool"
```

---

## Task 6: `spawn_tab` tool — TDD

**Files:**
- Modify: `src/jfterm/mcp_tools.py`
- Modify: `tests/test_mcp_tools.py`

- [ ] **Step 1: Append failing tests**

```python
from jfterm.mcp_tools import spawn_tab, SpawnTabInput
from jfterm.mcp_types import EmptyCommand


async def test_spawn_tab_returns_new_tab_and_records():
    ctrl = FakeController()
    ctrl.add_project("alpha", "/a")
    result = await spawn_tab(
        ctrl, SpawnTabInput(project_name="alpha", command="vim README.md")
    )
    assert result["tab"]["title"] == "vim README.md"
    assert result["tab"]["project"] == "alpha"
    assert result["tab"]["launched_command"] == "vim README.md"
    assert ctrl.spawn_log == [("alpha", "vim README.md")]


async def test_spawn_tab_empty_command_raises():
    ctrl = FakeController()
    ctrl.add_project("alpha", "/a")
    with pytest.raises(EmptyCommand):
        await spawn_tab(ctrl, SpawnTabInput(project_name="alpha", command=""))


async def test_spawn_tab_unknown_project_raises():
    ctrl = FakeController()
    with pytest.raises(ProjectNotFound):
        await spawn_tab(ctrl, SpawnTabInput(project_name="nope", command="ls"))
```

- [ ] **Step 2: Run test, expect failure**

Run: `uv run pytest tests/test_mcp_tools.py -v`
Expected: ImportError on `spawn_tab`/`SpawnTabInput`.

- [ ] **Step 3: Append the tool**

```python
class SpawnTabInput(BaseModel):
    project_name: str
    command: str


async def spawn_tab(controller: MCPController, params: SpawnTabInput) -> dict:
    tab = controller.spawn_tab(params.project_name, params.command)
    return {"tab": asdict(tab)}
```

- [ ] **Step 4: Run test, expect pass**

Run: `uv run pytest tests/test_mcp_tools.py -v`
Expected: 8 passed total.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/mcp_tools.py tests/test_mcp_tools.py
git commit -m "feat(mcp): spawn_tab tool"
```

---

## Task 7: `restart_tab` tool — TDD

**Files:**
- Modify: `src/jfterm/mcp_tools.py`
- Modify: `tests/test_mcp_tools.py`

- [ ] **Step 1: Append failing tests**

```python
from jfterm.mcp_tools import restart_tab, RestartTabInput
from jfterm.mcp_types import TabHasNoCommand, TabNotFound


async def test_restart_tab_records_and_returns_tab():
    ctrl = FakeController()
    ctrl.add_project("alpha", "/a")
    spawned = ctrl.add_tab("alpha", "mix phx.server", launched_command="mix phx.server")
    result = await restart_tab(ctrl, RestartTabInput(id=spawned.id))
    assert result["tab"]["id"] == spawned.id
    assert ctrl.restart_log == [spawned.id]


async def test_restart_tab_unknown_id_raises():
    ctrl = FakeController()
    with pytest.raises(TabNotFound):
        await restart_tab(ctrl, RestartTabInput(id="bogus"))


async def test_restart_tab_without_launched_command_raises():
    ctrl = FakeController()
    ctrl.add_project("alpha", "/a")
    plain = ctrl.add_tab("alpha", "shell", launched_command=None)
    with pytest.raises(TabHasNoCommand):
        await restart_tab(ctrl, RestartTabInput(id=plain.id))
```

- [ ] **Step 2: Run test, expect failure**

Run: `uv run pytest tests/test_mcp_tools.py -v`
Expected: ImportError on `restart_tab`/`RestartTabInput`.

- [ ] **Step 3: Append the tool**

```python
class RestartTabInput(BaseModel):
    id: str


async def restart_tab(controller: MCPController, params: RestartTabInput) -> dict:
    tab = controller.restart_tab(params.id)
    return {"tab": asdict(tab)}
```

- [ ] **Step 4: Run test, expect pass**

Run: `uv run pytest tests/test_mcp_tools.py -v`
Expected: 11 passed total.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/mcp_tools.py tests/test_mcp_tools.py
git commit -m "feat(mcp): restart_tab tool"
```

---

## Task 8: FastMCP server registration + thread runner

**Files:**
- Create: `src/jfterm/mcp_server.py`

This task only registers the tools and exposes a `start(controller, port)` /
`stop()` API. Smoke test comes in Task 9.

- [ ] **Step 1: Write the module**

```python
"""Embedded MCP server for JFTerm.

Wires the pure tool functions in mcp_tools to a FastMCP instance and
runs streamable-HTTP on a daemon thread bound to 127.0.0.1.
"""

from __future__ import annotations

import logging
import threading

from mcp.server.fastmcp import FastMCP

from jfterm.mcp_tools import (
    ListProjectsInput,
    ListTabsInput,
    RestartTabInput,
    SpawnTabInput,
    list_projects,
    list_tabs,
    restart_tab,
    spawn_tab,
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
    async def restart_tab_tool(id: str) -> dict:
        """Restart a tab in place. Only valid for tabs spawned with a startup command."""
        try:
            return await restart_tab(controller, RestartTabInput(id=id))
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

        def _run() -> None:
            try:
                mcp.run(transport="streamable-http", host=self._host, port=self._port)
            except OSError as e:
                log.warning("MCP server failed to bind %s:%d: %s", self._host, self._port, e)
            except Exception:
                log.exception("MCP server crashed")

        self._thread = threading.Thread(target=_run, name="jfterm-mcp", daemon=True)
        self._thread.start()
        log.info("MCP server starting on http://%s:%d/mcp", self._host, self._port)
```

(No `stop()` for MVP — daemon thread dies with the process. A clean
shutdown story belongs with the prefs/enable-disable follow-up.)

- [ ] **Step 2: Verify it imports**

Run: `uv run python -c "from jfterm.mcp_server import build_server, MCPServerThread; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/jfterm/mcp_server.py
git commit -m "feat(mcp): FastMCP server registration and thread runner"
```

---

## Task 9: HTTP smoke test

**Files:**
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the smoke test**

```python
"""End-to-end smoke test: start the real FastMCP server, do a real MCP
handshake, call tools/list and tools/call over HTTP."""

from __future__ import annotations

import asyncio
import socket
from contextlib import closing

import pytest
import pytest_asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from jfterm.mcp_server import MCPServerThread
from tests.fakes import FakeController


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.05)
    raise TimeoutError(f"server never bound to {host}:{port}")


@pytest_asyncio.fixture
async def running_server():
    ctrl = FakeController()
    ctrl.add_project("alpha", "/a")
    port = _free_port()
    server = MCPServerThread(ctrl, host="127.0.0.1", port=port)
    server.start()
    await _wait_for_port("127.0.0.1", port)
    yield ctrl, port


async def test_initialize_and_list_tools(running_server):
    _ctrl, port = running_server
    url = f"http://127.0.0.1:{port}/mcp"
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {
                "list_projects_tool",
                "list_tabs_tool",
                "spawn_tab_tool",
                "restart_tab_tool",
            } <= names


async def test_spawn_tab_round_trip(running_server):
    ctrl, port = running_server
    url = f"http://127.0.0.1:{port}/mcp"
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool(
                "spawn_tab_tool",
                arguments={"project_name": "alpha", "command": "vim"},
            )
    assert ctrl.spawn_log == [("alpha", "vim")]
```

Note: the SDK's import name is either `streamablehttp_client` or
`streamable_http_client`. Use whichever Task 1 Step 3 confirmed; if the
test fails on import, swap to the other name in both the import line
and any usage. Don't pivot to a different transport.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_mcp_server.py -v`
Expected: 2 passed. The server thread is a daemon so test exit doesn't hang.

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_server.py
git commit -m "test(mcp): HTTP round-trip smoke test"
```

---

## Task 10: GTK adapter — `GtkMCPController`

**Files:**
- Create: `src/jfterm/mcp_gtk.py`
- Modify: `src/jfterm/window.py` — add helpers used by the controller.

- [ ] **Step 1: Add helper methods to `JFTermWindow`**

In `src/jfterm/window.py`, add these methods on `JFTermWindow` (keep existing methods unchanged). Place them near the other private helpers:

```python
def mcp_list_projects(self) -> list["ProjectInfo"]:
    from jfterm.mcp_types import ProjectInfo

    out: list[ProjectInfo] = []
    for g in self.ws.all_groups():
        directory = g.directory if isinstance(g, Project) else ""
        out.append(ProjectInfo(name=g.name, directory=directory, tab_count=len(g.tabs)))
    return out

def mcp_list_tabs(self, project_name: str | None) -> list["TabInfo"]:
    from jfterm.mcp_types import ProjectNotFound, TabInfo

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

def _tab_to_info(self, tab: Tab, project_name: str) -> "TabInfo":
    from jfterm.mcp_types import TabInfo

    return TabInfo(
        id=tab.id,
        title=tab.title,
        project=project_name,
        cwd=tab.current_cwd,
        busy=tab.is_running,
        launched_command=tab.launched_command,
    )

def mcp_spawn_tab(self, project_name: str, command: str) -> "TabInfo":
    from jfterm.mcp_types import EmptyCommand, ProjectNotFound

    if not command:
        raise EmptyCommand()
    group = next((g for g in self.ws.all_groups() if g.name == project_name), None)
    if group is None:
        raise ProjectNotFound(project_name)
    tab = self._spawn_tab(group, command=command, focus=False)
    return self._tab_to_info(tab, group.name)

def mcp_restart_tab(self, tab_id: str) -> "TabInfo":
    from jfterm.mcp_types import TabHasNoCommand, TabNotFound

    for g in self.ws.all_groups():
        for t in g.tabs:
            if t.id == tab_id:
                if not t.launched_command:
                    raise TabHasNoCommand(tab_id)
                self._on_restart_tab(self.sidebar, t)
                return self._tab_to_info(t, g.name)
    raise TabNotFound(tab_id)
```

These run on the GTK thread — they read/mutate the workspace directly.
The `from … import` lines inside the methods avoid a circular import at
module load time.

- [ ] **Step 2: Write the adapter**

Create `src/jfterm/mcp_gtk.py`:

```python
"""GTK adapter implementing MCPController.

The MCP server runs tools on its own asyncio thread (inside the daemon
thread spawned by MCPServerThread). All workspace mutations have to
happen on the GTK main thread, so each method bounces a callable onto
GLib.idle_add and blocks on a Future for the result.
"""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from gi.repository import GLib

from jfterm.mcp_types import MCPController, ProjectInfo, TabInfo

if TYPE_CHECKING:
    from jfterm.window import JFTermWindow

T = TypeVar("T")

# Hard ceiling so a wedged GTK thread can't permanently hang the MCP
# request handler. 10s is generous for a UI-thread operation.
_GTK_CALL_TIMEOUT = 10.0


def _on_gtk_thread(thunk: Callable[[], T]) -> T:
    fut: concurrent.futures.Future[T] = concurrent.futures.Future()

    def _run() -> bool:
        try:
            fut.set_result(thunk())
        except BaseException as e:  # noqa: BLE001 — propagate every failure
            fut.set_exception(e)
        return False  # GLib.SOURCE_REMOVE

    GLib.idle_add(_run)
    return fut.result(timeout=_GTK_CALL_TIMEOUT)


class GtkMCPController(MCPController):
    def __init__(self, window: "JFTermWindow") -> None:
        self._window = window

    def list_projects(self) -> list[ProjectInfo]:
        return _on_gtk_thread(self._window.mcp_list_projects)

    def list_tabs(self, project_name: str | None) -> list[TabInfo]:
        return _on_gtk_thread(lambda: self._window.mcp_list_tabs(project_name))

    def spawn_tab(self, project_name: str, command: str) -> TabInfo:
        return _on_gtk_thread(lambda: self._window.mcp_spawn_tab(project_name, command))

    def restart_tab(self, tab_id: str) -> TabInfo:
        return _on_gtk_thread(lambda: self._window.mcp_restart_tab(tab_id))
```

- [ ] **Step 3: Verify imports**

Run: `uv run python -c "from jfterm.mcp_gtk import GtkMCPController; print('ok')"`
Expected: `ok` (the module imports `gi.repository.GLib`; the venv has system PyGObject).

- [ ] **Step 4: Run the existing tool tests to confirm no regression**

Run: `uv run pytest tests/test_mcp_tools.py tests/test_mcp_server.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/mcp_gtk.py src/jfterm/window.py
git commit -m "feat(mcp): GTK controller adapter with idle_add bridging"
```

---

## Task 11: Wire server into `JFTermWindow`

**Files:**
- Modify: `src/jfterm/window.py`

- [ ] **Step 1: Start the server in `__init__`**

In `src/jfterm/window.py`, near the end of `JFTermWindow.__init__`, add:

```python
        # Embedded MCP server. See docs/superpowers/specs/2026-05-06-mcp-server-design.md.
        # Hardcoded to 127.0.0.1:7820 for MVP; prefs UI is a follow-up.
        from jfterm.mcp_gtk import GtkMCPController
        from jfterm.mcp_server import MCPServerThread

        self._mcp_controller = GtkMCPController(self)
        self._mcp_server = MCPServerThread(self._mcp_controller)
        self._mcp_server.start()
```

- [ ] **Step 2: Run the full test suite**

Run: `uv run just check`
Expected: lint, format, typecheck, and tests all pass.

- [ ] **Step 3: Smoke-test by hand**

Run: `uv run jfterm` (or `just run`).
Expected: app launches normally; the log line "MCP server starting on http://127.0.0.1:7820/mcp" appears in the terminal.

In another terminal:

```bash
curl -sS -X POST http://127.0.0.1:7820/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

Expected: a JSON-RPC response with `serverInfo.name == "jfterm"`. (If the
SDK requires a session id flow that curl can't easily do, skip the curl
check — the smoke test in Task 9 already proves the round trip works.)

Quit the app.

- [ ] **Step 4: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(mcp): start MCP server with the main window"
```

---

## Task 12: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a section**

Append a short section to `README.md` after "Shell integration" and before "Development":

```markdown
## MCP server (Claude Code integration)

JFTerm exposes a small MCP server at `http://127.0.0.1:7820/mcp` so
Claude Code (or any MCP client) running inside a tab can drive JFTerm.
Connect Claude Code with:

    claude mcp add --transport http jfterm http://127.0.0.1:7820/mcp

Tools available in this MVP:

- `list_projects_tool` — projects with name, directory, and tab count.
- `list_tabs_tool(project_name?)` — all tabs, or filtered to one project.
- `spawn_tab_tool(project_name, command)` — spawn a tab running `command`.
- `restart_tab_tool(id)` — restart a tab spawned with a startup command.

The server binds to localhost only and has no authentication. A
preferences UI to enable/disable it and pick a port is on the roadmap;
see issue #20.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): document MCP server"
```

---

## Final verification

- [ ] Run `uv run just check` — all green.
- [ ] Manually confirm `claude mcp add --transport http jfterm http://127.0.0.1:7820/mcp` then `claude` invocation can list and call the tools.
