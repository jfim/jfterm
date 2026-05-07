"""Unit tests for the pure tool layer (no SDK, no GTK)."""

from __future__ import annotations

import pytest
from tests.fakes import FakeController

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
from jfterm.mcp_types import (
    EmptyCommand,
    ProjectNotFound,
    TabHasNoCommand,
    TabNotFound,
)


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


async def test_spawn_tab_returns_new_tab_and_records():
    ctrl = FakeController()
    ctrl.add_project("alpha", "/a")
    result = await spawn_tab(ctrl, SpawnTabInput(project_name="alpha", command="vim README.md"))
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
