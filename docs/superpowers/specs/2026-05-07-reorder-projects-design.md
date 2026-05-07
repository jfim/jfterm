# Reorder projects

Tracking: [#16](https://github.com/jfim/jfterm/issues/16)

## Problem

Project order in the sidebar is fixed by creation time. As a workspace grows
the user has no way to put the projects they care about most at the top, or
group related projects next to each other. Tabs already support drag-and-drop
reordering within and between projects; the project list itself does not.

## Solution

Make active project rows in the sidebar draggable. Dropping a project on
another active project row inserts it above that row; dropping it on an
end-of-list sentinel appends it to the active block. Order is persisted
immediately, mirroring the existing tab drag-and-drop behavior.

Archived projects and the Unsorted singleton are not part of the reorder.

## Data model

`src/jfterm/models.py`:

- `Workspace.projects` continues to hold both active and archived projects in
  a single ordered list. Reordering only permutes the active subset; archived
  projects keep their relative order, and the active/archived partition (as
  seen by `active_projects` / `archived_projects`) is unchanged by a move.
- New method `Workspace.move_project(project: Project, position: int)`:
  - `position` is an index into the **active** view (`0..len(active_projects)`).
  - The method computes the absolute index in `self.projects` corresponding
    to that active-view position (taking interleaved archived projects into
    account) and re-inserts `project` there.
  - If `project` is archived, raise `ValueError` — only active projects are
    reorderable.

## Persistence

`save_projects` already serializes `self.projects` in list order, so no
schema change is needed. The window calls `save_projects(self.ws,
default_path())` after each successful drop.

## Sidebar (DnD)

`src/jfterm/sidebar.py`:

- New signal `project-dropped: (project: Project, position: int)`.
  - `position` is the index into `active_projects` where the project should
    end up *before* same-list shift adjustment (the window adjusts for
    "drag down" the same way `_on_tab_dropped` does).
- New helpers, parallel to the existing tab DnD helpers:
  - `_attach_project_drag(row, project)` — installs a `Gtk.DragSource`
    carrying a project payload.
  - `_attach_project_drop(row, position_callable)` — installs a
    `Gtk.DropTarget` that accepts only project payloads and emits
    `project-dropped` with the resolved position.
- The project payload uses a distinct GType from the tab payload so:
  - tab drops do not land on project header rows or the project end-sentinel,
  - project drops do not land on tab rows or per-project tab end-sentinels.
- In `_add_project_row` (active path only): attach drag source on the row,
  attach drop target with `position_callable = lambda i=index_in_active: i`
  ("drop above this project").
- After the last active project row, add a project-level end sentinel
  (analogous to `_add_drop_sentinel` for tabs) with
  `position_callable = lambda: len(ws.active_projects)`.
- `_add_archived_row` does not attach project drag/drop. The Unsorted row
  does not attach project drag/drop.

## Window wiring

`src/jfterm/window.py`:

- Connect `self.sidebar.connect("project-dropped", self._on_project_dropped)`
  alongside the existing `tab-dropped` connection.
- `_on_project_dropped(self, _sb, project, position)`:
  - Adjust for "drag down" the same way `_on_tab_dropped` does:
    `src_idx = ws.active_projects.index(project); if src_idx < position:
    position -= 1`.
  - Call `self.ws.move_project(project, position)`.
  - Call `save_projects(self.ws, default_path())`.
  - Call `self.sidebar.refresh()`.

## Edge cases

- **No-op drop** (project dropped on its own row, or on the sentinel
  immediately after itself): `move_project` runs, the resulting list is
  identical, save and refresh still happen. Cheap and avoids special cases.
- **Project drag onto a tab row**: drop target rejects the payload (different
  GType); nothing happens.
- **Tab drag onto a project header**: rejected likewise; existing tab DnD
  semantics preserved.
- **Archived projects**: not draggable; not drop targets. The Archived
  section's internal order is not user-controlled.
- **Single active project**: drag still works mechanically but every drop is
  a no-op.

## Testing

`tests/`:

- Unit tests for `Workspace.move_project`:
  - Reorder among active projects produces the expected `active_projects`
    sequence.
  - With archived projects interleaved in `self.projects`, moving an active
    project leaves the archived projects' positions and relative order
    untouched.
  - Calling `move_project` on an archived project raises `ValueError`.
  - Edge positions: `position=0` and `position=len(active_projects)`.
- Handler-level test for `_on_project_dropped`:
  - Drag-down adjustment: starting from `[A, B, C]`, dropping `A` at
    `position=2` results in `[B, A, C]` (the same logic the tab handler
    uses).
  - Save is called; sidebar refresh is called.

GTK-level integration testing for the drop target itself follows whatever
pattern the existing tab DnD has (none currently asserted at GDK level, so
this spec does not add one either).

## Out of scope

- Keyboard shortcuts for moving projects (mentioned during brainstorming as
  a possible future addition).
- Reordering archived projects.
- Moving Unsorted.
- Drag-into-archive / drag-out-of-archive gestures.
