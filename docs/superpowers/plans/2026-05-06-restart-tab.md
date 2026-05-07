# Restart-tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-tab refresh button (visible only on tabs launched with a startup command) that kills the current shell and re-spawns a new one running the same command in the same tab slot.

**Architecture:** Track `launched_command` and `is_restarting` on the `Tab` model. The sidebar shows a refresh button between title and close when `launched_command` is set, emitting a new `restart-tab-requested` signal. The window handles restart by signal-killing the old shell, swapping a fresh `JFTermTerminal` into the same `Gtk.Stack` slot, and re-wiring tab event handlers. The `is_restarting` flag suppresses the old terminal's `child-exited` from removing the tab.

**Tech Stack:** Python, GTK4 / Adwaita, VTE (`Vte.Terminal`), pytest.

Spec: [docs/superpowers/specs/2026-05-06-restart-tab-design.md](../specs/2026-05-06-restart-tab-design.md)

---

## File Structure

- `src/jfterm/models.py` — add `launched_command: str | None` and `is_restarting: bool` fields to `Tab`.
- `src/jfterm/sidebar.py` — add `restart-tab-requested` signal; render a refresh button on rows where `tab.launched_command` is truthy.
- `src/jfterm/window.py` — set `tab.launched_command` in `_spawn_tab`; extract `_wire_terminal` helper; add `_on_restart_tab`; add early-return in `_on_close_tab` when `tab.is_restarting`; connect new sidebar signal.
- `tests/test_models.py` — verify new `Tab` field defaults.
- `tests/test_window.py` (new) — verify `_on_close_tab` skips removal when `is_restarting`.

---

## Task 1: Add Tab fields

**Files:**
- Modify: `src/jfterm/models.py:17-26`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
def test_tab_has_launched_command_and_is_restarting_defaults():
    from jfterm.models import Tab
    t = Tab(title="x")
    assert t.launched_command is None
    assert t.is_restarting is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py::test_tab_has_launched_command_and_is_restarting_defaults -v`
Expected: FAIL with `AttributeError: 'Tab' object has no attribute 'launched_command'`.

- [ ] **Step 3: Add the fields**

In `src/jfterm/models.py`, edit the `Tab` dataclass to add the two fields after `osc133_seen`:

```python
@dataclass
class Tab:
    title: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
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
    # True while a restart is in flight, so the old terminal's child-exited
    # signal does not remove the tab from its group.
    is_restarting: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: all model tests pass, including the new one.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/models.py tests/test_models.py
git commit -m "feat(models): track launched command and restart flag on Tab"
```

---

## Task 2: Set `launched_command` in `_spawn_tab`

**Files:**
- Modify: `src/jfterm/window.py:100-135`

- [ ] **Step 1: Update `_spawn_tab` to record the command**

In `src/jfterm/window.py`, find:

```python
        tab = Tab(title=command or "(starting…)", terminal=terminal)
```

Replace with:

```python
        tab = Tab(
            title=command or "(starting…)",
            terminal=terminal,
            launched_command=command,
        )
```

- [ ] **Step 2: Sanity check the app still imports**

Run: `uv run python -c "import jfterm.window"`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(window): record launched command on spawned tabs"
```

---

## Task 3: Extract `_wire_terminal` helper

**Files:**
- Modify: `src/jfterm/window.py:100-135`

- [ ] **Step 1: Add the helper and use it from `_spawn_tab`**

In `src/jfterm/window.py`, replace the body of `_spawn_tab` from the four `terminal.connect(...)` calls down through `self.terminal_stack.add_child(terminal)` so that the connect block becomes a single call to a new helper.

Final shape of `_spawn_tab` (preserving everything else):

```python
    def _spawn_tab(
        self,
        group: Group,
        *,
        command: str | None = None,
        focus: bool = True,
    ) -> Tab:
        cwd = group.directory if isinstance(group, Project) else None
        terminal = JFTermTerminal(cwd=cwd, send_after_spawn=command)
        terminal.set_vexpand(True)
        terminal.set_hexpand(True)
        tab = Tab(
            title=command or "(starting…)",
            terminal=terminal,
            launched_command=command,
        )
        self._wire_terminal(tab, terminal)
        self.terminal_stack.add_child(terminal)
        group.add_tab(tab)
        self._current_group = group
        self.sidebar.refresh()
        if focus:
            self.terminal_stack.set_visible_child(terminal)
            terminal.grab_focus()
        return tab

    def _wire_terminal(self, tab: Tab, terminal: JFTermTerminal) -> None:
        terminal.connect(
            "cwd-changed",
            lambda _t, path, t=tab: self._on_tab_cwd_changed(t, path),
        )
        terminal.connect(
            "running-changed",
            lambda _t, running, t=tab: self._on_tab_running_changed(t, running),
        )
        terminal.connect(
            "title-changed",
            lambda _t, title, t=tab: self._on_tab_title_changed(t, title),
        )
        terminal.connect(
            "child-exited",
            lambda _t, _status, t=tab: self._on_close_tab(self.sidebar, t),
        )
```

- [ ] **Step 2: Sanity check**

Run: `uv run python -c "import jfterm.window"`
Expected: clean import.

Run: `uv run pytest -q`
Expected: all existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/jfterm/window.py
git commit -m "refactor(window): extract _wire_terminal helper for reuse"
```

---

## Task 4: Skip close when restarting

**Files:**
- Modify: `src/jfterm/window.py` (top of `_on_close_tab`)
- Test: `tests/test_window.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_window.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_window.py -v`
Expected: FAIL — the tab is removed because the early return doesn't exist yet.

- [ ] **Step 3: Add the early return**

In `src/jfterm/window.py`, edit `_on_close_tab`. Find:

```python
    def _on_close_tab(self, _sb, tab: Tab) -> None:
        group = self.ws._find_group(tab)
```

Replace with:

```python
    def _on_close_tab(self, _sb, tab: Tab) -> None:
        if tab.is_restarting:
            return
        group = self.ws._find_group(tab)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_window.py -v`
Expected: PASS.

Run: `uv run pytest -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/window.py tests/test_window.py
git commit -m "feat(window): skip close handler when tab is_restarting"
```

---

## Task 5: Sidebar refresh button + signal

**Files:**
- Modify: `src/jfterm/sidebar.py:30-40` (signal list)
- Modify: `src/jfterm/sidebar.py:204-250` (`_add_tab_row`)

- [ ] **Step 1: Add the new signal**

In `src/jfterm/sidebar.py`, find the `__gsignals__` dict and add the entry:

```python
        "restart-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
```

Place it on the line immediately after `"close-tab-requested"` so related signals stay grouped.

- [ ] **Step 2: Render the refresh button on relevant rows**

In `_add_tab_row`, find:

```python
        close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close.add_css_class("flat")
        close.connect(
            "clicked", lambda _b, t=tab: self.emit("close-tab-requested", t)
        )

        # DnD: the row is both a drag source (carrying the tab) and a drop
        # target (drop above this row, taking this row's index).
        position_in_group = group.tabs.index(tab)
        self._attach_drag(row, tab)
        self._attach_drop(row, group, lambda pos=position_in_group: pos)

        for w in (dot, title, close):
            row.append(w)
        self._box.append(row)
```

Replace with:

```python
        restart: Gtk.Button | None = None
        if tab.launched_command:
            restart = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
            restart.add_css_class("flat")
            restart.set_tooltip_text("Restart command")
            restart.connect(
                "clicked",
                lambda _b, t=tab: self.emit("restart-tab-requested", t),
            )

        close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close.add_css_class("flat")
        close.connect(
            "clicked", lambda _b, t=tab: self.emit("close-tab-requested", t)
        )

        # DnD: the row is both a drag source (carrying the tab) and a drop
        # target (drop above this row, taking this row's index).
        position_in_group = group.tabs.index(tab)
        self._attach_drag(row, tab)
        self._attach_drop(row, group, lambda pos=position_in_group: pos)

        widgets: list[Gtk.Widget] = [dot, title]
        if restart is not None:
            widgets.append(restart)
        widgets.append(close)
        for w in widgets:
            row.append(w)
        self._box.append(row)
```

- [ ] **Step 3: Sanity check**

Run: `uv run python -c "import jfterm.sidebar"`
Expected: clean import.

Run: `uv run pytest -q`
Expected: full suite green.

- [ ] **Step 4: Commit**

```bash
git add src/jfterm/sidebar.py
git commit -m "feat(sidebar): refresh button on tabs with a launched command"
```

---

## Task 6: Window `_on_restart_tab` handler

**Files:**
- Modify: `src/jfterm/window.py` (sidebar signal connections, new method)

- [ ] **Step 1: Connect the new sidebar signal**

In `src/jfterm/window.py`, locate the block of `self.sidebar.connect(...)` calls (around lines 59-71) and add:

```python
        self.sidebar.connect("restart-tab-requested", self._on_restart_tab)
```

Place it immediately after the `close-tab-requested` connection so related handlers stay grouped.

- [ ] **Step 2: Add the imports needed by the handler**

At the top of `src/jfterm/window.py`, ensure these stdlib imports are present (add any that aren't):

```python
import os
import signal
```

- [ ] **Step 3: Implement `_on_restart_tab`**

Add this method to `JFTermWindow`. Place it directly after `_on_close_tab`:

```python
    def _on_restart_tab(self, _sb, tab: Tab) -> None:
        if not tab.launched_command:
            return
        from gi.repository import GLib

        from jfterm.terminal import JFTermTerminal

        group = self.ws._find_group(tab)
        cwd = group.directory if isinstance(group, Project) else None
        command = tab.launched_command
        was_visible = (
            tab.terminal is not None
            and self.terminal_stack.get_visible_child() is tab.terminal
        )
        old_terminal = tab.terminal
        old_pid = tab.shell_pid

        # Block the old terminal's child-exited from closing the tab.
        tab.is_restarting = True

        # SIGTERM now; SIGKILL after grace period if still alive.
        if old_pid is not None:
            try:
                os.kill(old_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

            def _force_kill(pid: int = old_pid) -> bool:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return False
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                return False

            GLib.timeout_add(1500, _force_kill)

        # Swap in a fresh terminal for the same tab.
        if old_terminal is not None:
            self.terminal_stack.remove(old_terminal)

        new_terminal = JFTermTerminal(cwd=cwd, send_after_spawn=command)
        new_terminal.set_vexpand(True)
        new_terminal.set_hexpand(True)

        tab.terminal = new_terminal
        tab.shell_pid = None
        tab.pty_fd = None
        tab.is_running = False
        tab.osc133_seen = False
        tab.title = command

        self._wire_terminal(tab, new_terminal)
        self.terminal_stack.add_child(new_terminal)

        # The flag has done its job — the new terminal's child-exited should
        # close the tab normally.
        tab.is_restarting = False

        if was_visible:
            self.terminal_stack.set_visible_child(new_terminal)
            new_terminal.grab_focus()

        self.sidebar.refresh()
```

- [ ] **Step 4: Sanity check**

Run: `uv run python -c "import jfterm.window"`
Expected: clean import.

Run: `uv run pytest -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(window): restart-tab handler kills shell and re-spawns command"
```

---

## Task 7: Manual verification

**No code changes** — this is a checklist run inside a real X/Wayland session.

- [ ] **Step 1: Run the app**

Run: `uv run jfterm` (or whatever the entry point is — check `pyproject.toml` `[project.scripts]`).
Expected: app launches.

- [ ] **Step 2: Configure a project with a startup command**

Create or edit a project; add a startup command like `sleep 100` (long-running, easy to spot).

- [ ] **Step 3: Launch the project**

Click the project's launch action.
Expected: a tab opens running `sleep 100`. The sidebar row for that tab shows three buttons: status dot, title, then refresh and close icons.

- [ ] **Step 4: Restart the running tab**

Click the refresh button.
Expected: the tab stays in the same sidebar slot. The previous shell is killed; a new shell starts and `sleep 100` runs again. Title updates to the command.

- [ ] **Step 5: Restart an already-exited tab**

Run a startup command like `echo done` so it exits quickly. After it exits, click refresh.
Expected: the tab is still there (it wasn't auto-closed during the brief run), and clicking refresh re-runs `echo done`. (If the tab was auto-closed by `child-exited`, that's expected today — note this in your report.)

- [ ] **Step 6: Close (not restart) a startup-command tab**

Click the close button on a startup-command tab.
Expected: the tab closes normally, same as before this feature.

- [ ] **Step 7: Plain new-tab still has no refresh button**

Open a new tab via the project's `+` button (no startup command).
Expected: only status dot, title, and close — no refresh button.

- [ ] **Step 8: Report findings**

If everything passes, say so. If any step misbehaves, capture exact symptom and stop — don't paper over it.

---

## Self-review notes

- Spec coverage: data model (Task 1), spawn-time field set (Task 2), refactor for reuse (Task 3), close-tab guard (Task 4), sidebar UI + signal (Task 5), restart handler (Task 6), manual verification (Task 7). All spec sections covered.
- No placeholders. Every code step shows the actual code.
- Type/name consistency: `launched_command`, `is_restarting`, `_wire_terminal`, `restart-tab-requested` used identically across all tasks.
