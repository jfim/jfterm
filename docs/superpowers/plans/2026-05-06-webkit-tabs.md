# Webkit tabs implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second tab kind (WebKitGTK web view) to JFTerm. Startup/flash commands beginning with `http(s)://` open as web tabs; right-click on a group's `+` button offers an ad-hoc "New web tab…" entry.

**Architecture:** Refactor `Tab` into a base class with `TerminalTab` and `WebTab` subclasses. A new `JFTermWebView` widget (toolbar + WebKit view) is mounted in the existing `Gtk.Stack` alongside terminals. A shared persistent `WebKit.NetworkSession` keeps cookies across tabs and runs.

**Tech Stack:** Python 3.12, PyGObject (GTK 4 / Adwaita 1 / VTE 3.91 / WebKit 6.0), pytest, pyright, ruff, uv, just.

**Spec:** [docs/superpowers/specs/2026-05-06-webkit-tabs-design.md](../specs/2026-05-06-webkit-tabs-design.md)

---

## File map

**Created:**
- `src/jfterm/url_routing.py` — `is_web_url(text)` helper
- `src/jfterm/webkit_session.py` — lazy shared `WebKit.NetworkSession`
- `src/jfterm/webtab.py` — `JFTermWebView` widget
- `typings/gi/repository/WebKit.pyi` — pyright stubs (Any-typed)
- `tests/test_url_routing.py` — `is_web_url` cases

**Modified:**
- `src/jfterm/models.py` — split `Tab` into base + `TerminalTab` + `WebTab`
- `src/jfterm/sidebar.py` — right-click on `+`, isinstance branches for dot/restart, new signal
- `src/jfterm/window.py` — `_spawn_web_tab`, routing in startup/flash paths, `tab.terminal` → `tab.widget` migration, web tab close/cycle/title plumbing, graceful degradation
- `src/jfterm/dialogs.py` — `show_new_web_tab_dialog`
- `tests/test_models.py` — update existing tests for `TerminalTab`, add `WebTab` cases
- `tests/test_window.py` — update for `TerminalTab`
- `README.md` — apt dep, Web tabs feature section

---

## Task 1: URL routing helper

**Files:**
- Create: `src/jfterm/url_routing.py`
- Test: `tests/test_url_routing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_url_routing.py`:

```python
import pytest

from jfterm.url_routing import is_web_url


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://example.com", True),
        ("http://example.com", True),
        ("HTTPS://example.com", True),
        ("HTTP://EXAMPLE.COM", True),
        ("  https://example.com  ", True),
        ("\thttp://localhost:4000\n", True),
        ("https://", True),
        ("httpsfoo://x", False),
        ("ftp://example.com", False),
        ("file:///etc/passwd", False),
        ("localhost:4000", False),
        ("", False),
        ("   ", False),
        ("npm run dev", False),
        ("echo https://example.com", False),
    ],
)
def test_is_web_url(text: str, expected: bool) -> None:
    assert is_web_url(text) is expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_url_routing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jfterm.url_routing'`.

- [ ] **Step 3: Implement the helper**

Create `src/jfterm/url_routing.py`:

```python
from __future__ import annotations

import re

_WEB_URL_RE = re.compile(r"https?://", re.IGNORECASE)


def is_web_url(text: str) -> bool:
    """Return True if `text` (after stripping) starts with http:// or https://."""
    return bool(_WEB_URL_RE.match(text.strip()))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_url_routing.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/url_routing.py tests/test_url_routing.py
git commit -m "feat(routing): add is_web_url helper"
```

---

## Task 2: Tab model refactor

Split `Tab` into a base + `TerminalTab` + `WebTab`. All call sites migrate from `Tab(...)` to `TerminalTab(...)`. The `widget` property replaces direct reads of `tab.terminal` for stack-mounting purposes (terminal-specific accesses keep using `tab.terminal`).

**Files:**
- Modify: `src/jfterm/models.py`
- Modify: `src/jfterm/window.py`
- Modify: `src/jfterm/sidebar.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_window.py`

- [ ] **Step 1: Update `tests/test_models.py` to fail against the new shape**

Replace the `Tab(...)` usages with `TerminalTab(...)` and add subclass tests. Replace the file with:

```python
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


def test_base_tab_widget_raises():
    t = Tab(title="x")
    with pytest.raises(NotImplementedError):
        _ = t.widget
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: ImportError on `TerminalTab`/`WebTab`.

- [ ] **Step 3: Refactor `src/jfterm/models.py`**

Replace lines 27–52 (the existing `@dataclass class Tab` block) with the base + two subclasses. The full new file:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StartupCommand:
    """A command to run when launching a project, with a post-spawn delay
    (in seconds) before the next command is spawned."""

    command: str
    delay: int = 0


@dataclass
class FlashCommand:
    """A one-shot command launched from the project's flash menu."""

    name: str
    command: str
    keep_open_on_success: bool = False
    focus_on_launch: bool = True


@dataclass
class Tab:
    """Base class for a tab. Concrete subclasses below mount different
    widgets (a VTE terminal or a WebKit view) in the window's stack."""

    title: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # Sidebar attaches the row's StatusDot here for terminal tabs so the
    # runtime layer can update its visual state without a full sidebar refresh.
    # Web tabs leave this None.
    _dot: Any = None

    @property
    def widget(self) -> Any:
        """The GTK widget mounted in the window's terminal_stack."""
        raise NotImplementedError


@dataclass
class TerminalTab(Tab):
    # Runtime-only fields populated when a real terminal is attached:
    terminal: Any = None
    shell_pid: int | None = None
    pty_fd: int | None = None
    current_cwd: str | None = None
    is_running: bool = False
    osc133_seen: bool = False
    # The startup command this tab was launched with (None for plain shells).
    # Set once at spawn time and reused on restart.
    launched_command: str | None = None
    # Display name of the flash command this tab was launched with (None if
    # not a flash tab). Used to prefix the tab title with "⚡ {name}: ".
    flash_name: str | None = None
    # True when launched from a project's startup commands. Used to prefix
    # the tab title with "▶ ".
    from_startup: bool = False
    # True while a restart is in flight, so the old terminal's child-exited
    # signal does not remove the tab from its group.
    is_restarting: bool = False

    @property
    def widget(self) -> Any:
        return self.terminal


@dataclass
class WebTab(Tab):
    # The URL the tab was launched with — used as title fallback and for the
    # "skip if already running" check during project launch.
    url: str = ""
    # The JFTermWebView widget mounted in the stack.
    web_view: Any = None
    from_startup: bool = False
    flash_name: str | None = None

    @property
    def widget(self) -> Any:
        return self.web_view


class Group:
    """Either a Project or the Unsorted singleton. Owns an ordered tab list."""

    name: str

    def __init__(self) -> None:
        self.tabs: list[Tab] = []
        self.expanded: bool = True

    def add_tab(self, tab: Tab, position: int | None = None) -> None:
        if position is None:
            self.tabs.append(tab)
        else:
            self.tabs.insert(position, tab)

    def remove_tab(self, tab: Tab) -> None:
        self.tabs.remove(tab)


class Unsorted(Group):
    name = "Unsorted"


class Project(Group):
    def __init__(
        self,
        name: str,
        directory: str,
        expanded: bool = True,
        id: str | None = None,
        startup_commands: list[StartupCommand] | None = None,
        spawn_blank_after_startup: bool = False,
        flash_commands: list[FlashCommand] | None = None,
    ) -> None:
        super().__init__()
        self.name = name
        self.directory = directory
        self.expanded = expanded
        self.id = id if id is not None else uuid.uuid4().hex
        self.startup_commands: list[StartupCommand] = list(startup_commands or [])
        self.spawn_blank_after_startup = spawn_blank_after_startup
        self.flash_commands: list[FlashCommand] = list(flash_commands or [])
        # Forward-compat: unknown fields read from disk are preserved here
        # and re-emitted on save so older code doesn't drop newer schema keys.
        self._extra: dict[str, Any] = {}


class Workspace:
    """Top-level container: ordered project list + Unsorted singleton."""

    def __init__(self) -> None:
        self.projects: list[Project] = []
        self.unsorted = Unsorted()
        self.sidebar_width: int = 220

    def add_project(self, name: str, directory: str) -> Project:
        p = Project(name=name, directory=directory)
        self.projects.append(p)
        return p

    def disband(self, project: Project) -> None:
        self.projects.remove(project)
        for t in project.tabs:
            self.unsorted.tabs.append(t)
        project.tabs = []

    def move_tab(self, tab: Tab, dest: Group, position: int | None = None) -> None:
        src = self._find_group(tab)
        src.remove_tab(tab)
        dest.add_tab(tab, position=position)

    def _find_group(self, tab: Tab) -> Group:
        for g in (*self.projects, self.unsorted):
            if tab in g.tabs:
                return g
        raise ValueError(f"tab {tab} not in any group")

    def all_groups(self) -> list[Group]:
        return [*self.projects, self.unsorted]
```

- [ ] **Step 4: Update `src/jfterm/window.py` to instantiate `TerminalTab`**

In `window.py` line 15, change the import from:

```python
from jfterm.models import FlashCommand, Group, Project, StartupCommand, Tab, Workspace  # noqa: E402
```

to:

```python
from jfterm.models import (  # noqa: E402
    FlashCommand,
    Group,
    Project,
    StartupCommand,
    Tab,
    TerminalTab,
    Workspace,
)
```

In `_spawn_tab` (lines 117–142), change the `Tab(...)` constructor (line 128) to `TerminalTab(...)`. The whole block becomes:

```python
def _spawn_tab(
    self,
    group: Group,
    *,
    command: str | None = None,
    focus: bool = True,
) -> TerminalTab:
    cwd = group.directory if isinstance(group, Project) else None
    terminal = JFTermTerminal(cwd=cwd, send_after_spawn=command)
    terminal.set_vexpand(True)
    terminal.set_hexpand(True)
    tab = TerminalTab(
        title=command or "(starting…)",
        terminal=terminal,
        launched_command=command,
    )
    self._wire_terminal(tab, terminal)
    self.terminal_stack.add_child(terminal)
    group.add_tab(tab)
    self._current_group = group
    if focus:
        self.terminal_stack.set_visible_child(terminal)
        self.sidebar.set_active_tab(tab)
        terminal.grab_focus()
    self.sidebar.refresh()
    return tab
```

In `_wire_terminal`, retype the `tab` parameter from `Tab` to `TerminalTab`:

```python
def _wire_terminal(self, tab: TerminalTab, terminal: JFTermTerminal) -> None:
```

In `_on_restart_tab` (lines 206–265), retype `tab: Tab` to `tab: TerminalTab` and the existing body works unchanged.

In `_on_tab_cwd_changed`, `_on_tab_running_changed`, `_on_tab_title_changed`, retype `tab: Tab` → `tab: TerminalTab`.

In `_refresh_tab_dot` (lines 422–434), retype `tab: Tab` → `tab: TerminalTab`. The body already only touches terminal-tab fields.

The signal-wiring lambdas in `_wire_terminal` already reference `t.terminal is term`. Leave those as-is — `t` is a `TerminalTab` and `.terminal` resolves correctly.

- [ ] **Step 5: Update `src/jfterm/sidebar.py`**

In `sidebar.py` line 8, change the import from:

```python
from jfterm.models import Group, Project, Tab, Workspace
```

to:

```python
from jfterm.models import Group, Project, Tab, TerminalTab, Workspace
```

In `_add_tab_row` (lines 276–336), guard the dot and restart-button blocks behind `isinstance(tab, TerminalTab)`. Replace lines 283–295 (the `dot = StatusDot()` block through the `dot.connect(...)` call) and lines 309–317 (the `restart` block) with:

```python
        dot: StatusDot | None = None
        if isinstance(tab, TerminalTab):
            dot = StatusDot()
            dot.set_valign(Gtk.Align.CENTER)
            if isinstance(group, Project):
                filled = is_inside(tab.current_cwd, group.directory)
            else:
                filled = not matching_projects(tab.current_cwd, self._ws.projects)
            dot.set_state(running=tab.is_running, filled=filled)
            tab._dot = dot
            dot.connect(
                "clicked",
                lambda _d, t=tab, g=group, anchor=dot: self.emit("dot-clicked", t, g, anchor),
            )
```

```python
        restart = None
        if isinstance(tab, TerminalTab) and tab.launched_command:
            restart = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
            restart.add_css_class("flat")
            restart.set_tooltip_text("Restart command")
            restart.connect(
                "clicked",
                lambda _b, t=tab: self.emit("restart-tab-requested", t),
            )
```

Then update the assembly at lines 330–333. Web tabs need an indent-only spacer in place of the dot so titles line up consistently with terminal-tab rows. Replace the `widgets: list[Gtk.Widget] = [dot, title]` block with:

```python
        widgets: list[Gtk.Widget] = []
        if dot is not None:
            widgets.append(dot)
        else:
            spacer = Gtk.Box()
            spacer.set_size_request(dot_size := 12, -1)  # match StatusDot width
            widgets.append(spacer)
        widgets.append(title)
        if restart is not None:
            widgets.append(restart)
        widgets.append(close)
        for w in widgets:
            row.append(w)
        self._box.append(row)
```

Note: if `StatusDot` exposes a different width, adjust `dot_size`. Check `src/jfterm/status_dot.py` for its size and use the same value here.

- [ ] **Step 6: Update `tests/test_window.py`**

Replace the `Tab` import and instantiation. The full updated file:

```python
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
```

- [ ] **Step 7: Run all tests and pyright**

Run: `uv run pytest -v && uv run pyright`
Expected: all tests pass, pyright clean.

- [ ] **Step 8: Run lint and format check**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no errors. If formatting is off, run `uv run ruff format .` and re-run check.

- [ ] **Step 9: Commit**

```bash
git add src/jfterm/models.py src/jfterm/window.py src/jfterm/sidebar.py \
        tests/test_models.py tests/test_window.py
git commit -m "refactor(models): split Tab into TerminalTab and WebTab"
```

---

## Task 3: WebKit pyright stub

**Files:**
- Create: `typings/gi/repository/WebKit.pyi`

- [ ] **Step 1: Inspect existing stubs to mirror their pattern**

Run: `ls typings/gi/repository/ && head -5 typings/gi/repository/Vte.pyi 2>/dev/null`
Expected: existing stub files (Gtk.pyi, Adw.pyi, Vte.pyi, Gdk.pyi, GLib.pyi, GObject.pyi, Pango.pyi). Each declares `from typing import Any` and exports `Any`-typed names.

- [ ] **Step 2: Create the WebKit stub**

Create `typings/gi/repository/WebKit.pyi`:

```python
from typing import Any

def __getattr__(name: str) -> Any: ...
```

If existing stubs use a richer pattern (e.g. listing specific names), mirror that pattern instead. The minimum is that any `WebKit.Foo` access type-checks as `Any`.

- [ ] **Step 3: Verify pyright still passes**

Run: `uv run pyright`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add typings/gi/repository/WebKit.pyi
git commit -m "chore(typings): add WebKit.pyi stub"
```

---

## Task 4: Shared WebKit network session

**Files:**
- Create: `src/jfterm/webkit_session.py`

- [ ] **Step 1: Implement the lazy session**

Create `src/jfterm/webkit_session.py`:

```python
"""Shared persistent WebKit.NetworkSession for all web tabs.

Lazy-imports WebKit so JFTerm starts even if `gir1.2-webkit-6.0` is not
installed — the failure is surfaced when a web tab is actually requested
(see webtab.is_available()).
"""

from __future__ import annotations

import os
from typing import Any

_session: Any = None


def _data_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "jfterm", "webkit")


def _cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "jfterm", "webkit")


def get_session() -> Any:
    """Return the shared WebKit.NetworkSession, constructing it on first use."""
    global _session
    if _session is not None:
        return _session

    import gi

    gi.require_version("WebKit", "6.0")
    from gi.repository import WebKit

    data = _data_dir()
    cache = _cache_dir()
    os.makedirs(data, exist_ok=True)
    os.makedirs(cache, exist_ok=True)

    _session = WebKit.NetworkSession.new(data, cache)
    return _session
```

- [ ] **Step 2: Smoke-import to confirm the module loads cleanly**

Run: `uv run python -c "from jfterm import webkit_session; print(webkit_session._data_dir())"`
Expected: prints `/home/<user>/.local/share/jfterm/webkit`. (Does not call `get_session()` so the WebKit dependency isn't yet exercised.)

- [ ] **Step 3: Commit**

```bash
git add src/jfterm/webkit_session.py
git commit -m "feat(webkit): add shared persistent NetworkSession"
```

---

## Task 5: Web tab availability probe

A small helper that other modules use to decide whether web-tab affordances should be enabled. Lives next to the widget so the import-failure detection logic is in one place.

**Files:**
- Create: `src/jfterm/webtab.py` (initial skeleton — the widget itself comes in Task 6)

- [ ] **Step 1: Implement availability probe**

Create `src/jfterm/webtab.py`:

```python
"""WebKit-backed web tab widget. Imports WebKit lazily so JFTerm runs
without `gir1.2-webkit-6.0` installed; callers must first check
is_available() before constructing a JFTermWebView."""

from __future__ import annotations

WEBKIT_PACKAGE = "gir1.2-webkit-6.0"

_probe_result: bool | None = None


def is_available() -> bool:
    """True iff WebKit 6.0 GObject bindings are importable.

    Cached after first call. The result is process-stable: there is no
    point retrying within the same JFTerm run.
    """
    global _probe_result
    if _probe_result is not None:
        return _probe_result
    try:
        import gi

        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit  # noqa: F401
    except (ImportError, ValueError):
        _probe_result = False
    else:
        _probe_result = True
    return _probe_result
```

- [ ] **Step 2: Smoke-test the probe**

Run: `uv run python -c "from jfterm.webtab import is_available; print(is_available())"`
Expected: `True` if `gir1.2-webkit-6.0` is installed, `False` otherwise. Either is fine — both branches will be exercised in later tasks.

- [ ] **Step 3: Commit**

```bash
git add src/jfterm/webtab.py
git commit -m "feat(webtab): add availability probe"
```

---

## Task 6: JFTermWebView widget

**Files:**
- Modify: `src/jfterm/webtab.py`

- [ ] **Step 1: Implement the widget**

Replace `src/jfterm/webtab.py` with:

```python
"""WebKit-backed web tab widget. Imports WebKit lazily so JFTerm runs
without `gir1.2-webkit-6.0` installed; callers must first check
is_available() before constructing a JFTermWebView."""

from __future__ import annotations

from typing import Any

from gi.repository import GObject, Gtk

from jfterm.webkit_session import get_session

WEBKIT_PACKAGE = "gir1.2-webkit-6.0"

_probe_result: bool | None = None


def is_available() -> bool:
    """True iff WebKit 6.0 GObject bindings are importable.

    Cached after first call. The result is process-stable: there is no
    point retrying within the same JFTerm run.
    """
    global _probe_result
    if _probe_result is not None:
        return _probe_result
    try:
        import gi

        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit  # noqa: F401
    except (ImportError, ValueError):
        _probe_result = False
    else:
        _probe_result = True
    return _probe_result


class JFTermWebView(Gtk.Box):
    """Vertical box: toolbar (back/forward/reload + URL entry) above a WebView.

    Emits:
      - `title-changed(str)` — page title changed.
      - `url-changed(str)` — current URI changed.
    """

    __gsignals__ = {
        "title-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "url-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, *, url: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        if not is_available():
            raise RuntimeError(
                f"WebKit 6.0 not available; install {WEBKIT_PACKAGE}",
            )

        import gi

        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit

        self._WebKit = WebKit  # held for can_go_back / load_uri calls

        # --- toolbar ---
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        toolbar.set_margin_start(4)
        toolbar.set_margin_end(4)
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(4)

        self._back = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self._back.add_css_class("flat")
        self._back.set_tooltip_text("Back")
        self._back.set_sensitive(False)
        self._back.connect("clicked", lambda _b: self._web.go_back())

        self._forward = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self._forward.add_css_class("flat")
        self._forward.set_tooltip_text("Forward")
        self._forward.set_sensitive(False)
        self._forward.connect("clicked", lambda _b: self._web.go_forward())

        self._reload = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self._reload.add_css_class("flat")
        self._reload.set_tooltip_text("Reload")
        self._reload.connect("clicked", lambda _b: self._web.reload())

        self._entry = Gtk.Entry()
        self._entry.set_hexpand(True)
        self._entry.set_text(url)
        self._entry.connect("activate", self._on_entry_activate)

        for w in (self._back, self._forward, self._reload, self._entry):
            toolbar.append(w)
        self.append(toolbar)

        # --- web view ---
        self._web = WebKit.WebView.new_with_session(get_session())
        self._web.set_vexpand(True)
        self._web.set_hexpand(True)

        settings = self._web.get_settings()
        settings.set_enable_developer_extras(True)

        self._web.connect("notify::title", self._on_title_notify)
        self._web.connect("notify::uri", self._on_uri_notify)
        self._web.connect("notify::estimated-load-progress", self._on_progress_notify)

        self.append(self._web)

        # Ctrl+L to focus the address bar.
        ctl = Gtk.ShortcutController()
        ctl.set_scope(Gtk.ShortcutScope.LOCAL)
        ctl.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<Control>l"),
                Gtk.CallbackAction.new(self._focus_entry),
            )
        )
        self.add_controller(ctl)

        self._web.load_uri(url)

    # --- signal plumbing ---

    def _on_title_notify(self, *_: Any) -> None:
        title = self._web.get_title() or ""
        self.emit("title-changed", title)

    def _on_uri_notify(self, *_: Any) -> None:
        uri = self._web.get_uri() or ""
        self._entry.set_text(uri)
        self._back.set_sensitive(self._web.can_go_back())
        self._forward.set_sensitive(self._web.can_go_forward())
        self.emit("url-changed", uri)

    def _on_progress_notify(self, *_: Any) -> None:
        # Update back/forward sensitivity as navigation progresses.
        self._back.set_sensitive(self._web.can_go_back())
        self._forward.set_sensitive(self._web.can_go_forward())

    def _on_entry_activate(self, entry: Gtk.Entry) -> None:
        text = entry.get_text().strip()
        if not text:
            return
        # Auto-prepend https:// if the user typed a bare host. We accept
        # anything here (no `^https?://` gate) — once a web tab exists, the
        # user is in mini-browser territory.
        if "://" not in text:
            text = "https://" + text
        self._web.load_uri(text)

    def _focus_entry(self, *_: Any) -> bool:
        self._entry.grab_focus()
        self._entry.select_region(0, -1)
        return True

    # --- public API ---

    def grab_focus(self) -> bool:  # type: ignore[override]
        return self._web.grab_focus()
```

- [ ] **Step 2: Smoke-test importability**

Run: `uv run python -c "from jfterm.webtab import JFTermWebView, is_available; print(is_available())"`
Expected: import succeeds. (Constructing the widget requires a running GTK display; we won't do that here.)

- [ ] **Step 3: Run pyright and ruff**

Run: `uv run pyright && uv run ruff check . && uv run ruff format --check .`
Expected: clean. Run `uv run ruff format .` first if formatting drifts.

- [ ] **Step 4: Commit**

```bash
git add src/jfterm/webtab.py
git commit -m "feat(webtab): add JFTermWebView widget"
```

---

## Task 7: New-web-tab dialog

A small modal that prompts for a URL, validates it against `is_web_url`, and returns the trimmed URL on confirm.

**Files:**
- Modify: `src/jfterm/dialogs.py`

- [ ] **Step 1: Inspect dialogs.py to learn the existing pattern**

Run: `head -40 src/jfterm/dialogs.py`
Expected: see how `show_project_dialog` is structured (Adw.AlertDialog usage). Mirror that style.

- [ ] **Step 2: Add `show_new_web_tab_dialog`**

Append to `src/jfterm/dialogs.py`:

```python
def show_new_web_tab_dialog(
    parent: Gtk.Window,
    on_confirm: Callable[[str], None],
) -> None:
    """Prompt for a URL. Calls `on_confirm(trimmed_url)` if the user submits
    a value matching ^https?:// (case-insensitive)."""
    from jfterm.url_routing import is_web_url

    dialog = Adw.AlertDialog.new("New web tab", None)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("ok", "Open")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response("cancel")

    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    entry = Gtk.Entry()
    entry.set_text("https://")
    entry.set_hexpand(True)
    error_label = Gtk.Label()
    error_label.add_css_class("error")
    error_label.set_xalign(0)
    error_label.set_visible(False)
    body.append(entry)
    body.append(error_label)
    dialog.set_extra_child(body)

    def _on_response(_d: Adw.AlertDialog, response: str) -> None:
        if response != "ok":
            return
        url = entry.get_text().strip()
        if not is_web_url(url):
            error_label.set_text("URL must start with http:// or https://")
            error_label.set_visible(True)
            # Re-present the dialog by re-emitting present.
            dialog.present(parent)
            return
        on_confirm(url)

    dialog.connect("response", _on_response)
    dialog.present(parent)
```

Imports already present in `dialogs.py` should cover `Adw`, `Gtk`, and `Callable`. If `Callable` isn't already imported, add `from collections.abc import Callable` at the top.

- [ ] **Step 3: Verify pyright and ruff**

Run: `uv run pyright && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/jfterm/dialogs.py
git commit -m "feat(dialogs): add new web tab URL prompt"
```

---

## Task 8: Sidebar — right-click on `+` button

Wire a right-click gesture on every `+` button (project rows and Unsorted row) that opens a `New terminal tab` / `New web tab…` popover. New signal: `new-web-tab-requested(Group, str url)`.

**Files:**
- Modify: `src/jfterm/sidebar.py`

- [ ] **Step 1: Add the signal to `__gsignals__`**

In `sidebar.py` lines 30–42, add the new signal entry. The dict becomes:

```python
__gsignals__ = {
    "tab-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "new-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "new-web-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object, str)),
    "close-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "restart-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "configure-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "launch-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "flash-command-launched": (GObject.SignalFlags.RUN_FIRST, None, (object, object)),
    "new-project-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    "toggle-expanded-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "dot-clicked": (GObject.SignalFlags.RUN_FIRST, None, (object, object, object)),
    "tab-dropped": (GObject.SignalFlags.RUN_FIRST, None, (object, object, int)),
}
```

- [ ] **Step 2: Add a helper that attaches the right-click gesture**

Add this method to the `Sidebar` class (place it near the other helpers, e.g. just after `_attach_drop`):

```python
def _attach_plus_right_click(self, plus_btn: Gtk.Widget, group: Group) -> None:
    """Attach a secondary-click gesture that opens the new-tab kind popover."""
    gesture = Gtk.GestureClick()
    gesture.set_button(Gdk.BUTTON_SECONDARY)

    def _on_pressed(_g: Gtk.GestureClick, _n: int, _x: float, _y: float) -> None:
        self._show_new_tab_popover(plus_btn, group)

    gesture.connect("pressed", _on_pressed)
    plus_btn.add_controller(gesture)


def _show_new_tab_popover(self, anchor: Gtk.Widget, group: Group) -> None:
    from jfterm.webtab import WEBKIT_PACKAGE, is_available

    pop = Gtk.Popover()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.set_margin_start(4)
    box.set_margin_end(4)
    box.set_margin_top(4)
    box.set_margin_bottom(4)

    term_btn = Gtk.Button(label="New terminal tab")
    term_btn.add_css_class("flat")
    term_btn.set_halign(Gtk.Align.FILL)

    def _on_term(_b: Gtk.Button, g: Group = group, popover: Gtk.Popover = pop) -> None:
        popover.popdown()
        self.emit("new-tab-requested", g)

    term_btn.connect("clicked", _on_term)
    box.append(term_btn)

    web_btn = Gtk.Button(label="New web tab…")
    web_btn.add_css_class("flat")
    web_btn.set_halign(Gtk.Align.FILL)
    if not is_available():
        web_btn.set_sensitive(False)
        web_btn.set_tooltip_text(f"WebKit not available — install {WEBKIT_PACKAGE}")
    else:

        def _on_web(_b: Gtk.Button, g: Group = group, popover: Gtk.Popover = pop) -> None:
            popover.popdown()
            # Ask the window to open the URL dialog. The window is the only
            # thing with a Gtk.Window handle for the dialog parent.
            self.emit("new-web-tab-requested", g, "")

        web_btn.connect("clicked", _on_web)
    box.append(web_btn)

    pop.set_child(box)
    pop.set_parent(anchor)
    pop.popup()
```

The `new-web-tab-requested` signal is emitted with an empty string when triggered from the popover — the window will pop the URL dialog and emit / re-handle the URL itself. The same signal is reused for non-empty URL routing later (Tasks 9 and 10) by emitting it with the URL prefilled.

Actually, simpler: the popover-triggered case calls into the window directly via the signal with empty string meaning "ask user for URL". The startup/flash paths don't go through this signal at all — they call `_spawn_web_tab` directly. So the empty-string contract is: empty → prompt; non-empty → spawn directly. Document this in the signal doc.

Add a docstring near `__gsignals__`:

```python
# new-web-tab-requested(Group, str url): if `url` is empty, the window
# should prompt the user for one (via show_new_web_tab_dialog); otherwise
# the window should spawn a web tab pointing at that URL directly.
```

- [ ] **Step 3: Wire `_attach_plus_right_click` to both `+` buttons**

In `_add_project_row` (around line 209–212), after the existing `plus.connect(...)`, add:

```python
        self._attach_plus_right_click(plus, project)
```

In `_add_unsorted_row` (around line 270), after the existing `plus.connect(...)`, add:

```python
        self._attach_plus_right_click(plus, group)
```

- [ ] **Step 4: Verify pyright and ruff**

Run: `uv run pyright && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/sidebar.py
git commit -m "feat(sidebar): right-click on + opens tab-kind popover"
```

---

## Task 9: Window — `_spawn_web_tab` and right-click handler

**Files:**
- Modify: `src/jfterm/window.py`

- [ ] **Step 1: Add the imports**

In `window.py` line 15, expand the models import to include `WebTab`:

```python
from jfterm.models import (  # noqa: E402
    FlashCommand,
    Group,
    Project,
    StartupCommand,
    Tab,
    TerminalTab,
    WebTab,
    Workspace,
)
```

- [ ] **Step 2: Add `_spawn_web_tab` and the wire helper**

Insert these methods just after `_wire_terminal` (around line 173):

```python
def _spawn_web_tab(
    self,
    group: Group,
    *,
    url: str,
    focus: bool = True,
    from_startup: bool = False,
    flash_name: str | None = None,
) -> WebTab:
    from jfterm.webtab import JFTermWebView

    web_view = JFTermWebView(url=url)
    web_view.set_vexpand(True)
    web_view.set_hexpand(True)

    initial_title = url
    if flash_name is not None:
        initial_title = f"⚡ {flash_name}"
    elif from_startup:
        initial_title = f"▶ {url}"
    tab = WebTab(
        title=initial_title,
        url=url,
        web_view=web_view,
        from_startup=from_startup,
        flash_name=flash_name,
    )
    self._wire_web_view(tab, web_view)
    self.terminal_stack.add_child(web_view)
    group.add_tab(tab)
    self._current_group = group
    if focus:
        self.terminal_stack.set_visible_child(web_view)
        self.sidebar.set_active_tab(tab)
        web_view.grab_focus()
    self.sidebar.refresh()
    return tab


def _wire_web_view(self, tab: WebTab, web_view: Any) -> None:
    web_view.connect(
        "title-changed",
        lambda _w, title, t=tab, wv=web_view: (
            self._on_web_tab_title_changed(t, title) if t.web_view is wv else None
        ),
    )
    web_view.connect(
        "url-changed",
        lambda _w, url, t=tab, wv=web_view: (
            self._on_web_tab_url_changed(t, url) if t.web_view is wv else None
        ),
    )


def _on_web_tab_title_changed(self, tab: WebTab, title: str) -> None:
    base = title or tab.url
    if tab.flash_name is not None:
        tab.title = f"⚡ {tab.flash_name}: {base}" if title else f"⚡ {tab.flash_name}"
    elif tab.from_startup:
        tab.title = f"▶ {base}"
    else:
        tab.title = base
    self.sidebar.refresh()


def _on_web_tab_url_changed(self, tab: WebTab, url: str) -> None:
    if url:
        tab.url = url
```

Add `from typing import Any` to the top of `window.py` if not already present.

- [ ] **Step 3: Connect the `new-web-tab-requested` signal**

In `__init__` after the existing `self.sidebar.connect(...)` block (around line 84), add:

```python
        self.sidebar.connect("new-web-tab-requested", self._on_new_web_tab)
```

Add the handler:

```python
def _on_new_web_tab(self, _sb, group: Group, url: str) -> None:
    if url:
        self._spawn_web_tab(group, url=url)
        return
    from jfterm.dialogs import show_new_web_tab_dialog

    def _confirm(submitted: str) -> None:
        self._spawn_web_tab(group, url=submitted)

    show_new_web_tab_dialog(self, on_confirm=_confirm)
```

- [ ] **Step 4: Update `tab.terminal` accesses that should be `tab.widget`**

Several spots in `window.py` read `tab.terminal` purely to fetch the GTK widget mounted in the stack. Migrate these to `tab.widget` so they work for both tab kinds. Specifically:

- `_on_tab_activated` (lines 107–112): `tab.terminal` → `tab.widget`. Note: web tabs don't have a child terminal, so the `.grab_focus()` call works since `Gtk.Box.grab_focus` is well-defined (and `JFTermWebView` overrides it to focus the WebView).
- `_on_close_tab` (lines 174–204): replace `tab.terminal is not None` checks with `tab.widget is not None`, and the two `self.terminal_stack.get_visible_child() is tab.terminal` checks with `... is tab.widget`. The `self.terminal_stack.remove(tab.terminal)` call becomes `self.terminal_stack.remove(tab.widget)`. The `promoted.terminal` accesses become `promoted.widget`.
- `_on_dot_clicked` (line 377): `tab.terminal is not None and self.terminal_stack.get_visible_child() is tab.terminal` → `... is tab.widget`. The dot-clicked path is only triggered for `TerminalTab` (web tabs have no dot), so this is just a defensive change.
- `_on_tab_dropped` (line 395): same migration as above.
- `_current_tab` (lines 454–460): `t.terminal is visible` → `t.widget is visible`.
- `_cycle_tab` (lines 462–473): `nxt.terminal is not None and ...` → `nxt.widget is not None`, and `self.terminal_stack.set_visible_child(nxt.terminal)` → `self.terminal_stack.set_visible_child(nxt.widget)`. The `nxt.terminal.grab_focus()` becomes `nxt.widget.grab_focus()`.

`_on_restart_tab` keeps using `tab.terminal` directly because it is, by definition, terminal-only — and the parameter is now typed `TerminalTab`.

- [ ] **Step 5: Run all tests, pyright, ruff**

Run: `uv run pytest -v && uv run pyright && uv run ruff check . && uv run ruff format --check .`
Expected: all green. Run `uv run ruff format .` first if formatting drifts.

- [ ] **Step 6: Manual smoke test**

Run: `just run` (or `uv run jfterm`). In the running app:
1. Right-click on the `+` button in any group's row.
2. Confirm the popover shows `New terminal tab` and `New web tab…`.
3. If WebKit is installed, click `New web tab…`, enter `https://example.com`, confirm a web tab opens with the page loaded and toolbar visible.
4. Confirm cycling tabs (Ctrl+PageDown) works between terminal and web tabs without errors.
5. Close the web tab (sidebar X button) — confirm clean removal.

Note: this is a UI feature, so type checks and tests verify code correctness, not feature correctness. If you can't test the UI in this environment, say so explicitly and mark the task with a note for the user.

- [ ] **Step 7: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(window): add _spawn_web_tab and right-click handler"
```

---

## Task 10: Startup-command routing

Make `_on_launch_project` dispatch URL-shaped commands to `_spawn_web_tab`.

**Files:**
- Modify: `src/jfterm/window.py`

- [ ] **Step 1: Update `_on_launch_project`**

Locate `_on_launch_project` (around lines 323–354). The existing `running` set tracks `launched_command` strings; expand it to include URLs from existing web tabs. Replace the `running = {...}` line and the `_step` body with:

```python
def _on_launch_project(self, _sb, project: Project) -> None:
    if not project.startup_commands:
        return
    if not project.expanded:
        project.expanded = True
        save_projects(self.ws, default_path())
        self.sidebar.refresh()
    from gi.repository import GLib

    from jfterm.url_routing import is_web_url

    running_terminal = {
        t.launched_command for t in project.tabs
        if isinstance(t, TerminalTab) and t.launched_command
    }
    running_web = {
        t.url for t in project.tabs if isinstance(t, WebTab)
    }
    cmds = [
        sc for sc in project.startup_commands
        if sc.command not in running_terminal
        and sc.command.strip() not in running_web
    ]
    spawn_blank = project.spawn_blank_after_startup

    def _step(idx: int) -> bool:
        if idx >= len(cmds):
            if spawn_blank:
                self._spawn_tab(project, focus=True)
            return False  # remove timeout
        sc = cmds[idx]
        is_last = idx == len(cmds) - 1
        focus = sc.delay > 0 or (is_last and not spawn_blank)
        if is_web_url(sc.command):
            self._spawn_web_tab(
                project,
                url=sc.command.strip(),
                focus=focus,
                from_startup=True,
            )
        else:
            tab = self._spawn_tab(project, command=sc.command, focus=focus)
            tab.from_startup = True
            tab.title = f"▶ {sc.command}"
        if idx + 1 < len(cmds) or spawn_blank:
            if sc.delay > 0:
                GLib.timeout_add_seconds(sc.delay, _step, idx + 1)
            else:
                GLib.idle_add(_step, idx + 1)
        return False

    _step(0)
```

- [ ] **Step 2: Run checks**

Run: `uv run pytest -v && uv run pyright && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(startup): route http(s) commands to web tabs"
```

---

## Task 11: Flash-command routing

**Files:**
- Modify: `src/jfterm/window.py`

- [ ] **Step 1: Update `_on_flash_command_launched`**

Locate `_on_flash_command_launched` (around lines 356–365). Replace the body with:

```python
def _on_flash_command_launched(self, _sb, project: Project, fc: FlashCommand) -> None:
    if not project.expanded:
        project.expanded = True
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    from jfterm.url_routing import is_web_url

    if is_web_url(fc.command):
        self._spawn_web_tab(
            project,
            url=fc.command.strip(),
            focus=fc.focus_on_launch,
            flash_name=fc.name,
        )
        self.sidebar.refresh()
        return

    wrapped = wrap_flash_command(fc)
    tab = self._spawn_tab(project, command=wrapped, focus=fc.focus_on_launch)
    tab.flash_name = fc.name
    tab.title = f"⚡ {fc.name}"
    self.sidebar.refresh()
```

- [ ] **Step 2: Run checks**

Run: `uv run pytest -v && uv run pyright && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(flash): route http(s) flash commands to web tabs"
```

---

## Task 12: README updates

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the apt dependency**

In the `apt install` snippet (around line 22 in current README), append `gir1.2-webkit-6.0` to the list. The block becomes:

```
sudo apt install \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-vte-3.91 \
    gir1.2-webkit-6.0 \
    libvte-2.91-gtk4-0 \
    python3-gi python3-cairo
```

- [ ] **Step 2: Add a "Web tabs" feature item**

In the `## Features` list, add a new bullet after the existing tab-related bullets:

```
- Web tabs: any startup or flash command starting with `http://` or
  `https://` opens a WebKitGTK mini-browser in place of a shell. You can
  also right-click a group's `+` button for an ad-hoc "New web tab…"
  prompt. Cookies and localStorage persist across tabs and JFTerm
  restarts in `~/.local/share/jfterm/webkit/`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): document web tabs feature"
```

---

## Task 13: Full check

- [ ] **Step 1: Run the full CI suite**

Run: `just check`
Expected: lint, fmt-check, typecheck, test all pass.

- [ ] **Step 2: Manual smoke test (UI)**

Run: `just run`. Verify in the running app:
1. Add a project with a startup command `https://example.com` and another `bash` command. Launching the project opens both — one web tab, one terminal tab.
2. Add a flash command with the URL `https://example.com`. Triggering it from the flash menu opens a web tab.
3. Right-click `+` → New web tab… → enter a URL → web tab opens.
4. Tab cycling (Ctrl+PageUp/Down) moves between terminal and web tabs.
5. Drag a web tab between groups — it moves cleanly.
6. Close the web tab — it removes from the sidebar and selects a sibling correctly.
7. F12 in a web tab opens DevTools; right-click on the page shows the WebKit context menu.
8. Restart JFTerm; cookies set in the previous session persist (test by visiting a site that sets a cookie, then restarting and reloading).

If any step fails, file the regression as a follow-up; don't paper over it.

- [ ] **Step 3: Final commit (if any cleanups)**

If steps 1–2 produced changes, commit them. Otherwise no-op.

---

## Task 14: Graceful fallback when WebKit missing for startup/flash

The popover already greys out `New web tab…` when WebKit is unavailable, but startup/flash commands can still hit `_spawn_web_tab`. This task wraps those paths so a missing WebKit becomes a visible error in a terminal tab rather than a stack trace.

**Files:**
- Modify: `src/jfterm/window.py`

- [ ] **Step 1: Wrap `_spawn_web_tab` calls in startup/flash routing with a try/except**

In `_on_launch_project`'s `_step`, replace the `if is_web_url(sc.command):` branch:

```python
        if is_web_url(sc.command):
            try:
                self._spawn_web_tab(
                    project,
                    url=sc.command.strip(),
                    focus=focus,
                    from_startup=True,
                )
            except RuntimeError as e:
                tab = self._spawn_tab(
                    project,
                    command=f'echo "JFTerm: {e}"',
                    focus=focus,
                )
                tab.from_startup = True
                tab.title = f"▶ {sc.command}"
```

In `_on_flash_command_launched`, replace the `if is_web_url(fc.command):` block:

```python
    if is_web_url(fc.command):
        try:
            self._spawn_web_tab(
                project,
                url=fc.command.strip(),
                focus=fc.focus_on_launch,
                flash_name=fc.name,
            )
        except RuntimeError as e:
            tab = self._spawn_tab(
                project,
                command=f'echo "JFTerm: {e}"',
                focus=fc.focus_on_launch,
            )
            tab.flash_name = fc.name
            tab.title = f"⚡ {fc.name}"
        self.sidebar.refresh()
        return
```

The right-click `New web tab…` popover path doesn't need this guard because the menu item is already insensitive when WebKit is missing.

- [ ] **Step 2: Run all checks**

Run: `uv run pytest -v && uv run pyright && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(window): fall back to terminal tab when WebKit missing"
```
