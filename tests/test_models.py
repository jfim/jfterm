import pytest

from jfterm.models import (
    FlashCommand,
    Project,
    Tab,
    TerminalTab,
    WebTab,
    Workspace,
)


def test_workspace_starts_empty_with_unsorted_only():
    ws = Workspace()
    assert ws.projects == []
    assert ws.unsorted.tabs == []


def test_add_project_appends():
    ws = Workspace()
    p = ws.add_project(name="A", directory="/tmp/a")
    assert ws.projects == [p]
    assert p.name == "A"
    assert p.directory == "/tmp/a"
    assert p.expanded is True


def test_add_tab_to_project():
    ws = Workspace()
    p = ws.add_project(name="A", directory="/tmp/a")
    t = TerminalTab(title="x")
    p.add_tab(t)
    assert p.tabs == [t]


def test_disband_moves_tabs_to_end_of_unsorted():
    ws = Workspace()
    p = ws.add_project(name="A", directory="/tmp/a")
    t1 = TerminalTab(title="from-A")
    p.add_tab(t1)
    pre_existing = TerminalTab(title="already-unsorted")
    ws.unsorted.add_tab(pre_existing)

    ws.disband(p)

    assert p not in ws.projects
    assert ws.unsorted.tabs == [pre_existing, t1]


def test_move_tab_between_groups():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    b = ws.add_project(name="B", directory="/tmp/b")
    t = TerminalTab(title="x")
    a.add_tab(t)

    ws.move_tab(t, b, position=0)

    assert a.tabs == []
    assert b.tabs == [t]


def test_terminal_tab_is_a_tab():
    t = TerminalTab(title="x")
    assert isinstance(t, Tab)


def test_web_tab_is_a_tab():
    t = WebTab(title="x", url="https://example.com")
    assert isinstance(t, Tab)


def test_terminal_tab_widget_returns_terminal_field():
    sentinel = object()
    t = TerminalTab(title="x", terminal=sentinel)
    assert t.widget is sentinel


def test_web_tab_widget_returns_web_view_field():
    sentinel = object()
    t = WebTab(title="x", url="https://example.com", web_view=sentinel)
    assert t.widget is sentinel


def test_terminal_tab_defaults():
    t = TerminalTab()
    assert t.title == ""
    assert t.shell_pid is None
    assert t.is_running is False
    assert t.osc133_seen is False
    assert t.launched_command is None
    assert t.from_startup is False
    assert t.is_restarting is False


def test_web_tab_defaults():
    t = WebTab()
    assert t.title == ""
    assert t.url == ""
    assert t.web_view is None
    assert t.from_startup is False
    assert t.flash_name is None


def test_two_tabs_have_distinct_ids():
    a = TerminalTab()
    b = TerminalTab()
    c = WebTab()
    assert len({a.id, b.id, c.id}) == 3


def test_flash_command_defaults():
    fc = FlashCommand(name="x", command="y")
    assert fc.keep_open_on_success is False
    assert fc.focus_on_launch is True


def test_project_with_flash_commands_in_ctor():
    fcs = [FlashCommand(name="a", command="echo a")]
    p = Project(name="P", directory="/tmp/p", flash_commands=fcs)
    assert p.flash_commands == fcs


def test_project_accepts_flash_commands():
    fc = FlashCommand(name="Push", command="git push", keep_open_on_success=True)
    p = Project(name="A", directory="/tmp/a", flash_commands=[fc])
    assert p.flash_commands == [fc]


def test_project_archived_defaults_to_false():
    p = Project(name="A", directory="/tmp/a")
    assert p.archived is False


def test_workspace_active_and_archived_views():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    b = ws.add_project(name="B", directory="/tmp/b")
    c = ws.add_project(name="C", directory="/tmp/c")

    b.archived = True

    assert ws.active_projects == [a, c]
    assert ws.archived_projects == [b]
    assert ws.projects == [a, b, c]


def test_unarchive_restores_position_in_active_view():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    b = ws.add_project(name="B", directory="/tmp/b")
    c = ws.add_project(name="C", directory="/tmp/c")

    b.archived = True
    assert ws.active_projects == [a, c]

    b.archived = False
    assert ws.active_projects == [a, b, c]


def test_workspace_archived_expanded_defaults_to_false():
    ws = Workspace()
    assert ws.archived_expanded is False


def test_base_tab_widget_raises():
    t = Tab(title="x")
    with pytest.raises(NotImplementedError):
        _ = t.widget


def test_move_project_reorders_active_projects():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    b = ws.add_project(name="B", directory="/tmp/b")
    c = ws.add_project(name="C", directory="/tmp/c")

    ws.move_project(c, 0)

    assert [p.name for p in ws.active_projects] == ["C", "A", "B"]


def test_move_project_preserves_archived_positions():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    z = ws.add_project(name="Z", directory="/tmp/z")
    z.archived = True
    b = ws.add_project(name="B", directory="/tmp/b")
    c = ws.add_project(name="C", directory="/tmp/c")

    ws.move_project(c, 0)

    assert [p.name for p in ws.active_projects] == ["C", "A", "B"]
    assert [p.name for p in ws.archived_projects] == ["Z"]
    assert [p.name for p in ws.projects] == ["C", "A", "Z", "B"]


def test_move_project_to_end_appends():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    b = ws.add_project(name="B", directory="/tmp/b")
    c = ws.add_project(name="C", directory="/tmp/c")

    ws.move_project(a, 2)

    assert [p.name for p in ws.active_projects] == ["B", "C", "A"]


def test_move_project_to_same_position_is_noop():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    b = ws.add_project(name="B", directory="/tmp/b")

    ws.move_project(a, 0)

    assert [p.name for p in ws.active_projects] == ["A", "B"]


def test_move_project_rejects_archived_project():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    a.archived = True

    with pytest.raises(ValueError):
        ws.move_project(a, 0)


def test_move_project_rejects_out_of_range_position():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    b = ws.add_project(name="B", directory="/tmp/b")

    with pytest.raises(ValueError):
        ws.move_project(a, 5)
    with pytest.raises(ValueError):
        ws.move_project(a, -1)
