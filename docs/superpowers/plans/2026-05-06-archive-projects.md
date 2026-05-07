# Archive Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-project "archived" flag with a collapsible "Archived" section in the sidebar so users can set projects aside and pull them back later without losing their configuration.

**Architecture:** A single boolean field `archived` on `Project`, with `Workspace.active_projects` / `Workspace.archived_projects` filtered views over the existing `projects` list (preserves order across archive/unarchive). The sidebar renders an "Archived" collapsible section below Unsorted, with each row showing only `[name] [unarchive button]`. Archive is triggered from the project settings dialog and closes the project's tabs through the existing close-tab path.

**Tech Stack:** Python 3, GTK 4 / libadwaita, pytest. Existing modules: `models.py`, `persistence.py`, `sidebar.py`, `dialogs.py`, `window.py`.

Spec: [docs/superpowers/specs/2026-05-06-archive-projects-design.md](../specs/2026-05-06-archive-projects-design.md)

---

## File touch map

- **Modify** `src/jfterm/models.py`: add `archived: bool = False` to `Project`; add `archived_expanded: bool = False` and `active_projects` / `archived_projects` properties to `Workspace`.
- **Modify** `src/jfterm/persistence.py`: persist `archived` per-project and `archived_expanded` at the top level; add `"archived"` to `_KNOWN_FIELDS`.
- **Modify** `src/jfterm/sidebar.py`: render only `active_projects` in the project section; render an "Archived" section with archived rows after Unsorted; add `unarchive-project-requested` and `toggle-archived-expanded-requested` signals.
- **Modify** `src/jfterm/dialogs.py`: add an "Archive project" button + tab-count confirm dialog; expose via a new `on_archive` callback.
- **Modify** `src/jfterm/window.py`: wire `on_archive` from the settings dialog; handle `unarchive-project-requested` and `toggle-archived-expanded-requested`; switch internal callers from `ws.projects` → `ws.active_projects` where appropriate (matching/dot logic).
- **Modify** `tests/test_models.py`: cover archive flag + filtered views + order preservation.
- **Modify** `tests/test_persistence.py`: cover round-trip of `archived` and `archived_expanded` and old-file backward compat.

---

## Task 1: Data model — add `archived` flag and filtered views

**Files:**
- Modify: `src/jfterm/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing test for archive flag default + flip**

Append to `tests/test_models.py`:

```python
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
    # Underlying order preserved.
    assert ws.projects == [a, b, c]


def test_unarchive_restores_position_in_active_view():
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    b = ws.add_project(name="B", directory="/tmp/b")
    c = ws.add_project(name="C", directory="/tmp/c")

    b.archived = True
    assert ws.active_projects == [a, c]

    b.archived = False
    # B reappears between A and C — original position preserved.
    assert ws.active_projects == [a, b, c]


def test_workspace_archived_expanded_defaults_to_false():
    ws = Workspace()
    assert ws.archived_expanded is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: 4 new tests fail with `AttributeError` about `archived` / `active_projects` / `archived_projects` / `archived_expanded`.

- [ ] **Step 3: Implement on `Project` and `Workspace`**

Edit `src/jfterm/models.py`:

In the `Project.__init__` signature, add `archived: bool = False` after `flash_commands`:

```python
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
        archived: bool = False,
    ) -> None:
        super().__init__()
        self.name = name
        self.directory = directory
        self.expanded = expanded
        self.id = id if id is not None else uuid.uuid4().hex
        self.startup_commands: list[StartupCommand] = list(startup_commands or [])
        self.spawn_blank_after_startup = spawn_blank_after_startup
        self.flash_commands: list[FlashCommand] = list(flash_commands or [])
        self.archived = archived
        self._extra: dict[str, Any] = {}
```

In `Workspace`, add `archived_expanded` to `__init__` and add the two filtered properties:

```python
class Workspace:
    """Top-level container: ordered project list + Unsorted singleton."""

    def __init__(self) -> None:
        self.projects: list[Project] = []
        self.unsorted = Unsorted()
        self.sidebar_width: int = 220
        self.archived_expanded: bool = False

    @property
    def active_projects(self) -> list[Project]:
        return [p for p in self.projects if not p.archived]

    @property
    def archived_projects(self) -> list[Project]:
        return [p for p in self.projects if p.archived]

    def add_project(self, name: str, directory: str) -> Project:
        p = Project(name=name, directory=directory)
        self.projects.append(p)
        return p
    # ... rest unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/models.py tests/test_models.py
git commit -m "feat(models): add archived flag and active/archived project views"
```

---

## Task 2: Persistence — round-trip `archived` and `archived_expanded`

**Files:**
- Modify: `src/jfterm/persistence.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Write failing tests for round-trip and backward compat**

Append to `tests/test_persistence.py`:

```python
def test_archived_flag_roundtrips(tmp_path: Path):
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    b = ws.add_project(name="B", directory="/tmp/b")
    b.archived = True

    path = tmp_path / "projects.json"
    save_projects(ws, path)
    ws2 = Workspace()
    load_projects(ws2, path)

    assert [(p.name, p.archived) for p in ws2.projects] == [
        ("A", False),
        ("B", True),
    ]
    # Order preserved exactly so unarchive lands in the right slot.
    assert [p.id for p in ws2.projects] == [a.id, b.id]


def test_archived_expanded_roundtrips(tmp_path: Path):
    ws = Workspace()
    ws.archived_expanded = True
    path = tmp_path / "projects.json"
    save_projects(ws, path)
    ws2 = Workspace()
    load_projects(ws2, path)
    assert ws2.archived_expanded is True


def test_load_missing_archived_field_defaults_to_false(tmp_path: Path):
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
    assert ws.projects[0].archived is False
    assert ws.archived_expanded is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_persistence.py -v`
Expected: round-trip tests fail (archived flag not persisted; archived_expanded missing from save payload).

- [ ] **Step 3: Update persistence**

Edit `src/jfterm/persistence.py`:

Add `"archived"` to the `_KNOWN_FIELDS` set:

```python
_KNOWN_FIELDS = {
    "id",
    "name",
    "directory",
    "expanded",
    "startup_commands",
    "spawn_blank_after_startup",
    "flash_commands",
    "archived",
}
```

In `load_projects`, pass `archived` into the `Project` constructor and read `archived_expanded`:

```python
def load_projects(ws: Workspace, path: Path) -> None:
    if not path.exists():
        return
    data = json.loads(path.read_text())
    for entry in data.get("projects", []):
        p = Project(
            id=entry["id"],
            name=entry["name"],
            directory=entry["directory"],
            expanded=entry.get("expanded", True),
            startup_commands=_load_commands(entry.get("startup_commands", [])),
            spawn_blank_after_startup=bool(entry.get("spawn_blank_after_startup", False)),
            flash_commands=_load_flash_commands(entry.get("flash_commands", [])),
            archived=bool(entry.get("archived", False)),
        )
        p._extra = {k: v for k, v in entry.items() if k not in _KNOWN_FIELDS}
        ws.projects.append(p)
    ws.unsorted.expanded = data.get("unsorted_expanded", True)
    ws.sidebar_width = int(data.get("sidebar_width", ws.sidebar_width))
    ws.archived_expanded = bool(data.get("archived_expanded", False))
```

In `save_projects`, write `archived` per-project and `archived_expanded` at top level:

```python
def save_projects(ws: Workspace, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "directory": p.directory,
                "expanded": p.expanded,
                "startup_commands": [
                    {"command": c.command, "delay": c.delay} for c in p.startup_commands
                ],
                "spawn_blank_after_startup": p.spawn_blank_after_startup,
                "flash_commands": [
                    {
                        "name": fc.name,
                        "command": fc.command,
                        "keep_open_on_success": fc.keep_open_on_success,
                        "focus_on_launch": fc.focus_on_launch,
                    }
                    for fc in p.flash_commands
                ],
                "archived": p.archived,
                **getattr(p, "_extra", {}),
            }
            for p in ws.projects
        ],
        "unsorted_expanded": ws.unsorted.expanded,
        "sidebar_width": ws.sidebar_width,
        "archived_expanded": ws.archived_expanded,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)
```

- [ ] **Step 4: Run all tests to verify**

Run: `uv run pytest tests/test_persistence.py tests/test_models.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/persistence.py tests/test_persistence.py
git commit -m "feat(persistence): persist archived flag and archived_expanded"
```

---

## Task 3: Sidebar — render Archived section with unarchive button

**Files:**
- Modify: `src/jfterm/sidebar.py`

There are no existing unit tests for the sidebar (it's GTK-bound). Behaviour is verified by running the app in Task 6.

- [ ] **Step 1: Add new signals and switch project iteration to `active_projects`**

Edit `src/jfterm/sidebar.py`. In the `__gsignals__` dict on `Sidebar`, add two signals:

```python
__gsignals__ = {
    "tab-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "new-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "close-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "restart-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "configure-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "launch-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "flash-command-launched": (GObject.SignalFlags.RUN_FIRST, None, (object, object)),
    "new-project-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    "toggle-expanded-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "dot-clicked": (GObject.SignalFlags.RUN_FIRST, None, (object, object, object)),
    "tab-dropped": (GObject.SignalFlags.RUN_FIRST, None, (object, object, int)),
    "unarchive-project-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    "toggle-archived-expanded-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
}
```

In `Sidebar.refresh`, change the project loop to use `active_projects` and append the archived section after the Unsorted block. Replace the body of `refresh` with:

```python
def refresh(self) -> None:
    child = self._box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        self._box.remove(child)
        child = nxt

    new_proj_btn = Gtk.Button(label="+ New project")
    new_proj_btn.add_css_class("flat")
    new_proj_btn.connect("clicked", lambda _b: self.emit("new-project-requested"))
    self._box.append(new_proj_btn)

    active = self._ws.active_projects
    for idx, project in enumerate(active):
        if idx > 0:
            self._add_separator()
        self._add_project_row(project)
        if project.expanded:
            for tab in project.tabs:
                self._add_tab_row(project, tab)
            self._add_drop_sentinel(project)

    if active:
        self._add_separator()
    self._add_unsorted_row(self._ws.unsorted)
    if self._ws.unsorted.expanded:
        for tab in self._ws.unsorted.tabs:
            self._add_tab_row(self._ws.unsorted, tab)
        self._add_drop_sentinel(self._ws.unsorted)

    archived = self._ws.archived_projects
    if archived:
        self._add_separator()
        self._add_archived_header()
        if self._ws.archived_expanded:
            for project in archived:
                self._add_archived_row(project)
```

- [ ] **Step 2: Add archived header and row builders**

Append two new methods to `Sidebar` (next to `_add_unsorted_row`):

```python
def _add_archived_header(self) -> None:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    row.set_margin_start(4)
    row.set_margin_end(4)

    chevron = Gtk.Button.new_from_icon_name(
        "pan-down-symbolic" if self._ws.archived_expanded else "pan-end-symbolic"
    )
    chevron.add_css_class("flat")
    chevron.connect(
        "clicked",
        lambda _b: self.emit("toggle-archived-expanded-requested"),
    )

    label_btn = Gtk.Button(label="Archived")
    label_btn.add_css_class("flat")
    label_btn.set_hexpand(True)
    label_btn.set_halign(Gtk.Align.START)
    label_btn.connect(
        "clicked",
        lambda _b: self.emit("toggle-archived-expanded-requested"),
    )

    for w in (chevron, label_btn):
        row.append(w)
    self._box.append(row)

def _add_archived_row(self, project: Project) -> None:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    row.set_margin_start(20)
    row.set_margin_end(4)

    from gi.repository import Pango

    name_label = Gtk.Label(label=project.name, xalign=0)
    name_label.set_ellipsize(Pango.EllipsizeMode.END)
    name_label.set_max_width_chars(24)
    name_label.set_hexpand(True)

    unarchive = Gtk.Button.new_from_icon_name("view-restore-symbolic")
    unarchive.add_css_class("flat")
    unarchive.set_tooltip_text("Unarchive project")
    unarchive.connect(
        "clicked",
        lambda _b, p=project: self.emit("unarchive-project-requested", p),
    )

    row.append(name_label)
    row.append(unarchive)
    self._box.append(row)
```

- [ ] **Step 3: Run lint/typecheck to verify nothing's broken syntactically**

Run: `uv run ruff check src/jfterm/sidebar.py && uv run pyright src/jfterm/sidebar.py`
Expected: no errors.

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: all pass (no test changes here, but make sure we didn't break models/persistence tests).

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/sidebar.py
git commit -m "feat(sidebar): render Archived section below Unsorted"
```

---

## Task 4: Settings dialog — add "Archive project" button with confirm

**Files:**
- Modify: `src/jfterm/dialogs.py`

- [ ] **Step 1: Add `on_archive` parameter and `n_open_tabs` to `show_project_dialog`**

Edit `src/jfterm/dialogs.py`. Update the function signature:

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
    on_save: Callable[[str, str, list[StartupCommand], bool, list[FlashCommand]], None],
    on_disband: Callable[[], None] | None = None,
    on_archive: Callable[[], None] | None = None,
    n_open_tabs: int = 0,
) -> None:
```

- [ ] **Step 2: Add the Archive button + confirm dialog**

In `show_project_dialog`, locate the `if on_disband is not None:` block (currently around line 369) and add an analogous block for archive immediately after it (so visual order in the action bar is `[Delete] [Archive] [Cancel] [Save]`):

```python
    if on_disband is not None:
        disband_btn = Gtk.Button(label="Delete project")
        disband_btn.add_css_class("destructive-action")

        def _on_disband_clicked(_b):
            on_disband()
            dlg.close()

        disband_btn.connect("clicked", _on_disband_clicked)
        actions.append(disband_btn)

    if on_archive is not None:
        archive_btn = Gtk.Button(label="Archive project")

        def _do_archive():
            on_archive()
            dlg.close()

        def _on_archive_clicked(_b):
            if n_open_tabs <= 0:
                _do_archive()
                return
            confirm = Adw.MessageDialog(
                transient_for=dlg,
                modal=True,
                heading=f"Archive {initial_name or 'project'}?",
                body=(
                    f"This will close {n_open_tabs} tab"
                    f"{'s' if n_open_tabs != 1 else ''}."
                ),
            )
            confirm.add_response("cancel", "Cancel")
            confirm.add_response("archive", "Archive")
            confirm.set_response_appearance(
                "archive", Adw.ResponseAppearance.DESTRUCTIVE
            )
            confirm.set_default_response("cancel")
            confirm.set_close_response("cancel")

            def _on_response(_d, response):
                if response == "archive":
                    _do_archive()

            confirm.connect("response", _on_response)
            confirm.present()

        archive_btn.connect("clicked", _on_archive_clicked)
        actions.append(archive_btn)

    actions.append(cancel_btn)
    actions.append(save_btn)
```

(The last two lines — `actions.append(cancel_btn)` / `actions.append(save_btn)` — already exist; ensure the new block is inserted *before* them, replacing nothing else.)

- [ ] **Step 3: Lint check**

Run: `uv run ruff check src/jfterm/dialogs.py && uv run pyright src/jfterm/dialogs.py`
Expected: no errors.

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/dialogs.py
git commit -m "feat(dialogs): add Archive project button with tab-count confirm"
```

---

## Task 5: Window — wire archive/unarchive/toggle handlers

**Files:**
- Modify: `src/jfterm/window.py`

- [ ] **Step 1: Connect the two new sidebar signals**

Edit `src/jfterm/window.py`. In `JFTermWindow.__init__`, after the existing `self.sidebar.connect(...)` lines (around line 84), add:

```python
        self.sidebar.connect("unarchive-project-requested", self._on_unarchive_project)
        self.sidebar.connect("toggle-archived-expanded-requested", self._on_toggle_archived_expanded)
```

- [ ] **Step 2: Pass `on_archive` and `n_open_tabs` from `_on_configure_project`**

In `_on_configure_project` (around line 286), add an `_archive` closure and pass it into `show_project_dialog` along with the tab count. Replace the existing function body with:

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

        def _archive() -> None:
            self._archive_project(project)

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
            on_archive=_archive,
            n_open_tabs=len(project.tabs),
        )
```

- [ ] **Step 3: Implement `_archive_project` and the new sidebar handlers**

Add three new methods to `JFTermWindow`. Place them next to `_on_configure_project`:

```python
    def _archive_project(self, project: Project) -> None:
        # Close every tab via the standard close path so child processes
        # terminate cleanly. Iterate over a copy because _on_close_tab
        # mutates project.tabs.
        for tab in list(project.tabs):
            self._on_close_tab(self.sidebar, tab)
        project.archived = True
        if self._current_group is project:
            self._current_group = self.ws.unsorted
            self.terminal_stack.set_visible_child_name("__empty_global__")
            self.sidebar.set_active_tab(None)
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    def _on_unarchive_project(self, _sb, project: Project) -> None:
        project.archived = False
        save_projects(self.ws, default_path())
        self.sidebar.refresh()

    def _on_toggle_archived_expanded(self, _sb) -> None:
        self.ws.archived_expanded = not self.ws.archived_expanded
        save_projects(self.ws, default_path())
        self.sidebar.refresh()
```

- [ ] **Step 4: Lint + typecheck**

Run: `uv run ruff check src/jfterm/window.py && uv run pyright src/jfterm/window.py`
Expected: no errors.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(window): wire archive/unarchive handlers and confirm flow"
```

---

## Task 6: Manual UI verification

**Files:** none — runtime verification only.

- [ ] **Step 1: Run all CI checks**

Run: `just check`
Expected: lint, fmt-check, typecheck, test all pass.

- [ ] **Step 2: Launch the app**

Run: `just run`

Verify the following manually:

1. Create two projects, A and B. Open one tab in A.
2. Click A's settings cog → Archive project. Confirm dialog says "This will close 1 tab." Click Archive.
3. A vanishes from the active project list. An "Archived" header appears below Unsorted, collapsed by default.
4. Click the Archived header. A is shown with an unarchive icon button to its right and no other controls.
5. Quit the app and relaunch (`just run` again). Archived section is still present and still collapsed (or still expanded if you left it that way before quitting).
6. Expand Archived, click the unarchive icon next to A. A reappears in the active project list at its original position (above B). Archived section disappears (no more archived projects).
7. Archive A again with no open tabs — verify there's no confirm dialog, archive happens silently.
8. Inspect `~/.config/jfterm/projects.json`: confirm each project entry has an `"archived"` field and the top level has `"archived_expanded"`.

- [ ] **Step 3: If everything looks right, no further commit**

If you found issues, fix them, re-run `just check`, and commit per fix.

---

## Self-review notes

- **Spec coverage:** Every section of the spec maps to a task. Data model → Task 1. Persistence → Task 2. Sidebar → Task 3. Settings dialog → Task 4. Window wiring → Task 5. Behaviour summary table verified manually → Task 6. Tests live in Tasks 1-2 (the only places with non-GTK logic).
- **Type consistency:** `Project.archived: bool`, `Workspace.archived_expanded: bool`, `Workspace.active_projects` / `Workspace.archived_projects` properties returning `list[Project]`. Signal names: `unarchive-project-requested` (carries `Project`), `toggle-archived-expanded-requested` (no args). Dialog kwargs: `on_archive`, `n_open_tabs`. All consistent across tasks.
- **No placeholders.**
