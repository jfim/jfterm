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

    class FakeSaver:
        def schedule(self) -> None:
            saves.append(ws)

    refreshes: list[int] = []
    fake_self = SimpleNamespace(
        ws=ws,
        sidebar=SimpleNamespace(refresh=lambda: refreshes.append(1)),
        _project_saver=FakeSaver(),
    )

    JFTermWindow._on_project_dropped(fake_self, None, c, 0)  # pyright: ignore[reportArgumentType]
    assert [p.name for p in ws.active_projects] == ["C", "A", "B"]

    JFTermWindow._on_project_dropped(fake_self, None, a, 3)  # pyright: ignore[reportArgumentType]
    assert [p.name for p in ws.active_projects] == ["C", "B", "A"]

    assert len(saves) == 2
    assert len(refreshes) == 2


def test_dispatch_launcher_action_routes_to_existing_handlers():
    from jfterm.launcher_items import (
        FlashAction,
        JumpAction,
        NewTabAction,
        NewWebTabAction,
        StartupAction,
    )
    from jfterm.models import FlashCommand

    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    fc = FlashCommand(name="Push", command="git push")
    tab = TerminalTab(title="bash")
    p.add_tab(tab)

    calls: list[tuple] = []
    fake = SimpleNamespace(
        ws=ws,
        sidebar=object(),
        _on_flash_command_launched=lambda sb, proj, f: calls.append(("flash", proj, f)),
        _spawn_tab=lambda group: calls.append(("new", group)),
        _on_new_web_tab=lambda sb, group, url: calls.append(("web", group, url)),
        _on_launch_project=lambda sb, proj: calls.append(("startup", proj)),
        _on_tab_activated=lambda sb, t: calls.append(("jump", t)),
    )

    JFTermWindow._dispatch_launcher_action(fake, FlashAction(p, fc))  # pyright: ignore[reportArgumentType]
    JFTermWindow._dispatch_launcher_action(fake, NewTabAction(p))  # pyright: ignore[reportArgumentType]
    JFTermWindow._dispatch_launcher_action(fake, NewWebTabAction(p))  # pyright: ignore[reportArgumentType]
    JFTermWindow._dispatch_launcher_action(fake, StartupAction(p))  # pyright: ignore[reportArgumentType]
    JFTermWindow._dispatch_launcher_action(fake, JumpAction(tab))  # pyright: ignore[reportArgumentType]

    assert calls == [
        ("flash", p, fc),
        ("new", p),
        ("web", p, ""),
        ("startup", p),
        ("jump", tab),
    ]


def test_adopt_session_appends_terminal_tab_to_unsorted():
    ws = Workspace()
    created = []

    def fake_materialize(info):
        tab = SimpleNamespace(session_id=info["session_id"], title=info.get("argv", ["?"])[0])
        ws.unsorted.tabs.append(tab)
        created.append(tab)
        return tab

    fake_self = SimpleNamespace(
        ws=ws,
        _materialize_adopted_tab=fake_materialize,
    )
    sessions = [
        {"session_id": "s1", "argv": ["bash"], "cwd": "/tmp"},
        {"session_id": "s2", "argv": ["vim"], "cwd": "/home"},
    ]
    JFTermWindow._adopt_sessions(fake_self, sessions)  # pyright: ignore[reportArgumentType]
    assert [t.session_id for t in ws.unsorted.tabs] == ["s1", "s2"]


def test_close_request_detaches_all_sessions():
    ws = Workspace()
    p = ws.add_project(name="A", directory="/tmp/a")
    detached = []

    class FakeProxy:
        def detach(self):
            detached.append(self)

    class FakeTerm:
        def __init__(self):
            self._proxy = FakeProxy()

    t1 = SimpleNamespace(terminal=FakeTerm())
    t2 = SimpleNamespace(terminal=FakeTerm())
    p.tabs.extend([t1, t2])

    fake_self = SimpleNamespace(
        ws=ws,
        _window_save_source=None,
        _persist_window_geometry=lambda: None,
        _muxer=SimpleNamespace(close=lambda: None),
        _project_saver=SimpleNamespace(flush=lambda timeout=0: None),
    )
    result = JFTermWindow._on_close_request(fake_self, None)  # pyright: ignore[reportArgumentType]
    assert result is False
    assert len(detached) == 2
