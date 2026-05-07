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
