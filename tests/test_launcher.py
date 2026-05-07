"""Smoke tests for the launcher widget — exercise pure helpers only,
no GTK main loop."""

from jfterm.launcher import Launcher
from jfterm.launcher_items import FlashAction, NewTabAction, build_items
from jfterm.models import FlashCommand, Workspace


def test_launcher_filter_returns_ranked_items():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    p.flash_commands.append(FlashCommand(name="Push", command="git push"))
    items = build_items(ws)
    out = Launcher.filter_items("alpha push", items)
    assert any(isinstance(i.action, FlashAction) for i in out)
    assert isinstance(out[0].action, FlashAction)
    assert out[0].action.flash.name == "Push"


def test_launcher_filter_empty_query_returns_nothing():
    ws = Workspace()
    ws.add_project(name="Alpha", directory="/tmp/a")
    items = build_items(ws)
    assert Launcher.filter_items("", items) == []


def test_launcher_recents_dedupe_and_cap():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    a = NewTabAction(p)
    recents: list = []
    Launcher.push_recent(recents, a, max_recents=3)
    Launcher.push_recent(recents, a, max_recents=3)  # dedup
    assert recents == [a]
    p2 = ws.add_project(name="Beta", directory="/tmp/b")
    p3 = ws.add_project(name="Gamma", directory="/tmp/g")
    p4 = ws.add_project(name="Delta", directory="/tmp/d")
    Launcher.push_recent(recents, NewTabAction(p2), max_recents=3)
    Launcher.push_recent(recents, NewTabAction(p3), max_recents=3)
    Launcher.push_recent(recents, NewTabAction(p4), max_recents=3)
    assert len(recents) == 3
    assert recents[0] == NewTabAction(p4)


def test_launcher_recents_filter_drops_stale_actions():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    fresh = NewTabAction(p)
    p2_proj = ws.add_project(name="Beta", directory="/tmp/b")
    stale = NewTabAction(p2_proj)
    ws.projects.remove(p2_proj)
    items = build_items(ws)
    out = Launcher.recents_in_items([fresh, stale], items)
    assert out == [fresh]
