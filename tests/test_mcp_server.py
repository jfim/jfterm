"""End-to-end smoke test: start the real FastMCP server, do a real MCP
handshake, call tools/list and tools/call over HTTP."""

from __future__ import annotations

import asyncio
import socket
import urllib.error
import urllib.request
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


@pytest_asyncio.fixture
async def authed_server():
    ctrl = FakeController()
    ctrl.add_project("alpha", "/a")
    port = _free_port()
    token = "test-token-abc123"
    server = MCPServerThread(ctrl, host="127.0.0.1", port=port, token=token)
    server.start()
    await _wait_for_port("127.0.0.1", port)
    yield ctrl, port, token


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


def _post_initialize(url: str, headers: dict[str, str]) -> int:
    """POST a minimal MCP initialize body and return HTTP status code.

    We use urllib (sync) rather than the MCP client because the client
    raises on non-2xx and obscures the status code; for auth tests we
    care exactly about the 401-vs-200 distinction.
    """
    body = (
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
        b'{"protocolVersion":"2024-11-05","capabilities":{},'
        b'"clientInfo":{"name":"t","version":"0"}}}'
    )
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("accept", "application/json, text/event-stream")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_authed_server_rejects_missing_bearer(authed_server):
    _ctrl, port, _token = authed_server
    url = f"http://127.0.0.1:{port}/mcp"
    assert _post_initialize(url, headers={}) == 401


def test_authed_server_rejects_wrong_bearer(authed_server):
    _ctrl, port, _token = authed_server
    url = f"http://127.0.0.1:{port}/mcp"
    status = _post_initialize(url, headers={"Authorization": "Bearer wrong"})
    assert status == 401


def test_authed_server_rejects_non_bearer_scheme(authed_server):
    _ctrl, port, token = authed_server
    url = f"http://127.0.0.1:{port}/mcp"
    status = _post_initialize(url, headers={"Authorization": f"Basic {token}"})
    assert status == 401


async def test_authed_server_accepts_correct_bearer(authed_server):
    ctrl, port, token = authed_server
    url = f"http://127.0.0.1:{port}/mcp"
    async with (
        streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (
            read,
            write,
            _,
        ),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        await session.call_tool(
            "spawn_tab_tool",
            arguments={"project_name": "alpha", "command": "vim"},
        )
    assert ctrl.spawn_log == [("alpha", "vim")]
