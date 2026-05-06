from jfterm.models import Project, Tab, Workspace


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
    t = Tab(title="x")
    p.add_tab(t)
    assert p.tabs == [t]


def test_disband_moves_tabs_to_end_of_unsorted():
    ws = Workspace()
    p = ws.add_project(name="A", directory="/tmp/a")
    t1 = Tab(title="from-A")
    p.add_tab(t1)
    pre_existing = Tab(title="already-unsorted")
    ws.unsorted.add_tab(pre_existing)

    ws.disband(p)

    assert p not in ws.projects
    assert ws.unsorted.tabs == [pre_existing, t1]


def test_move_tab_between_groups():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    b = ws.add_project(name="B", directory="/tmp/b")
    t = Tab(title="x")
    a.add_tab(t)

    ws.move_tab(t, b, position=0)

    assert a.tabs == []
    assert b.tabs == [t]


def test_reorder_tab_within_group():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    t1, t2, t3 = Tab(title="1"), Tab(title="2"), Tab(title="3")
    for t in (t1, t2, t3):
        a.add_tab(t)

    ws.move_tab(t3, a, position=0)
    assert [t.title for t in a.tabs] == ["3", "1", "2"]
