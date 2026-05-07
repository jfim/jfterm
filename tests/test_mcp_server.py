"""End-to-end smoke test: start the real FastMCP server, do a real MCP
handshake, call tools/list and tools/call over HTTP."""

from __future__ import annotations

import asyncio
import socket
from contextlib import closing

import pytest_asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from tests.fakes import FakeController

from jfterm.mcp_server import MCPServerThread


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            _reader, writer = await asyncio.open_connection(host, port)
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
    async with (
        streamablehttp_client(url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
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
    async with (
        streamablehttp_client(url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        await session.call_tool(
            "spawn_tab_tool",
            arguments={"project_name": "alpha", "command": "vim"},
        )
    assert ctrl.spawn_log == [("alpha", "vim")]
