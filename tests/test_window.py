"""Window logic tests that don't require a running GTK loop.

We construct a minimal stand-in for the parts of JFTermWindow that
_on_close_tab actually touches, and assert the early-return behaviour.
"""
from types import SimpleNamespace

from jfterm.models import Tab, Workspace
from jfterm.window import JFTermWindow


def test_on_close_tab_is_noop_when_tab_is_restarting():
    ws = Workspace()
    p = ws.add_project(name="A", directory="/tmp/a")
    tab = Tab(title="x")
    p.add_tab(tab)
    tab.is_restarting = True

    # Stand-in window: only the attributes _on_close_tab references when
    # short-circuiting on is_restarting.
    fake_self = SimpleNamespace(
        ws=ws,
        terminal_stack=None,
        sidebar=SimpleNamespace(refresh=lambda: None),
        _current_group=p,
        _show_group_empty=lambda g: None,
    )

    JFTermWindow._on_close_tab(fake_self, None, tab)

    assert tab in p.tabs, "tab should not be removed while is_restarting is True"
