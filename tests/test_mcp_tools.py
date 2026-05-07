"""Unit tests for the pure tool layer (no SDK, no GTK)."""

from __future__ import annotations

import pytest

from jfterm.mcp_tools import (
    list_projects,
    list_tabs,
    ListProjectsInput,
    ListTabsInput,
)
from jfterm.mcp_types import ProjectNotFound
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
