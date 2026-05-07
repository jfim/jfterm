# Reorder Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add drag-and-drop reordering of active projects in the sidebar, plus tab-drop on a project header (= append tab to that project).

**Architecture:** Mirror the existing tab DnD pattern in `Sidebar`. Project rows become drag sources carrying a distinct `_ProjectRef` GObject payload, and drop targets that emit a new `project-dropped` signal. The same project rows additionally accept the existing `_TabRef` payload to enable moving tabs into a project (especially collapsed ones). The window persists the new order via `save_projects`. A new `Workspace.move_project` method handles the list permutation, leaving archived projects' positions untouched.

**Tech Stack:** Python 3, GTK4 (PyGObject), pytest, ruff, pyright. Run via `uv run`. Test entrypoint: `just test`.

**Spec:** [docs/superpowers/specs/2026-05-07-reorder-projects-design.md](docs/superpowers/specs/2026-05-07-reorder-projects-design.md). Tracks [#16](https://github.com/jfim/jfterm/issues/16).

---

## File map

- **Modify** `src/jfterm/models.py` — add `Workspace.move_project`.
- **Modify** `src/jfterm/sidebar.py` — add `_ProjectRef`, project drag/drop helpers, `project-dropped` signal, project end sentinel, tab-drop on project header.
- **Modify** `src/jfterm/window.py` — connect `project-dropped`, add `_on_project_dropped` handler.
- **Modify** `tests/test_models.py` — unit tests for `move_project`.
- **Modify** `tests/test_window.py` — handler-level test for `_on_project_dropped`.

No new files.

---

## Task 1: `Workspace.move_project`

**Files:**
- Modify: `src/jfterm/models.py` (after `move_tab`, around line 168)
- Test: `tests/test_models.py` (append at end of file)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
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

    # Initial absolute order: [A, Z, B, C] with Z archived between A and B.
    ws.move_project(c, 0)

    assert [p.name for p in ws.active_projects] == ["C", "A", "B"]
    assert [p.name for p in ws.archived_projects] == ["Z"]
    # Z must remain wedged between (the now-second) A and (the third) B in
    # the absolute list so that unarchive logic that relies on absolute
    # neighbors keeps working.
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -k move_project -v`
Expected: All six tests FAIL with `AttributeError: 'Workspace' object has no attribute 'move_project'`.

- [ ] **Step 3: Implement `move_project`**

In `src/jfterm/models.py`, add this method to `Workspace` immediately after `move_tab` (around line 168):

```python
    def move_project(self, project: Project, position: int) -> None:
        """Reorder `project` within the active-projects view to `position`.

        `position` is an index into `self.active_projects` after `project`
        has been removed (range `0..len(active_projects)-1` if `project` is
        already active, equivalently the destination index in the resulting
        active view). Archived projects keep their absolute slots so their
        relative order to the surrounding active neighbors is preserved.

        Raises ValueError if `project` is archived or `position` is out of
        range.
        """
        if project.archived:
            raise ValueError("cannot move an archived project")
        active = self.active_projects
        if project not in active:
            raise ValueError(f"project {project!r} is not in this workspace")
        if position < 0 or position >= len(active):
            raise ValueError(
                f"position {position} out of range 0..{len(active) - 1}"
            )

        self.projects.remove(project)
        # Recompute active list AFTER removal so `position` indexes the
        # post-removal active view.
        active_after = [p for p in self.projects if not p.archived]
        if position == len(active_after):
            self.projects.append(project)
            return
        anchor = active_after[position]
        anchor_idx = self.projects.index(anchor)
        self.projects.insert(anchor_idx, project)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -k move_project -v`
Expected: All six PASS.

- [ ] **Step 5: Run the full model test suite**

Run: `uv run pytest tests/test_models.py -v`
Expected: All previously-passing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add src/jfterm/models.py tests/test_models.py
git commit -m "feat(models): add Workspace.move_project for active-list reorder"
```

---

## Task 2: Sidebar — project drag-and-drop scaffolding

Add the `_ProjectRef` carrier, project drag/drop helpers, the `project-dropped` signal, the project end sentinel, and wire the project drag source + drop target onto each active project header row.

**Files:**
- Modify: `src/jfterm/sidebar.py`

- [ ] **Step 1: Add `_ProjectRef` carrier**

In `src/jfterm/sidebar.py`, add immediately after the existing `_TabRef` class (around line 23):

```python
class _ProjectRef(GObject.Object):
    """GObject wrapper around a Project so it can travel through GValue/Gdk DnD.

    Distinct from `_TabRef` so project drop targets only accept project
    drags and tab drop targets only accept tab drags.
    """

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
```

- [ ] **Step 2: Register the `project-dropped` signal**

In the `__gsignals__` dict on `Sidebar` (around line 34-51), add:

```python
        "project-dropped": (GObject.SignalFlags.RUN_FIRST, None, (object, int)),
```

Place it adjacent to the existing `"tab-dropped"` entry for readability.

- [ ] **Step 3: Add project drag/drop helpers**

In `Sidebar`, immediately after `_attach_drop` (around line 170), add:

```python
    def _attach_project_drag(self, row: Gtk.Widget, project: Project) -> None:
        src = Gtk.DragSource()
        src.set_actions(Gdk.DragAction.MOVE)

        def _prepare(_s, _x, _y):
            v = GObject.Value()
            v.init(_ProjectRef.__gtype__)
            v.set_object(_ProjectRef(project))
            return Gdk.ContentProvider.new_for_value(v)

        src.connect("prepare", _prepare)
        row.add_controller(src)

    def _attach_project_drop(
        self,
        row: Gtk.Widget,
        target_position_callable: Callable[[], int],
    ) -> None:
        target = Gtk.DropTarget.new(_ProjectRef.__gtype__, Gdk.DragAction.MOVE)

        def _on_drop(_t, value, _x, _y):
            project = value.project if isinstance(value, _ProjectRef) else value
            self.emit("project-dropped", project, target_position_callable())
            return True

        target.connect("drop", _on_drop)
        row.add_controller(target)
```

- [ ] **Step 4: Add a project end-sentinel helper**

Add this method right after `_add_drop_sentinel` (around line 235):

```python
    def _add_project_end_sentinel(self) -> None:
        sentinel = Gtk.Box()
        sentinel.set_size_request(-1, 6)
        self._attach_project_drop(sentinel, lambda: len(self._ws.active_projects))
        self._box.append(sentinel)
```

- [ ] **Step 5: Wire drag + drop into `_add_project_row`**

Change the signature of `_add_project_row` to accept the active-view index, and attach the drag source and drop target on the row.

Replace the `def _add_project_row(self, project: Project) -> None:` line (around line 239) with:

```python
    def _add_project_row(self, project: Project, active_index: int) -> None:
```

At the end of `_add_project_row`, immediately before `self._box.append(row)` (around line 303), add:

```python
        self._attach_project_drag(row, project)
        self._attach_project_drop(row, lambda i=active_index: i)
```

- [ ] **Step 6: Update `refresh()` to pass the index and append the end sentinel**

In `refresh()` (around line 113-120), change:

```python
        active = self._ws.active_projects
        for idx, project in enumerate(active):
            if idx > 0:
                self._add_separator()
            self._add_project_row(project)
            if project.expanded:
                for tab in project.tabs:
                    self._add_tab_row(project, tab)
                self._add_drop_sentinel(project)
```

to:

```python
        active = self._ws.active_projects
        for idx, project in enumerate(active):
            if idx > 0:
                self._add_separator()
            self._add_project_row(project, idx)
            if project.expanded:
                for tab in project.tabs:
                    self._add_tab_row(project, tab)
                self._add_drop_sentinel(project)
        if active:
            self._add_project_end_sentinel()
```

- [ ] **Step 7: Run the existing test suite**

Run: `uv run pytest -v`
Expected: All tests PASS (no behavioral change to existing handlers; only new sidebar plumbing).

- [ ] **Step 8: Lint and typecheck**

Run: `uv run ruff check src/jfterm/sidebar.py`
Run: `uv run pyright src/jfterm/sidebar.py`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add src/jfterm/sidebar.py
git commit -m "feat(sidebar): add project drag-and-drop scaffolding"
```

---

## Task 3: Sidebar — tab drop on project header

Allow tabs to be dropped onto a project header row, interpreted as "append to this project". This is the only way to move a tab into a collapsed project.

**Files:**
- Modify: `src/jfterm/sidebar.py`

- [ ] **Step 1: Attach a tab drop target to each project header**

In `_add_project_row`, immediately before the project drag/drop attachment lines added in Task 2 (so right before `self._attach_project_drag(...)`), add:

```python
        self._attach_drop(row, project, lambda p=project: len(p.tabs))
```

Final tail of `_add_project_row` should now read:

```python
        gesture.connect(
            "pressed",
            lambda g, _n, x, y, p=project, r=row: self._show_project_context_menu(r, p, x, y),
        )
        row.add_controller(gesture)

        self._attach_drop(row, project, lambda p=project: len(p.tabs))
        self._attach_project_drag(row, project)
        self._attach_project_drop(row, lambda i=active_index: i)

        self._box.append(row)
```

- [ ] **Step 2: Run the existing test suite**

Run: `uv run pytest -v`
Expected: All tests PASS.

- [ ] **Step 3: Lint**

Run: `uv run ruff check src/jfterm/sidebar.py`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/jfterm/sidebar.py
git commit -m "feat(sidebar): accept tab drop on project header (append to project)"
```

---

## Task 4: Window — `_on_project_dropped` handler

Connect the new signal, implement the handler with drag-down adjustment, persistence, and refresh. Add a handler-level test.

**Files:**
- Modify: `src/jfterm/window.py`
- Test: `tests/test_window.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_window.py`:

```python
def test_on_project_dropped_reorders_and_persists(tmp_path, monkeypatch):
    from jfterm import persistence
    from jfterm.window import JFTermWindow

    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    b = ws.add_project(name="B", directory="/tmp/b")
    c = ws.add_project(name="C", directory="/tmp/c")

    saves: list[Workspace] = []
    monkeypatch.setattr(persistence, "default_path", lambda: tmp_path / "p.json")
    monkeypatch.setattr(
        "jfterm.window.save_projects",
        lambda workspace, path: saves.append(workspace),
    )

    refreshes: list[int] = []
    fake_self = SimpleNamespace(
        ws=ws,
        sidebar=SimpleNamespace(refresh=lambda: refreshes.append(1)),
    )

    # Move C to the front: position=0, no drag-down adjustment needed.
    JFTermWindow._on_project_dropped(fake_self, None, c, 0)  # pyright: ignore[reportArgumentType]
    assert [p.name for p in ws.active_projects] == ["C", "A", "B"]

    # Drag-down case: A is now at active index 1; dropping it at position 3
    # (end sentinel) must adjust to 2 because removing A first shifts the
    # tail left. Result: [C, B, A].
    JFTermWindow._on_project_dropped(fake_self, None, a, 3)  # pyright: ignore[reportArgumentType]
    assert [p.name for p in ws.active_projects] == ["C", "B", "A"]

    assert len(saves) == 2
    assert len(refreshes) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_window.py::test_on_project_dropped_reorders_and_persists -v`
Expected: FAIL with `AttributeError: type object 'JFTermWindow' has no attribute '_on_project_dropped'`.

- [ ] **Step 3: Implement the handler and connect the signal**

In `src/jfterm/window.py`, find the existing connection block where `tab-dropped` is wired (around line 97):

```python
        self.sidebar.connect("tab-dropped", self._on_tab_dropped)
```

Add immediately after it:

```python
        self.sidebar.connect("project-dropped", self._on_project_dropped)
```

Then, immediately after the existing `_on_tab_dropped` method (around line 616), add:

```python
    def _on_project_dropped(self, _sb, project, position: int) -> None:
        # Drag-down adjustment: if the source index is before the requested
        # destination, removing the source first shifts later positions left
        # by one — same logic as `_on_tab_dropped`.
        active = self.ws.active_projects
        src_idx = active.index(project)
        adjusted = position
        if src_idx < position:
            adjusted -= 1
        self.ws.move_project(project, adjusted)
        save_projects(self.ws, default_path())
        self.sidebar.refresh()
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `uv run pytest tests/test_window.py::test_on_project_dropped_reorders_and_persists -v`
Expected: PASS.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS.

- [ ] **Step 6: Lint, format-check, typecheck**

Run: `just check`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/jfterm/window.py tests/test_window.py
git commit -m "feat(window): handle project-dropped to persist new project order

Closes #16."
```

---

## Task 5: Manual smoke test

GTK-level DnD behavior is not unit-tested. Verify by hand before declaring done.

- [ ] **Step 1: Launch the app**

Run: `uv run jfterm` (or `just run` if defined).

- [ ] **Step 2: Verify project reorder via drag-and-drop**

With at least three active projects (create them if needed via "+ New project"):

1. Drag the third project upward and drop it onto the first project's header row → it should land above the first.
2. Drag the (now) first project downward past the others and drop onto the bottom end-sentinel area → it should land at the bottom.
3. Quit and relaunch → the new order persists.

- [ ] **Step 3: Verify tab drop on a collapsed project header**

1. Collapse a project by clicking its chevron. Confirm no tab rows are visible for it.
2. Drag a tab from another project onto the collapsed project's header.
3. Expand the collapsed project → the dragged tab is at the end of its tab list.

- [ ] **Step 4: Verify tab drop on an expanded project header still works**

Drag a tab from project A onto project B's header (B expanded, with existing tabs) → the tab should append to B's tab list.

- [ ] **Step 5: Verify archived projects are not draggable**

Archive a project. Try to drag it from the Archived section → nothing should happen (no drag source). Try to drop another active project onto an archived row → nothing should happen.

- [ ] **Step 6: Verify Unsorted is not draggable**

Try to drag the Unsorted row → nothing should happen.

If all of the above pass, the feature is complete. If anything misbehaves, file the issue (or fix in-place) before marking the task done.
