# Flash Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-project "flash commands" — quick one-shot commands launched from a dropdown next to the project play button, run in a new tab, auto-closed on success.

**Architecture:** New `FlashCommand` dataclass on `Project`, persisted alongside `startup_commands`. Sidebar gets a `Gtk.MenuButton` per project row that pops a `Gio.Menu` of flash commands and emits a new signal. The window handler spawns a tab with a wrapped command string that exits on success. Project edit dialog gets a parallel drag-and-drop list.

**Tech Stack:** Python 3, GTK4 / libadwaita / VTE via PyGObject, pytest.

**Spec:** `docs/superpowers/specs/2026-05-06-flash-commands-design.md`

---

## Task 1: Add `FlashCommand` model and `Project.flash_commands`

**Files:**
- Modify: `src/jfterm/models.py`
- Modify: `tests/test_models.py` (or create if absent — check first)

- [ ] **Step 1: Inspect existing model tests**

Run: `cat tests/test_models.py`
Note the import style and assertion style used. If there are no existing tests for `StartupCommand`/`Project`, add ours at the end.

- [ ] **Step 2: Write failing tests**

Append to `tests/test_models.py`:

```python
from jfterm.models import FlashCommand, Project


def test_flash_command_defaults():
    fc = FlashCommand(name="Push", command="git push")
    assert fc.name == "Push"
    assert fc.command == "git push"
    assert fc.keep_open_on_success is False
    assert fc.focus_on_launch is True


def test_project_default_flash_commands_is_empty_list():
    p = Project(name="A", directory="/tmp/a")
    assert p.flash_commands == []


def test_project_accepts_flash_commands():
    fc = FlashCommand(name="Push", command="git push", keep_open_on_success=True)
    p = Project(name="A", directory="/tmp/a", flash_commands=[fc])
    assert p.flash_commands == [fc]
```

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/test_models.py -v`
Expected: ImportError on `FlashCommand` or AttributeError on `flash_commands`.

- [ ] **Step 4: Implement `FlashCommand` and add to `Project`**

In `src/jfterm/models.py`, add after the existing `StartupCommand` dataclass:

```python
@dataclass
class FlashCommand:
    """A one-shot command launched from the project's flash menu."""

    name: str
    command: str
    keep_open_on_success: bool = False
    focus_on_launch: bool = True
```

Update `Project.__init__` signature and body. The new keyword goes after `spawn_blank_after_startup`:

```python
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
    self._extra: dict[str, Any] = {}
```

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/jfterm/models.py tests/test_models.py
git commit -m "feat(models): add FlashCommand and Project.flash_commands"
```

---

## Task 2: Persist flash commands

**Files:**
- Modify: `src/jfterm/persistence.py`
- Modify: `tests/test_persistence.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_persistence.py`:

```python
from jfterm.models import FlashCommand


def test_flash_commands_roundtrip(tmp_path: Path):
    ws = Workspace()
    p = ws.add_project(name="A", directory="/tmp/a")
    p.flash_commands = [
        FlashCommand(name="Push", command="git push"),
        FlashCommand(
            name="Check",
            command="just check",
            keep_open_on_success=True,
            focus_on_launch=False,
        ),
    ]

    path = tmp_path / "projects.json"
    save_projects(ws, path)
    ws2 = Workspace()
    load_projects(ws2, path)

    fcs = ws2.projects[0].flash_commands
    assert [(f.name, f.command, f.keep_open_on_success, f.focus_on_launch) for f in fcs] == [
        ("Push", "git push", False, True),
        ("Check", "just check", True, False),
    ]


def test_load_missing_flash_commands_defaults_to_empty(tmp_path: Path):
    path = tmp_path / "projects.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "projects": [
                    {"id": "x", "name": "A", "directory": "/tmp/a", "expanded": True}
                ],
            }
        )
    )
    ws = Workspace()
    load_projects(ws, path)
    assert ws.projects[0].flash_commands == []
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_persistence.py -v`
Expected: `flash_commands` round-trip test fails.

- [ ] **Step 3: Implement persistence**

In `src/jfterm/persistence.py`:

Update imports:

```python
from jfterm.models import FlashCommand, Project, StartupCommand, Workspace
```

Add to `_KNOWN_FIELDS`:

```python
_KNOWN_FIELDS = {
    "id",
    "name",
    "directory",
    "expanded",
    "startup_commands",
    "spawn_blank_after_startup",
    "flash_commands",
}
```

Add a loader after `_load_commands`:

```python
def _load_flash_commands(raw: list) -> list[FlashCommand]:
    out: list[FlashCommand] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            FlashCommand(
                name=str(item.get("name", "")),
                command=str(item.get("command", "")),
                keep_open_on_success=bool(item.get("keep_open_on_success", False)),
                focus_on_launch=bool(item.get("focus_on_launch", True)),
            )
        )
    return out
```

Update `load_projects` to pass it in:

```python
p = Project(
    id=entry["id"],
    name=entry["name"],
    directory=entry["directory"],
    expanded=entry.get("expanded", True),
    startup_commands=_load_commands(entry.get("startup_commands", [])),
    spawn_blank_after_startup=bool(entry.get("spawn_blank_after_startup", False)),
    flash_commands=_load_flash_commands(entry.get("flash_commands", [])),
)
```

Update `save_projects` payload to include flash commands:

```python
"flash_commands": [
    {
        "name": fc.name,
        "command": fc.command,
        "keep_open_on_success": fc.keep_open_on_success,
        "focus_on_launch": fc.focus_on_launch,
    }
    for fc in p.flash_commands
],
```

Place this entry inside the project dict after `spawn_blank_after_startup`.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_persistence.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/persistence.py tests/test_persistence.py
git commit -m "feat(persistence): save and load flash commands"
```

---

## Task 3: Command-wrapping helper

This is the small pure function that builds the string fed to the shell.
Putting it in its own module keeps it testable without GTK.

**Files:**
- Create: `src/jfterm/flash.py`
- Create: `tests/test_flash.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_flash.py`:

```python
from jfterm.flash import wrap_flash_command
from jfterm.models import FlashCommand


def test_wrap_keep_open_returns_command_unchanged():
    fc = FlashCommand(name="X", command="echo hi", keep_open_on_success=True)
    assert wrap_flash_command(fc) == "echo hi"


def test_wrap_close_on_success_wraps_with_exit_logic():
    fc = FlashCommand(name="X", command="echo hi")
    out = wrap_flash_command(fc)
    assert out == (
        '{ echo hi; }; __ec=$?; if [ $__ec -eq 0 ]; then exit; '
        'else echo "Command failed (exit $__ec)"; fi'
    )


def test_wrap_handles_command_with_semicolons_and_and():
    fc = FlashCommand(name="X", command="a && b; c")
    out = wrap_flash_command(fc)
    # The whole user command must be inside the brace group, so the
    # semicolons within don't escape it.
    assert out.startswith("{ a && b; c; }; ")
    assert "if [ $__ec -eq 0 ]; then exit;" in out
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_flash.py -v`
Expected: ImportError on `jfterm.flash`.

- [ ] **Step 3: Implement**

Create `src/jfterm/flash.py`:

```python
from __future__ import annotations

from jfterm.models import FlashCommand


def wrap_flash_command(fc: FlashCommand) -> str:
    """Build the shell string fed to the freshly spawned shell.

    With keep_open_on_success the command is returned as-is; the shell
    naturally remains after it finishes regardless of exit status.

    Otherwise the command is grouped and followed by exit-on-success /
    failure-message-and-stay logic. The brace group ensures embedded
    semicolons or && operators don't escape the wrapper.
    """
    if fc.keep_open_on_success:
        return fc.command
    return (
        "{ " + fc.command + "; }; __ec=$?; "
        "if [ $__ec -eq 0 ]; then exit; "
        'else echo "Command failed (exit $__ec)"; fi'
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_flash.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/flash.py tests/test_flash.py
git commit -m "feat(flash): add wrap_flash_command helper"
```

---

## Task 4: Sidebar flash menu button + signal

**Files:**
- Modify: `src/jfterm/sidebar.py`

This task is GTK-only and is verified manually in Task 6 alongside the
window wiring. No unit test here.

- [ ] **Step 1: Add the `flash-command-launched` signal**

In `src/jfterm/sidebar.py`, extend `__gsignals__` on `Sidebar`:

```python
"flash-command-launched": (GObject.SignalFlags.RUN_FIRST, None, (object, object)),
```

(Both args are passed as Python objects: the `Project` and the `FlashCommand`.)

- [ ] **Step 2: Update imports**

At the top of `src/jfterm/sidebar.py`, change the model import:

```python
from jfterm.models import FlashCommand, Group, Project, Tab, Workspace
```

And add `Gio`:

```python
from gi.repository import Gdk, Gio, GObject, Gtk
```

- [ ] **Step 3: Build the menu button in `_add_project_row`**

In `_add_project_row` (around line 143, just after the `play` button is built and connected), insert the flash menu button before the `cog` button. Replace the line:

```python
for w in (chevron, label_btn, play, cog, plus):
```

with the block below, inserted right after `play.connect(...)`:

```python
flash = Gtk.MenuButton()
flash.set_icon_name("weather-storm-symbolic")
flash.add_css_class("flat")
flash.set_tooltip_text("Flash commands")
flash.set_sensitive(bool(project.flash_commands))
flash.set_popover(self._build_flash_popover(project))
```

And update the row-append loop:

```python
for w in (chevron, label_btn, play, flash, cog, plus):
    row.append(w)
```

- [ ] **Step 4: Add `_build_flash_popover` method**

Add to the `Sidebar` class (placement: after `_add_project_row`):

```python
def _build_flash_popover(self, project: Project) -> Gtk.Popover:
    pop = Gtk.Popover()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.set_margin_start(4)
    box.set_margin_end(4)
    box.set_margin_top(4)
    box.set_margin_bottom(4)
    if not project.flash_commands:
        empty = Gtk.Label(label="(no flash commands)")
        empty.add_css_class("dim-label")
        box.append(empty)
    else:
        for fc in project.flash_commands:
            btn = Gtk.Button(label=fc.name)
            btn.add_css_class("flat")
            btn.set_halign(Gtk.Align.FILL)

            def _on_click(_b, p=project, c=fc, popover=pop):
                popover.popdown()
                self.emit("flash-command-launched", p, c)

            btn.connect("clicked", _on_click)
            box.append(btn)
    pop.set_child(box)
    return pop
```

`Gio` import in step 2 is needed only if you later switch to a `Gio.Menu`;
the simpler button-list popover above doesn't strictly require it. Leave the
import in — the linter will complain if unused, in which case remove it.

- [ ] **Step 5: Verify the import is needed; remove if not**

Run: `uv run ruff check src/jfterm/sidebar.py`
If ruff flags `Gio` as unused, drop it from the import line.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check src/jfterm/sidebar.py && uv run pyright src/jfterm/sidebar.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/jfterm/sidebar.py
git commit -m "feat(sidebar): add flash command menu button and signal"
```

---

## Task 5: Window handler — spawn tab for flash command

**Files:**
- Modify: `src/jfterm/window.py`

- [ ] **Step 1: Update imports**

Change the model import:

```python
from jfterm.models import FlashCommand, Group, Project, StartupCommand, Tab, Workspace
```

Add the flash helper import (top-level imports, near the other `from jfterm.*`):

```python
from jfterm.flash import wrap_flash_command
```

- [ ] **Step 2: Wire the new signal**

Where the other sidebar signals are connected (~line 67), add:

```python
self.sidebar.connect("flash-command-launched", self._on_flash_command_launched)
```

- [ ] **Step 3: Add the handler method**

Add anywhere in the class (e.g. after `_on_launch_project`):

```python
def _on_flash_command_launched(
    self, _sb, project: Project, fc: FlashCommand
) -> None:
    if not project.expanded:
        project.expanded = True
        save_projects(self.ws, default_path())
        self.sidebar.refresh()
    wrapped = wrap_flash_command(fc)
    tab = self._spawn_tab(project, command=wrapped, focus=fc.focus_on_launch)
    tab.title = f"⚡ {fc.name}"
    self.sidebar.refresh()
```

`⚡` is the high-voltage / lightning bolt emoji (⚡).

- [ ] **Step 4: Lint and type-check**

Run: `uv run ruff check src/jfterm/window.py && uv run pyright src/jfterm/window.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(window): launch flash command in new tab"
```

---

## Task 6: Manual verification of launch path

The next task adds the config UI; before doing that, verify the launch
machinery works using a hand-edited config. This catches plumbing bugs
before more code is layered on.

**Files:** none (manual)

- [ ] **Step 1: Hand-edit the config**

Locate `~/.config/jfterm/projects.json` (or `$XDG_CONFIG_HOME/jfterm/projects.json`). Pick any project entry and add:

```json
"flash_commands": [
  { "name": "Echo OK", "command": "echo hello", "keep_open_on_success": false, "focus_on_launch": true },
  { "name": "Fail", "command": "false", "keep_open_on_success": false, "focus_on_launch": true },
  { "name": "Stay", "command": "echo stays", "keep_open_on_success": true, "focus_on_launch": true },
  { "name": "Background", "command": "echo bg", "keep_open_on_success": false, "focus_on_launch": false }
]
```

- [ ] **Step 2: Launch the app**

Run: `uv run jfterm` (or whatever the project's run command is — check `pyproject.toml`/`justfile`).

- [ ] **Step 3: Verify each flash command**

For the project with the entries above:
- Click the lightning-bolt menu button. Verify all four items appear in order.
- "Echo OK" → tab opens, prints `hello`, auto-closes.
- "Fail" → tab opens, prints `Command failed (exit 1)`, shell prompt remains.
- "Stay" → tab opens, prints `stays`, shell prompt remains (no failure message).
- "Background" → tab is created in the project but the current tab stays focused.
- All tab titles begin with ⚡.

If any step fails, debug and re-test before continuing.

- [ ] **Step 4: Restore your config**

Either keep the test entries or remove them — your call.

---

## Task 7: Config UI in project dialog

**Files:**
- Modify: `src/jfterm/dialogs.py`
- Modify: `src/jfterm/window.py`

The dialog signature gains two new keyword args: `initial_flash_commands`
and the `on_save` callback gets a fifth argument (`list[FlashCommand]`).

- [ ] **Step 1: Update `dialogs.py` imports and signature**

Change the import:

```python
from jfterm.models import FlashCommand, StartupCommand
```

Update `show_project_dialog` signature:

```python
def show_project_dialog(
    parent: Gtk.Window,
    *,
    title: str,
    initial_name: str = "",
    initial_directory: str = "",
    initial_commands: list[StartupCommand] | None = None,
    initial_spawn_blank_after_startup: bool = False,
    initial_flash_commands: list[FlashCommand] | None = None,
    on_save: Callable[
        [str, str, list[StartupCommand], bool, list[FlashCommand]], None
    ],
    on_disband: Callable[[], None] | None = None,
) -> None:
```

- [ ] **Step 2: Add a separate `_RowRef` class for flash rows**

Right below the existing `_RowRef`, add:

```python
class _FlashRowRef(GObject.Object):
    """Carrier so a flash-command row can travel through GValue DnD.

    Distinct from _RowRef so dragging a startup row can't drop into the
    flash list (different GType).
    """

    def __init__(self, row: Gtk.Widget) -> None:
        super().__init__()
        self.row = row
```

- [ ] **Step 3: Build the flash commands editor block**

Inside `show_project_dialog`, after the `add_cmd_btn` for startup commands is created (~line 185), and before `spawn_blank_check`, add the new editor. Insert this block:

```python
# --- flash commands editor ---

flash_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
flash_handle_spacer = Gtk.Image.new_from_icon_name("open-menu-symbolic")
flash_handle_spacer.set_opacity(0)
flash_name_header = Gtk.Label(label="Name", xalign=0)
flash_name_header.add_css_class("dim-label")
flash_name_header.set_width_chars(14)
flash_cmd_header = Gtk.Label(label="Command", xalign=0)
flash_cmd_header.add_css_class("dim-label")
flash_cmd_header.set_hexpand(True)
flash_keep_header = Gtk.Label(label="Keep open\non exit 0", xalign=0)
flash_keep_header.add_css_class("dim-label")
flash_focus_header = Gtk.Label(label="Focus", xalign=0)
flash_focus_header.add_css_class("dim-label")
flash_delete_spacer = Gtk.Image.new_from_icon_name("user-trash-symbolic")
flash_delete_spacer.set_opacity(0)
for w in (
    flash_handle_spacer,
    flash_name_header,
    flash_cmd_header,
    flash_keep_header,
    flash_focus_header,
    flash_delete_spacer,
):
    flash_header.append(w)

flash_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
# Each entry: (row, name_entry, cmd_entry, keep_check, focus_check)
flash_rows: list[
    tuple[Gtk.Box, Gtk.Entry, Gtk.Entry, Gtk.CheckButton, Gtk.CheckButton]
] = []

def _move_flash_row(src_row: Gtk.Box, dst_row: Gtk.Box) -> None:
    if src_row is dst_row:
        return
    src_idx = next((i for i, t in enumerate(flash_rows) if t[0] is src_row), None)
    dst_idx = next((i for i, t in enumerate(flash_rows) if t[0] is dst_row), None)
    if src_idx is None or dst_idx is None:
        return
    item = flash_rows.pop(src_idx)
    new_dst = next(i for i, t in enumerate(flash_rows) if t[0] is dst_row)
    flash_rows.insert(new_dst, item)
    for r, *_ in flash_rows:
        flash_box.remove(r)
    for r, *_ in flash_rows:
        flash_box.append(r)

def _add_flash_row(
    initial_name: str = "",
    initial_command: str = "",
    initial_keep_open: bool = False,
    initial_focus: bool = True,
) -> None:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

    handle = Gtk.Image.new_from_icon_name("open-menu-symbolic")
    handle.add_css_class("dim-label")
    handle.set_tooltip_text("Drag to reorder")
    handle.set_cursor(Gdk.Cursor.new_from_name("grab", None))

    name_entry = Gtk.Entry(placeholder_text="e.g. Git push")
    name_entry.set_text(initial_name)
    name_entry.set_width_chars(14)

    cmd_entry = Gtk.Entry(placeholder_text="e.g. git push")
    cmd_entry.set_text(initial_command)
    cmd_entry.set_hexpand(True)

    keep_check = Gtk.CheckButton()
    keep_check.set_active(initial_keep_open)
    keep_check.set_tooltip_text("Don't auto-close the tab when the command exits 0")

    focus_check = Gtk.CheckButton()
    focus_check.set_active(initial_focus)
    focus_check.set_tooltip_text("Switch to the tab when launching the command")

    delete = Gtk.Button.new_from_icon_name("user-trash-symbolic")
    delete.add_css_class("flat")
    delete.set_tooltip_text("Remove flash command")

    def _on_delete(_b, r=row):
        flash_box.remove(r)
        for i, t in enumerate(flash_rows):
            if t[0] is r:
                flash_rows.pop(i)
                break

    delete.connect("clicked", _on_delete)

    src = Gtk.DragSource()
    src.set_actions(Gdk.DragAction.MOVE)

    def _prepare(_s, _x, _y, r=row):
        v = GObject.Value()
        v.init(_FlashRowRef.__gtype__)
        v.set_object(_FlashRowRef(r))
        return Gdk.ContentProvider.new_for_value(v)

    def _drag_begin(s, _drag, r=row):
        s.set_icon(Gtk.WidgetPaintable.new(r), 0, 0)

    src.connect("prepare", _prepare)
    src.connect("drag-begin", _drag_begin)
    handle.add_controller(src)

    target = Gtk.DropTarget.new(_FlashRowRef.__gtype__, Gdk.DragAction.MOVE)

    def _on_drop(_t, value, _x, _y, dst=row):
        src_row = value.row if isinstance(value, _FlashRowRef) else None
        if src_row is None:
            return False
        _move_flash_row(src_row, dst)
        return True

    target.connect("drop", _on_drop)
    row.add_controller(target)

    for w in (handle, name_entry, cmd_entry, keep_check, focus_check, delete):
        row.append(w)
    flash_box.append(row)
    flash_rows.append((row, name_entry, cmd_entry, keep_check, focus_check))

for fc in initial_flash_commands or []:
    _add_flash_row(fc.name, fc.command, fc.keep_open_on_success, fc.focus_on_launch)

add_flash_btn = Gtk.Button(label="Add flash command")
add_flash_btn.add_css_class("flat")
add_flash_btn.connect("clicked", lambda _b: _add_flash_row())
```

- [ ] **Step 4: Update `_on_save_clicked` to collect flash commands**

Replace the existing `_on_save_clicked` with:

```python
def _on_save_clicked(_b):
    name = name_entry.get_text().strip()
    directory = dir_entry.get_text().strip()
    if not name or not directory:
        return
    commands = [
        StartupCommand(command=text, delay=int(delay_w.get_value()))
        for _row, entry, delay_w in command_rows
        if (text := entry.get_text().strip())
    ]
    flash = [
        FlashCommand(
            name=fname,
            command=fcmd,
            keep_open_on_success=keep_w.get_active(),
            focus_on_launch=focus_w.get_active(),
        )
        for _row, name_w, cmd_w, keep_w, focus_w in flash_rows
        if (fname := name_w.get_text().strip()) and (fcmd := cmd_w.get_text().strip())
    ]
    on_save(name, directory, commands, spawn_blank_check.get_active(), flash)
    dlg.close()
```

- [ ] **Step 5: Add the new widgets to the dialog layout**

Update the `for w in (...)` loop near the bottom of `show_project_dialog` to insert the new section between `add_cmd_btn` and `spawn_blank_check`:

```python
for w in (
    Gtk.Label(label="Name", xalign=0),
    name_entry,
    Gtk.Label(label="Directory", xalign=0),
    dir_row,
    Gtk.Label(label="Startup commands (one tab per command)", xalign=0),
    commands_header,
    commands_box,
    add_cmd_btn,
    Gtk.Label(label="Flash commands", xalign=0),
    flash_header,
    flash_box,
    add_flash_btn,
    spawn_blank_check,
    actions,
):
    box.append(w)
```

- [ ] **Step 6: Update both call sites in `window.py`**

In `src/jfterm/window.py`, update `_on_new_project`:

```python
def _on_new_project(self, _sb) -> None:
    from jfterm.dialogs import show_project_dialog

    def _save(
        name: str,
        directory: str,
        commands: list[StartupCommand],
        spawn_blank_after_startup: bool,
        flash_commands: list[FlashCommand],
    ) -> None:
        p = self.ws.add_project(name=name, directory=directory)
        p.startup_commands = commands
        p.spawn_blank_after_startup = spawn_blank_after_startup
        p.flash_commands = flash_commands
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    show_project_dialog(self, title="New project", on_save=_save)
```

And `_on_configure_project`:

```python
def _on_configure_project(self, _sb, project: Project) -> None:
    from jfterm.dialogs import show_project_dialog

    def _save(
        name: str,
        directory: str,
        commands: list[StartupCommand],
        spawn_blank_after_startup: bool,
        flash_commands: list[FlashCommand],
    ) -> None:
        project.name = name
        project.directory = directory
        project.startup_commands = commands
        project.spawn_blank_after_startup = spawn_blank_after_startup
        project.flash_commands = flash_commands
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    def _disband() -> None:
        self.ws.disband(project)
        if self._current_group is project:
            self._current_group = self.ws.unsorted
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    show_project_dialog(
        self,
        title=f"Configure {project.name}",
        initial_name=project.name,
        initial_directory=project.directory,
        initial_commands=project.startup_commands,
        initial_spawn_blank_after_startup=project.spawn_blank_after_startup,
        initial_flash_commands=project.flash_commands,
        on_save=_save,
        on_disband=_disband,
    )
```

- [ ] **Step 7: Lint and type-check**

Run: `uv run ruff check src/jfterm/dialogs.py src/jfterm/window.py && uv run pyright src/jfterm/dialogs.py src/jfterm/window.py`
Expected: clean.

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/jfterm/dialogs.py src/jfterm/window.py
git commit -m "feat(dialogs): add flash commands editor to project dialog"
```

---

## Task 8: Final manual verification

**Files:** none (manual)

- [ ] **Step 1: Launch the app**

Run: `uv run jfterm`

- [ ] **Step 2: Configure a project's flash commands via the UI**

- Open a project's settings (cog icon).
- In the new "Flash commands" section, click "Add flash command".
- Add three entries:
  - `Echo` / `echo hi` (defaults)
  - `Stay` / `echo stay` / Keep-open checked
  - `Background` / `echo bg` / Focus unchecked
- Drag the third row above the second using the grip handle. Verify visual order updates.
- Save.

- [ ] **Step 3: Verify launch behavior**

- Click the lightning-bolt menu on the project row. Confirm the three commands appear in the new order.
- Click "Echo": tab opens, prints, auto-closes.
- Click "Stay": tab opens, prints `stay`, shell remains.
- Click "Background": new tab appears in sidebar but is not focused.
- All tab titles begin with ⚡.

- [ ] **Step 4: Verify persistence**

- Quit the app.
- Run: `cat ~/.config/jfterm/projects.json` (or `$XDG_CONFIG_HOME/jfterm/projects.json`).
- Confirm the `flash_commands` array is present, has the right order, and the boolean fields match what was set.
- Re-launch the app and confirm the flash menu still shows the same commands in the same order.

- [ ] **Step 5: Verify backwards compatibility**

- In a separate scratch directory, save a `projects.json` containing a project with no `flash_commands` field at all (or use an existing pre-feature config).
- Point `XDG_CONFIG_HOME` at that directory and launch.
- Project should load fine; flash menu should be insensitive (greyed out).

- [ ] **Step 6: Verify empty-list disables menu**

- For a project with no flash commands configured, the menu button should be greyed out / non-interactive.

- [ ] **Step 7: Verify failure path (sanity)**

- Add a flash command `Fail` with command `false`.
- Click it. Expect: tab opens, prints `Command failed (exit 1)`, shell prompt remains.
