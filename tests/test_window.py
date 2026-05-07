"""Window logic tests that don't require a running GTK loop.

We construct a minimal stand-in for the parts of JFTermWindow that
_on_close_tab actually touches, and assert the early-return behaviour.
"""

from types import SimpleNamespace

from jfterm.models import TerminalTab, Workspace
from jfterm.window import JFTermWindow


def test_on_close_tab_is_noop_when_tab_is_restarting():
    ws = Workspace()
    p = ws.add_project(name="A", directory="/tmp/a")
    tab = TerminalTab(title="x")
    p.add_tab(tab)
    tab.is_restarting = True

    fake_self = SimpleNamespace(
        ws=ws,
        terminal_stack=None,
        sidebar=SimpleNamespace(refresh=lambda: None),
        _current_group=p,
        _show_group_empty=lambda g: None,
    )

    JFTermWindow._on_close_tab(fake_self, None, tab)  # pyright: ignore[reportArgumentType]

    assert tab in p.tabs, "tab should not be removed while is_restarting is True"


def test_on_project_dropped_reorders_and_persists(tmp_path, monkeypatch):
    from jfterm import persistence
    from jfterm.window import JFTermWindow

    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    ws.add_project(name="B", directory="/tmp/b")
    c = ws.add_project(name="C", directory="/tmp/c")

    saves: list[Workspace] = []
    monkeypatch.setattr(persistence, "default_path", lambda: tmp_path / "p.json")
    monkeypatch.setattr(
        "jfterm.window.save_projects",
        lambda workspace, path: saves.append(workspace),
    )

    refreshes: list[int] = []
    fake_self = SimpleNamespace(
        ws=ws,
        sidebar=SimpleNamespace(refresh=lambda: refreshes.append(1)),
    )

    JFTermWindow._on_project_dropped(fake_self, None, c, 0)  # pyright: ignore[reportArgumentType]
    assert [p.name for p in ws.active_projects] == ["C", "A", "B"]

    JFTermWindow._on_project_dropped(fake_self, None, a, 3)  # pyright: ignore[reportArgumentType]
    assert [p.name for p in ws.active_projects] == ["C", "B", "A"]

    assert len(saves) == 2
    assert len(refreshes) == 2
