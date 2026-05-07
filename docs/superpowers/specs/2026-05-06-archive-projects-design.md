# Archive projects

Tracking: [#17](https://github.com/jfim/jfterm/issues/17)

## Problem

A long-lived JFTerm workspace accumulates projects that are no longer being
actively worked on but the user does not want to delete. The sidebar grows
cluttered. Users want a way to set a project aside without losing its
configuration (startup commands, flash commands, directory) and pull it back
out later.

## Solution

Add an `archived` flag on `Project`. Render archived projects in a separate
collapsible "Archived" section at the bottom of the sidebar, with a single
unarchive action per row. Archive is triggered from the project settings
dialog. Tabs of an archived project are closed at archive time; restoring
brings the project back configured but with no tabs.

## Data model

`src/jfterm/models.py`:

- `Project` gains `archived: bool = False`.
- `Workspace.projects` remains a single ordered list of all projects (active
  and archived). Two computed views:
  - `Workspace.active_projects` → `[p for p in self.projects if not p.archived]`
  - `Workspace.archived_projects` → `[p for p in self.projects if p.archived]`

Existing call sites that iterate `ws.projects` for sidebar/match purposes
switch to `active_projects`. Persistence and bulk operations continue to use
`projects`.

Order is preserved across archive/unarchive: archiving only flips the flag,
so a project unarchived later reappears between the same neighbors it had
before.

## Persistence

`src/jfterm/persistence.py`:

- Add `"archived"` to `_KNOWN_FIELDS`.
- Write `archived` for each project entry.
- Read with `entry.get("archived", False)` so older `projects.json` files
  load cleanly.

## Sidebar

`src/jfterm/sidebar.py`:

- Iterate `ws.active_projects` for the existing project section.
- After the Unsorted row, if `ws.archived_projects` is non-empty, render an
  "Archived" header row (chevron + label, like Unsorted) followed by one
  archived row per project when expanded.
- Archived row contains only: `[name label] [unarchive icon button]`. No
  play, flash, cog, plus, or expand chevron — archived projects do not show
  tabs (they have none).
- Unarchive icon: `view-restore-symbolic` (or similar; pick a stock icon
  that reads as "bring back").
- Add `archived_expanded: bool = False` to `Workspace` so the archived
  section's collapse state persists. Default collapsed.
- Emit a new `unarchive-project-requested` signal when the row's button is
  clicked. Existing `toggle-expanded-requested` handles the section header,
  taking the workspace-level archived flag as its target (or use a new
  signal — see Window section).

## Settings dialog

`src/jfterm/dialogs.py`:

- Add an "Archive project" button to the project settings dialog. Place it
  near the bottom of the dialog alongside other project-level actions.
- On click:
  1. Count the project's open tabs.
  2. If 0 tabs, emit archive request and close dialog.
  3. If ≥1 tabs, show a confirm dialog: `"Archive {name}? This will close
     N tab(s)."` with Cancel / Archive. On confirm, emit archive request
     and close.

## Window wiring

`src/jfterm/window.py`:

- Handle `archive-project-requested` from the settings dialog: close every
  tab in the project (reusing the existing close-tab code path so child
  processes terminate cleanly), set `project.archived = True`, persist,
  refresh sidebar.
- Handle `unarchive-project-requested` from the sidebar: set
  `project.archived = False`, persist, refresh sidebar.
- Handle the archived-section toggle: flip `ws.archived_expanded`, persist,
  refresh.

## Behaviour summary

| Action | Trigger | Effect |
| --- | --- | --- |
| Archive (no tabs) | Settings → Archive | Flag flipped, persisted, sidebar refreshes silently |
| Archive (with tabs) | Settings → Archive | Confirm dialog → close tabs → flag flipped, persisted, refresh |
| Unarchive | Archived row → unarchive button | Flag flipped, persisted, refresh; project reappears in original slot, no tabs |

## Testing

`tests/`:

- `test_models.py` (or equivalent): archive/unarchive flips flag,
  `active_projects` and `archived_projects` filter correctly, `projects`
  order preserved across archive→unarchive cycle.
- `test_persistence.py`: archive flag round-trips through save/load; old
  `projects.json` without the field loads with `archived=False`;
  `archived_expanded` round-trips.
- Sidebar tests, if any exist: Archived section absent when no archived
  projects; present and collapsed by default once one exists; archived row
  has name + unarchive button only.

The tab-close path on archive reuses existing close-tab handling and does
not need a dedicated test.

## Out of scope

- Reordering within the archived section.
- Bulk archive/unarchive.
- Search/filter over archived projects.
- A separate "Manage archived projects" dialog.
