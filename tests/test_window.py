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
