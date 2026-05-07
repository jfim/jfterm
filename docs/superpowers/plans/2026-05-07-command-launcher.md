# Command Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quicksilver-style fuzzy command launcher invoked by double-tapping Left Shift, exposing flash commands, project actions (new shell tab, run startup commands), and jump-to-tab as a single ranked list.

**Architecture:** Three pure modules (`fuzzy.py` — scoring; `launcher_items.py` — action dataclasses + item-list builder from a Workspace; `double_tap.py` — modifier-double-tap detector) plus one GTK module (`launcher.py` — popup widget with search entry, list view, and a session-only recents list). Wired into `JFTermWindow` via a single dispatcher that reuses existing `_spawn_tab`, `_on_launch_project`, `_on_flash_command_launched`, and `_on_tab_activated` handlers.

**Tech Stack:** Python 3, GTK4 / libadwaita via PyGObject, pytest.

**Spec:** [docs/superpowers/specs/2026-05-07-command-launcher-design.md](docs/superpowers/specs/2026-05-07-command-launcher-design.md)

---

## Task 1: Fuzzy matcher (`fuzzy.py`)

**Files:**
- Create: `src/jfterm/fuzzy.py`
- Create: `tests/test_fuzzy.py`

Pure scoring with a subsequence DP. No GTK. The DP state is `best[i][j]` = best score for matching `query[:i]` ending at `candidate[j]` (with `j` being the index of the *last* matched candidate char). Final score is `max(best[len(query)][*])`. Returns `None` if no subsequence match.

Bonus constants (tunable, but locked here so later tasks can rely on them):

- `BOUNDARY = 10` — matched candidate char sits at a word boundary
- `CONSECUTIVE = 5` — matched immediately after the previous match
- `BASE = 1` — every matched char

A "word boundary" in `candidate[j]`:

- `j == 0`, OR
- `candidate[j-1]` is one of `space`, `:`, `_`, `-`, `/`, OR
- `candidate[j-1].islower()` and `candidate[j].isupper()` (camel hump)

Case rule: a query character `q` matches candidate character `c` when:

- if `q.isupper()`: only matches if `c.isupper()` *or* `c` sits at a word boundary (any case), and `q.lower() == c.lower()`
- else: `q.lower() == c.lower()` (case-insensitive)

- [ ] **Step 1: Write failing tests**

Create `tests/test_fuzzy.py`:

```python
from jfterm.fuzzy import rank, score


def test_score_exact_prefix_beats_subsequence():
    assert (score("proj", "project") or 0) > (score("proj", "p_r_o_j") or 0)


def test_score_no_match_returns_none():
    assert score("xyz", "project") is None


def test_score_empty_query_is_zero():
    assert score("", "anything") == 0


def test_score_intellij_initials_lowercase():
    # All matches sit on word boundaries -> high score.
    s = score("panst", "Project A: New Shell Tab")
    assert s is not None
    # 5 chars * BOUNDARY (10) + 4 consecutive runs of length 0 + 5 * BASE (1)
    # We don't pin the exact number; just require it ranks above the
    # mid-string subsequence below.
    s_mid = score("panst", "panastic")  # subsequence, mid-string
    assert s_mid is None or s > s_mid


def test_score_intellij_initials_uppercase():
    # Uppercase query must match uppercase OR boundary chars.
    assert score("PANST", "Project A: New Shell Tab") is not None
    # Uppercase must NOT match a mid-word lowercase char.
    assert score("PANST", "panastic") is None


def test_score_consecutive_run_beats_scattered():
    a = score("proj", "project")
    b = score("proj", "p_r_o_j")
    assert a is not None and b is not None
    assert a > b


def test_rank_orders_by_score_descending():
    items = ["panastic", "Project A: New Shell Tab", "Pat A: Nest"]
    out = rank("panst", items, key=lambda s: s)
    # First non-None match should be the all-boundary one.
    assert out[0] == "Project A: New Shell Tab"
    # Items that don't match are dropped.
    assert "panastic" not in out


def test_rank_drops_unmatched():
    out = rank("zzz", ["abc", "def"], key=lambda s: s)
    assert out == []
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_fuzzy.py -v`
Expected: all fail with `ModuleNotFoundError: No module named 'jfterm.fuzzy'`.

- [ ] **Step 3: Implement `fuzzy.py`**

Create `src/jfterm/fuzzy.py`:

```python
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

BOUNDARY = 10
CONSECUTIVE = 5
BASE = 1

_BOUNDARY_CHARS = frozenset(" :_-/")

T = TypeVar("T")


def _is_boundary(candidate: str, j: int) -> bool:
    if j == 0:
        return True
    prev = candidate[j - 1]
    if prev in _BOUNDARY_CHARS:
        return True
    cur = candidate[j]
    return prev.islower() and cur.isupper()


def _matches(q: str, c: str, candidate: str, j: int) -> bool:
    if q.lower() != c.lower():
        return False
    if q.isupper():
        return c.isupper() or _is_boundary(candidate, j)
    return True


def score(query: str, candidate: str) -> int | None:
    """Return a non-negative score for fuzzy-matching query against
    candidate, or None when no subsequence match exists.

    Higher is better. See module docstring for the bonus constants.
    """
    if query == "":
        return 0
    n, m = len(query), len(candidate)
    if n > m:
        return None
    NEG = -1
    # best[j] = best score matching query[:i] ending exactly at candidate[j]
    # for the current i. Uses two rows (prev / cur) over i.
    prev = [NEG] * m
    # i = 1
    q0 = query[0]
    for j in range(m):
        if _matches(q0, candidate[j], candidate, j):
            bonus = BOUNDARY if _is_boundary(candidate, j) else 0
            prev[j] = BASE + bonus
    if n == 1:
        best = max((v for v in prev if v != NEG), default=NEG)
        return best if best != NEG else None
    for i in range(2, n + 1):
        cur = [NEG] * m
        qi = query[i - 1]
        # Track best prev[k] for k < j as we walk j ascending.
        running_best_prev = NEG
        running_best_prev_j = -1
        for j in range(m):
            # First, update running best for k < j (i.e., include prev[j-1]).
            if j > 0 and prev[j - 1] > running_best_prev:
                running_best_prev = prev[j - 1]
                running_best_prev_j = j - 1
            if not _matches(qi, candidate[j], candidate, j):
                continue
            if running_best_prev == NEG:
                continue
            bonus = BOUNDARY if _is_boundary(candidate, j) else 0
            consec = CONSECUTIVE if running_best_prev_j == j - 1 else 0
            # If consec applies, we must use prev[j-1] specifically (not the
            # max). Otherwise we use the max across k < j.
            if running_best_prev_j == j - 1:
                cur[j] = prev[j - 1] + BASE + bonus + consec
                # Also consider the non-consecutive path in case the running
                # best is higher than prev[j-1] + bonuses without consec.
                non_consec = running_best_prev + BASE + bonus
                if non_consec > cur[j]:
                    cur[j] = non_consec
            else:
                cur[j] = running_best_prev + BASE + bonus
        prev = cur
    best = max((v for v in prev if v != NEG), default=NEG)
    return best if best != NEG else None


def rank(query: str, items: Iterable[T], key: Callable[[T], str]) -> list[T]:
    """Return items sorted by descending score against query, dropping
    items that don't match. Stable on ties (preserves input order)."""
    scored: list[tuple[int, int, T]] = []
    for idx, item in enumerate(items):
        s = score(query, key(item))
        if s is None:
            continue
        scored.append((-s, idx, item))
    scored.sort()
    return [item for _, _, item in scored]
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_fuzzy.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/fuzzy.py tests/test_fuzzy.py
git commit -m "feat(fuzzy): subsequence matcher with word-boundary bonuses"
```

---

## Task 2: Action types and item-list builder (`launcher_items.py`)

**Files:**
- Create: `src/jfterm/launcher_items.py`
- Create: `tests/test_launcher_items.py`

Pure module. Defines four `@dataclass(frozen=True)` action types and a `build_items(workspace) -> list[LauncherItem]` function. Each `LauncherItem` is `(display: str, action: Action)`.

Display rules (uniform `<Project>: <Object>` per the spec):

- `FlashAction(project, flash)` → `f"{project.name}: ⚡ {flash.name}"`
- `JumpAction(project_or_unsorted_name, tab)` → `f"{project_or_unsorted_name}: ▦ {tab.title or '(untitled)'}"`
- `NewTabAction(project)` → `f"{project.name}: New Shell Tab"`
- `StartupAction(project)` → `f"{project.name}: Run Startup Commands"`

Order in the built list (only matters as a tiebreaker; ranking re-sorts on query):

1. For each active project (in `workspace.projects` order, skipping archived):
   - one `NewTabAction`
   - one `StartupAction` *only if* `project.startup_commands` is non-empty
   - one `FlashAction` per `project.flash_commands` (in order)
   - one `JumpAction` per tab in `project.tabs` (in order)
2. For Unsorted: one `JumpAction` per tab (no New Shell Tab / Startup rows for Unsorted).

Archived projects are skipped entirely.

- [ ] **Step 1: Write failing tests**

Create `tests/test_launcher_items.py`:

```python
from jfterm.launcher_items import (
    FlashAction,
    JumpAction,
    NewTabAction,
    StartupAction,
    build_items,
)
from jfterm.models import (
    FlashCommand,
    StartupCommand,
    TerminalTab,
    Workspace,
)


def test_build_items_empty_workspace_yields_nothing():
    ws = Workspace()
    assert build_items(ws) == []


def test_build_items_project_with_no_extras_emits_only_new_tab():
    ws = Workspace()
    ws.add_project(name="Alpha", directory="/tmp/a")
    items = build_items(ws)
    assert len(items) == 1
    assert items[0].display == "Alpha: New Shell Tab"
    assert isinstance(items[0].action, NewTabAction)


def test_build_items_emits_startup_row_only_when_startup_commands_present():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    p.startup_commands.append(StartupCommand(command="ls"))
    items = build_items(ws)
    displays = [i.display for i in items]
    assert "Alpha: Run Startup Commands" in displays
    assert any(isinstance(i.action, StartupAction) for i in items)


def test_build_items_emits_one_flash_row_per_flash_command():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    p.flash_commands.extend(
        [FlashCommand(name="Push", command="git push"),
         FlashCommand(name="Pull", command="git pull")]
    )
    items = build_items(ws)
    displays = [i.display for i in items]
    assert "Alpha: ⚡ Push" in displays
    assert "Alpha: ⚡ Pull" in displays
    flash_actions = [i.action for i in items if isinstance(i.action, FlashAction)]
    assert {a.flash.name for a in flash_actions} == {"Push", "Pull"}


def test_build_items_emits_jump_row_per_tab_in_project():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    t = TerminalTab(title="bash")
    p.add_tab(t)
    items = build_items(ws)
    displays = [i.display for i in items]
    assert "Alpha: ▦ bash" in displays


def test_build_items_uses_unsorted_label_for_unsorted_tabs():
    ws = Workspace()
    t = TerminalTab(title="scratch")
    ws.unsorted.add_tab(t)
    items = build_items(ws)
    assert len(items) == 1
    assert items[0].display == "Unsorted: ▦ scratch"
    assert isinstance(items[0].action, JumpAction)


def test_build_items_no_new_tab_or_startup_for_unsorted():
    ws = Workspace()
    ws.unsorted.add_tab(TerminalTab(title="x"))
    displays = [i.display for i in build_items(ws)]
    assert "Unsorted: New Shell Tab" not in displays
    assert "Unsorted: Run Startup Commands" not in displays


def test_build_items_skips_archived_projects():
    ws = Workspace()
    a = ws.add_project(name="Alive", directory="/tmp/a")
    z = ws.add_project(name="Zombie", directory="/tmp/z")
    z.archived = True
    z.flash_commands.append(FlashCommand(name="Push", command="git push"))
    displays = [i.display for i in build_items(ws)]
    assert any(d.startswith("Alive:") for d in displays)
    assert not any(d.startswith("Zombie:") for d in displays)
    _ = a  # unused-name silencer


def test_build_items_untitled_tab_falls_back():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    p.add_tab(TerminalTab(title=""))
    displays = [i.display for i in build_items(ws)]
    assert "Alpha: ▦ (untitled)" in displays
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_launcher_items.py -v`
Expected: all fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `launcher_items.py`**

Create `src/jfterm/launcher_items.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from jfterm.models import FlashCommand, Project, Tab, Workspace


@dataclass(frozen=True)
class FlashAction:
    project: Project
    flash: FlashCommand


@dataclass(frozen=True)
class NewTabAction:
    project: Project


@dataclass(frozen=True)
class StartupAction:
    project: Project


@dataclass(frozen=True)
class JumpAction:
    tab: Tab


Action = FlashAction | NewTabAction | StartupAction | JumpAction


@dataclass(frozen=True)
class LauncherItem:
    display: str
    action: Action


def _tab_title(t: Tab) -> str:
    return t.title or "(untitled)"


def build_items(ws: Workspace) -> list[LauncherItem]:
    items: list[LauncherItem] = []
    for p in ws.projects:
        if p.archived:
            continue
        items.append(LauncherItem(f"{p.name}: New Shell Tab", NewTabAction(p)))
        if p.startup_commands:
            items.append(
                LauncherItem(f"{p.name}: Run Startup Commands", StartupAction(p))
            )
        for fc in p.flash_commands:
            items.append(LauncherItem(f"{p.name}: ⚡ {fc.name}", FlashAction(p, fc)))
        for t in p.tabs:
            items.append(LauncherItem(f"{p.name}: ▦ {_tab_title(t)}", JumpAction(t)))
    for t in ws.unsorted.tabs:
        items.append(LauncherItem(f"Unsorted: ▦ {_tab_title(t)}", JumpAction(t)))
    return items
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_launcher_items.py -v`
Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/launcher_items.py tests/test_launcher_items.py
git commit -m "feat(launcher): action types and item-list builder"
```

---

## Task 3: Double-tap detector (`double_tap.py`)

**Files:**
- Create: `src/jfterm/double_tap.py`
- Create: `tests/test_double_tap.py`

Pure logic, no GTK. A `DoubleTapDetector(target_keyval, interval_ms, callback)` exposes two methods:

- `on_press(keyval, time_ms)` — feed a key-press event. Fires callback if this is a second press of `target_keyval` within `interval_ms`, with no intervening non-target key press.
- `reset()` — clear pending state (used when the launcher actually opens, to avoid triple-tap re-firing).

Behavior:

- First press of target → record `(time_ms)`.
- Second press of target within window → fire callback, then clear pending.
- Press of *any other* key → clear pending.
- Press of target outside the window → treat as new "first press" (overwrite timestamp).

GTK keyval ints are opaque to this module (we just compare equality).

- [ ] **Step 1: Write failing tests**

Create `tests/test_double_tap.py`:

```python
from jfterm.double_tap import DoubleTapDetector


def test_two_presses_within_window_fires():
    fired = []
    d = DoubleTapDetector(target_keyval=42, interval_ms=300, callback=lambda: fired.append(True))
    d.on_press(42, 1000)
    d.on_press(42, 1100)
    assert fired == [True]


def test_two_presses_outside_window_does_not_fire():
    fired = []
    d = DoubleTapDetector(target_keyval=42, interval_ms=300, callback=lambda: fired.append(True))
    d.on_press(42, 1000)
    d.on_press(42, 1500)
    assert fired == []


def test_intervening_other_key_resets():
    fired = []
    d = DoubleTapDetector(target_keyval=42, interval_ms=300, callback=lambda: fired.append(True))
    d.on_press(42, 1000)
    d.on_press(99, 1050)
    d.on_press(42, 1100)
    assert fired == []


def test_third_press_does_not_re_fire():
    fired = []
    d = DoubleTapDetector(target_keyval=42, interval_ms=300, callback=lambda: fired.append(True))
    d.on_press(42, 1000)
    d.on_press(42, 1100)  # fires
    d.on_press(42, 1200)  # this is now a fresh first press
    d.on_press(42, 1300)  # this completes a new pair
    assert fired == [True, True]


def test_reset_clears_pending():
    fired = []
    d = DoubleTapDetector(target_keyval=42, interval_ms=300, callback=lambda: fired.append(True))
    d.on_press(42, 1000)
    d.reset()
    d.on_press(42, 1100)  # no pending -> becomes fresh first press
    assert fired == []


def test_non_target_first_press_does_nothing():
    fired = []
    d = DoubleTapDetector(target_keyval=42, interval_ms=300, callback=lambda: fired.append(True))
    d.on_press(99, 1000)
    d.on_press(99, 1100)
    assert fired == []
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_double_tap.py -v`
Expected: all fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `double_tap.py`**

Create `src/jfterm/double_tap.py`:

```python
from __future__ import annotations

from collections.abc import Callable


class DoubleTapDetector:
    """Fires a callback when target_keyval is pressed twice within
    interval_ms with no intervening non-target press."""

    def __init__(
        self,
        *,
        target_keyval: int,
        interval_ms: int,
        callback: Callable[[], None],
    ) -> None:
        self._target = target_keyval
        self._interval = interval_ms
        self._callback = callback
        self._pending_time: int | None = None

    def on_press(self, keyval: int, time_ms: int) -> None:
        if keyval != self._target:
            self._pending_time = None
            return
        if self._pending_time is not None and time_ms - self._pending_time <= self._interval:
            self._pending_time = None
            self._callback()
            return
        self._pending_time = time_ms

    def reset(self) -> None:
        self._pending_time = None
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_double_tap.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/double_tap.py tests/test_double_tap.py
git commit -m "feat(double-tap): modifier double-tap detector"
```

---

## Task 4: Launcher widget (`launcher.py`)

**Files:**
- Create: `src/jfterm/launcher.py`
- Create: `tests/test_launcher.py`

GTK widget. The `Launcher` class:

- Constructor: `Launcher(parent: Gtk.Window, dispatch: Callable[[Action], None])`.
- Holds `self._recents: list[Action]` (RAM-only, capped at `MAX_RECENTS = 8`).
- `open(workspace)` — builds items from `workspace`, opens a transient `Adw.Window` (~600px wide) over `parent`, focuses search entry, shows recents (filtered to actions whose item still exists in `workspace`).
- On Enter: calls `dispatch(action)`, prepends to recents (deduped by equality), closes the popup.
- On Esc: closes without dispatching.
- On text change: re-runs `fuzzy.rank` over current items, updates list view.
- Up/Down move highlight (default `Gtk.ListView` behavior with single-selection).

Recents filtering uses identity comparison against current items list — each `Action`'s referenced project / tab / flash must still exist in the freshly built items. (Frozen dataclasses with `eq=True` make equality structural, which is what we want.)

This task ships the widget and a smoke test only (no end-to-end GTK loop test).

- [ ] **Step 1: Write the smoke test**

Create `tests/test_launcher.py`:

```python
"""Smoke test for the launcher widget — constructs it and exercises its
pure logic methods, without entering a GTK main loop."""

from jfterm.launcher import Launcher
from jfterm.launcher_items import FlashAction, NewTabAction, build_items
from jfterm.models import FlashCommand, Workspace


def test_launcher_filter_returns_ranked_items():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    p.flash_commands.append(FlashCommand(name="Push", command="git push"))
    items = build_items(ws)
    # filter_items is a static-style helper that doesn't need GTK.
    out = Launcher.filter_items("alpha push", items)
    assert any(isinstance(i.action, FlashAction) for i in out)
    assert out[0].action.flash.name == "Push"  # type: ignore[attr-defined]


def test_launcher_filter_empty_query_returns_recents_only_when_provided():
    ws = Workspace()
    ws.add_project(name="Alpha", directory="/tmp/a")
    items = build_items(ws)
    # Empty query, no recents -> empty.
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
    # Most recent first.
    assert recents[0] == NewTabAction(p4)


def test_launcher_recents_filter_drops_stale_actions():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    items = build_items(ws)
    fresh = NewTabAction(p)
    p2_proj = ws.add_project(name="Beta", directory="/tmp/b")
    stale = NewTabAction(p2_proj)
    ws.projects.remove(p2_proj)  # Beta no longer in workspace
    items = build_items(ws)
    out = Launcher.recents_in_items([fresh, stale], items)
    assert out == [fresh]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_launcher.py -v`
Expected: fails with `ModuleNotFoundError: No module named 'jfterm.launcher'`.

- [ ] **Step 3: Implement `launcher.py`**

Create `src/jfterm/launcher.py`:

```python
from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GObject, Gtk  # noqa: E402

from jfterm.fuzzy import rank
from jfterm.launcher_items import Action, LauncherItem, build_items
from jfterm.models import Workspace

MAX_RECENTS = 8


class Launcher:
    def __init__(
        self,
        parent: Gtk.Window,
        dispatch: Callable[[Action], None],
    ) -> None:
        self._parent = parent
        self._dispatch = dispatch
        self._recents: list[Action] = []
        self._window: Adw.Window | None = None
        self._entry: Gtk.SearchEntry | None = None
        self._list_view: Gtk.ListView | None = None
        self._store: Gio.ListStore | None = None
        self._selection: Gtk.SingleSelection | None = None
        self._items: list[LauncherItem] = []

    # --- pure helpers (kept static-style for unit testing) ---

    @staticmethod
    def filter_items(query: str, items: list[LauncherItem]) -> list[LauncherItem]:
        if query == "":
            return []
        return rank(query, items, key=lambda it: it.display)

    @staticmethod
    def push_recent(recents: list[Action], action: Action, *, max_recents: int) -> None:
        # Dedup by equality (frozen dataclasses) and move to front.
        if action in recents:
            recents.remove(action)
        recents.insert(0, action)
        del recents[max_recents:]

    @staticmethod
    def recents_in_items(
        recents: list[Action], items: list[LauncherItem]
    ) -> list[Action]:
        present = {it.action for it in items}
        return [a for a in recents if a in present]

    # --- GTK lifecycle ---

    def open(self, workspace: Workspace) -> None:
        if self._window is not None:
            return  # already open
        self._items = build_items(workspace)
        self._window = Adw.Window(transient_for=self._parent, modal=True)
        self._window.set_default_size(600, 400)
        self._window.set_title("Launcher")
        self._window.set_hide_on_close(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._entry = Gtk.SearchEntry()
        self._entry.set_hexpand(True)
        self._entry.connect("search-changed", self._on_search_changed)
        self._entry.connect("activate", self._on_activate)
        box.append(self._entry)

        self._store = Gio.ListStore(item_type=_LauncherRow)
        self._selection = Gtk.SingleSelection(model=self._store)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._row_setup)
        factory.connect("bind", self._row_bind)
        self._list_view = Gtk.ListView(model=self._selection, factory=factory)
        self._list_view.set_vexpand(True)
        self._list_view.connect("activate", self._on_row_activate)

        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self._list_view)
        scroller.set_vexpand(True)
        box.append(scroller)

        self._window.set_content(box)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key_pressed)
        self._window.add_controller(key)

        self._refresh()
        self._window.present()
        self._entry.grab_focus()

    def _close(self) -> None:
        if self._window is not None:
            self._window.close()
            self._window = None
            self._entry = None
            self._list_view = None
            self._store = None
            self._selection = None

    # --- handlers ---

    def _on_key_pressed(self, _ctrl, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._close()
            return True
        return False

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._refresh(entry.get_text())

    def _on_activate(self, _entry: Gtk.SearchEntry) -> None:
        self._activate_selected()

    def _on_row_activate(self, _lv, _pos) -> None:
        self._activate_selected()

    def _activate_selected(self) -> None:
        if self._selection is None or self._store is None:
            return
        idx = self._selection.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION:
            return
        row = self._store.get_item(idx)
        if row is None:
            return
        action = row.action  # type: ignore[attr-defined]
        Launcher.push_recent(self._recents, action, max_recents=MAX_RECENTS)
        self._close()
        self._dispatch(action)

    # --- list refresh ---

    def _refresh(self, query: str = "") -> None:
        if self._store is None:
            return
        self._store.remove_all()
        if query == "":
            visible_actions = Launcher.recents_in_items(self._recents, self._items)
            display_by_action = {it.action: it.display for it in self._items}
            rows = [
                _LauncherRow(display=display_by_action[a], action=a)
                for a in visible_actions
            ]
        else:
            filtered = Launcher.filter_items(query, self._items)
            rows = [_LauncherRow(display=it.display, action=it.action) for it in filtered]
        for r in rows:
            self._store.append(r)
        if self._selection is not None and self._store.get_n_items() > 0:
            self._selection.set_selected(0)

    def _row_setup(self, _factory, list_item: Gtk.ListItem) -> None:
        label = Gtk.Label(xalign=0)
        label.set_margin_start(8)
        label.set_margin_end(8)
        label.set_margin_top(4)
        label.set_margin_bottom(4)
        list_item.set_child(label)

    def _row_bind(self, _factory, list_item: Gtk.ListItem) -> None:
        row = list_item.get_item()
        label = list_item.get_child()
        if row is not None and isinstance(label, Gtk.Label):
            label.set_text(row.display)  # type: ignore[attr-defined]


class _LauncherRow(GObject.Object):
    """Boxed row for the GListStore. Plain attributes on a GObject suffice."""

    __gtype_name__ = "JFTermLauncherRow"

    def __init__(self, *, display: str, action: Action) -> None:
        super().__init__()
        self.display = display
        self.action = action
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_launcher.py -v`
Expected: all 4 tests pass. (The static-style helpers don't touch GTK.)

- [ ] **Step 5: Run the full check suite**

Run: `just check`
Expected: lint + format + typecheck + tests all pass.

- [ ] **Step 6: Commit**

```bash
git add src/jfterm/launcher.py tests/test_launcher.py
git commit -m "feat(launcher): popup widget with fuzzy search and recents"
```

---

## Task 5: Wire double-tap + dispatcher into `JFTermWindow`

**Files:**
- Modify: `src/jfterm/window.py` (around lines 103-120 — shortcuts setup)
- Modify: `src/jfterm/window.py` (add `_open_launcher`, `_dispatch_launcher_action`, init of `self._launcher` and detector)

The launcher object is stored on the window (`self._launcher`) so its recents survive across opens. The double-tap detector is held in `self._double_shift` and fed via a `Gtk.EventControllerKey` attached to the window.

`Shift_L` keyval is `Gdk.KEY_Shift_L`.

- [ ] **Step 1: Add the launcher field, detector, and key controller in `JFTermWindow.__init__`**

Insert this block in `src/jfterm/window.py` immediately after the existing `app.set_accels_for_action(...)` lines (currently around `window.py:120`):

```python
# Command launcher (issue #19)
from jfterm.double_tap import DoubleTapDetector
from jfterm.launcher import Launcher

self._launcher = Launcher(self, dispatch=self._dispatch_launcher_action)
self._double_shift = DoubleTapDetector(
    target_keyval=Gdk.KEY_Shift_L,
    interval_ms=300,
    callback=self._open_launcher,
)
key_ctrl = Gtk.EventControllerKey()
key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
key_ctrl.connect("key-pressed", self._on_window_key_pressed)
self.add_controller(key_ctrl)
```

Add to the existing `from gi.repository` import line (currently `from gi.repository import Adw, Gtk`) so it becomes:

```python
from gi.repository import Adw, Gdk, Gtk  # noqa: E402
```

- [ ] **Step 2: Add the three new methods at the bottom of `JFTermWindow`**

Append (before any module-level code) inside the class:

```python
def _on_window_key_pressed(self, _ctrl, keyval, _keycode, _state) -> bool:
    # Feed the double-tap detector. We never *consume* the event
    # (return False) so normal text input keeps working.
    from gi.repository import GLib

    self._double_shift.on_press(keyval, GLib.get_monotonic_time() // 1000)
    return False

def _open_launcher(self) -> None:
    self._double_shift.reset()
    self._launcher.open(self.ws)

def _dispatch_launcher_action(self, action) -> None:
    from jfterm.launcher_items import (
        FlashAction,
        JumpAction,
        NewTabAction,
        StartupAction,
    )

    if isinstance(action, FlashAction):
        self._on_flash_command_launched(self.sidebar, action.project, action.flash)
    elif isinstance(action, NewTabAction):
        self._spawn_tab(action.project)
    elif isinstance(action, StartupAction):
        self._on_launch_project(self.sidebar, action.project)
    elif isinstance(action, JumpAction):
        self._on_tab_activated(self.sidebar, action.tab)
```

- [ ] **Step 3: Add a unit test for the dispatcher**

Append to `tests/test_window.py`:

```python
def test_dispatch_launcher_action_routes_to_existing_handlers():
    from types import SimpleNamespace

    from jfterm.launcher_items import (
        FlashAction,
        JumpAction,
        NewTabAction,
        StartupAction,
    )
    from jfterm.models import FlashCommand, TerminalTab, Workspace

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
        _spawn_tab=lambda proj: calls.append(("new", proj)),
        _on_launch_project=lambda sb, proj: calls.append(("startup", proj)),
        _on_tab_activated=lambda sb, t: calls.append(("jump", t)),
    )

    JFTermWindow._dispatch_launcher_action(fake, FlashAction(p, fc))  # type: ignore[arg-type]
    JFTermWindow._dispatch_launcher_action(fake, NewTabAction(p))  # type: ignore[arg-type]
    JFTermWindow._dispatch_launcher_action(fake, StartupAction(p))  # type: ignore[arg-type]
    JFTermWindow._dispatch_launcher_action(fake, JumpAction(tab))  # type: ignore[arg-type]

    assert calls == [
        ("flash", p, fc),
        ("new", p),
        ("startup", p),
        ("jump", tab),
    ]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_window.py::test_dispatch_launcher_action_routes_to_existing_handlers -v`
Expected: PASS.

- [ ] **Step 5: Run the full check suite**

Run: `just check`
Expected: all green.

- [ ] **Step 6: Manual smoke test**

Run: `just run`

In the running app:
1. Press Left Shift twice quickly → launcher opens.
2. Type a project name → results filter.
3. Press Enter on a `New Shell Tab` row → a new shell tab appears in that project.
4. Open the launcher again → that action is the top recent item.
5. Press Esc → launcher closes.

Report any visual or behavioral issues; do not commit until they're fixed.

- [ ] **Step 7: Commit**

```bash
git add src/jfterm/window.py tests/test_window.py
git commit -m "feat(window): wire double-shift launcher into main window"
```

---

## Task 6: README mention

**Files:**
- Modify: `README.md` (Features list)

- [ ] **Step 1: Add a one-line bullet to the Features section**

Edit `README.md`. Find the `## Features` section and add as a new bullet:

```markdown
- Command launcher: double-tap Left Shift to fuzzy-search every flash
  command, project action, and open tab in one ranked list.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): mention command launcher (issue #19)"
```

---

## Done

All tasks complete: fuzzy matcher, item builder, double-tap detector, launcher widget, dispatcher wiring, README. Run `just check` once more to confirm a clean tree.
