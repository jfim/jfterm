# JFTerm v1 — Design

## Purpose

A GNOME terminal emulator that groups tabs by project. Each project is associated with a directory; tabs within a project visually indicate, via a status dot, whether their current working directory is inside that project's directory and whether a command is currently running.

This document specifies the v1 (proof-of-concept) scope. Several enhancements are explicitly deferred (see "Out of scope").

## Stack

- **Language:** Python 3, project managed with `uv` (`uv init`, `uv add`, `uv run`).
- **GUI:** GTK 4 + libadwaita via PyGObject.
- **Terminal:** VTE 3.91 (GTK 4 branch) via PyGObject.

Rationale: PyGObject gives the fastest iteration loop for a UI prototype; VTE provides a complete, GNOME-native terminal widget; libadwaita supplies modern GNOME widgets (`AdwApplicationWindow`, `AdwExpanderRow`-style patterns). Rust is a viable alternative for a v2 rewrite if longevity becomes a goal.

## Window Layout

`AdwApplicationWindow` containing a horizontal `Gtk.Paned`:

- **Left pane (sidebar):** project list with their tabs, plus an "Unsorted" group and a "+ new project" affordance above it.
- **Right pane:** `Gtk.Stack` of `Vte.Terminal` widgets. Selecting a tab in the sidebar swaps the visible stack child.

The paned divider is user-draggable so the sidebar width can be adjusted.

## Sidebar Structure

From top to bottom:

1. One row per **project** in user-defined order. Each project row contains: expand/collapse chevron, project name, configure (⚙) icon, new-tab (+) icon.
2. When expanded, the project's tab rows render indented beneath it. Each tab row contains: status dot, tab label, close (×) icon.
3. A **"+ new project"** button.
4. The **"Unsorted"** group, which behaves like a project for tab-display purposes but cannot be configured, renamed, or disbanded. It has the same `+` icon for new tabs and is always present.

Clicking a project's name (anywhere on the row outside its icons) toggles expand/collapse.

## Models

In-memory:

- **`Project`** — `id` (UUID), `name` (string), `directory` (absolute path), `expanded` (bool), `tabs` (ordered list of `Tab`).
- **`Tab`** — `vte_terminal` (the `Vte.Terminal` widget), `shell_pid` (PID of the spawned shell), `pty_fd` (the controlling pty file descriptor), `current_cwd` (most recently observed cwd from OSC 7, or `None`), `is_running` (bool — see "Status dot"), `osc133_seen` (bool — see "Status dot fallback").
- **`Unsorted`** is modeled as a singleton group object distinct from `Project` (no directory, no configuration). Its tabs use the same `Tab` type.

## Persistence

- File: `~/.config/jfterm/projects.json` (created on first save; directory created with `mkdir -p`).
- Contents: a JSON object `{"version": 1, "projects": [{"id", "name", "directory", "expanded"}, ...]}` in user-defined order.
- Written on every project mutation: create, rename, change directory, reorder, expand/collapse, disband.
- **Tabs are not persisted.** Tab content, count, order, and project assignment are all session-local.
- Schema is intentionally extensible: new optional fields (e.g., future auto-launch templates) can be added without breaking older files. Unknown fields are preserved on load and re-emitted on save.

## Tab Lifecycle

**New tab in a project:** spawns `$SHELL` (defaulting to `/bin/bash` if unset) with cwd set to the project's directory.

**New tab in Unsorted:** same shell, cwd = `$HOME`.

**Close tab:** terminates the VTE child process, destroys the widget, removes the tab from its group's list. If the closed tab was selected, selection follows this priority within the same group only (it does not jump to other groups):

1. The next tab in the same group (the tab that took the closed tab's slot).
2. If the closed tab was last, the new last tab.
3. If the group is now empty, the right pane shows the per-group empty panel for that group.

**Tab labels:** the VTE widget's window-title property (`Vte.Terminal.get_window_title()`, set by the shell via `OSC 0`/`OSC 2`). The user's existing prompt already emits this. Labels are truncated with ellipsis to fit the sidebar row width.

## Status Dot

A custom `Gtk.DrawingArea` widget on each tab row. Two visual axes:

**Color (running state):**
- **Blue:** a foreground subprocess is running in the tab's shell.
- **Grey:** the shell is at its prompt.

**Fill (in-place state):** the unifying semantic is *filled = the tab is in the right home; outline = the tab could be moved* (and the dot-click menu will offer where).

For tabs in a **project**:
- **Filled:** the tab's current cwd equals or is a descendant of the tab's project's directory.
- **Outline:** the cwd is outside the project's directory (or the cwd is unknown).

For tabs in **Unsorted**:
- **Filled:** the cwd does not match any project's directory (Unsorted is the correct home).
- **Outline:** the cwd is inside some project's directory (the tab could be moved there).

### Cwd tracking

Source: `Vte.Terminal.get_current_directory_uri()`, populated automatically by VTE from OSC 7 sequences emitted by the shell. The user's `~/.bash_profile` is configured to emit OSC 7. Re-evaluated on the VTE `current-directory-uri-changed` signal.

### Running-state tracking (primary: OSC 133)

VTE 0.78+ parses OSC 133 internally and exposes prompt/command boundaries via shell-integration signals or termprop APIs. The widget subscribes to those signals and flips `is_running`:

- `OSC 133;C` (command started) → `is_running = True`
- `OSC 133;D` (command finished) → `is_running = False`
- `OSC 133;A` (prompt start) — also implies `is_running = False` if the `D` was missed

The first time any OSC 133 marker is observed on a tab, `osc133_seen` is set to `True` and the fallback below is disabled for that tab.

The user's `~/.bash_profile` is configured to emit `A`/`B`/`C`/`D` markers, so this is the expected path on the user's primary shell.

### Running-state tracking (fallback: tcgetpgrp)

If no OSC 133 marker is seen within 5 seconds of tab spawn (e.g., user runs `bash --norc`, an SSH session into an uninstrumented host, or a non-bash shell without OSC 133 setup), the tab falls back to polling:

- Every 250ms while the window is focused, compare `os.tcgetpgrp(pty_fd)` to `shell_pid`. Equal → at prompt (`is_running = False`). Different → subprocess running (`is_running = True`).
- Polling pauses when the window loses focus.

If OSC 133 is later observed on a tab that started in the fallback, the tab transitions to OSC-133-primary and stops polling.

### API verification caveat

The exact PyGObject surface for VTE shell-integration signals depends on the installed VTE version. **Milestone 4 begins with a small spike** that confirms the available API on the target VTE version. If the Python bindings do not expose OSC 133 state cleanly, the implementation falls back to:

1. A `Vte.Terminal` subclass that intercepts OSC sequences itself, or
2. `tcgetpgrp`-only running-state tracking.

This is a known unknown; the design accommodates all three outcomes without restructuring.

## Status Dot Click — "Move To" Menu

Clicking a tab's status dot opens a `Gtk.PopoverMenu`. The menu always contains both a project-move row (or rows) and an Unsorted-move row, so the available actions are visible at a glance — entries that don't apply are shown but greyed out.

**Project move entries.** For every project whose directory contains the tab's current cwd, an entry **"Move to project {name}"** is shown. Entries are ordered from deepest match (longest directory path) to shallowest, so the most-specific home appears first. An entry is greyed out if the move would be idempotent (the tab is already in that project); otherwise it is active.

If no project's directory contains the cwd, a single greyed-out placeholder entry **"No matching projects"** is shown in place of the per-project entries.

**Unsorted move entry.** A single entry **"Move to Unsorted"** is always shown. It is greyed out if the tab is already in Unsorted; otherwise active.

**Examples.**
- Tab in Project A, cwd inside A's dir → "Move to project A" (greyed), "Move to Unsorted" (active).
- Tab in Project A, cwd inside Project B's dir → "Move to project B" (active), "Move to Unsorted" (active).
- Tab in Project A, cwd outside all project dirs → "No matching projects" (greyed), "Move to Unsorted" (active).
- Tab in Unsorted, cwd inside Project B's dir → "Move to project B" (active), "Move to Unsorted" (greyed).
- Tab in Unsorted, cwd outside all project dirs → "No matching projects" (greyed), "Move to Unsorted" (greyed).
- Nested case: projects "monorepo" at `/code/monorepo` and "webapp" at `/code/monorepo/webapp`. Tab in "monorepo", cwd at `/code/monorepo/webapp/src` → "Move to project webapp" (active, deepest), "Move to project monorepo" (greyed, already there), "Move to Unsorted" (active).

Selecting an active item moves the tab (re-parents it in the model and re-renders the sidebar). The right-pane stack child does not change; only the tab's group membership.

## Drag-and-Drop

GTK 4 native DnD on tab rows:

- **Drag source:** any tab row.
- **Drop targets:** any position between tab rows in any group (including Unsorted).
- **Effect:** moves the tab to the drop position in the destination group, supporting both within-group reordering and across-group moves.

The status dot of the dragged tab updates after the move (a tab dragged into Project A becomes filled if its cwd matches; outline otherwise).

## Project Lifecycle

**Create** — clicking "+ new project" opens a dialog with two required fields:
- **Name** (text, pre-filled with `basename(directory)` and updated as the user picks a directory; user may override).
- **Directory** (path, with a `Gtk.FileDialog` directory picker).

OK creates the project and appends it to the project list (above Unsorted).

**Configure** — clicking ⚙ on a project row opens the same dialog populated with the project's current values, plus a **Disband** button.

**Disband** — confirmation prompt; on confirm the project is removed from the list. Its tabs move to the end of Unsorted's tab list, preserving relative order.

**Rename / change directory** — done via Configure. Changing a project's directory immediately re-evaluates all of its tabs' status-dot fill states (and the dot-click menu offerings on tabs in other projects).

## Empty States

The right pane has two empty-state variants, both centered placeholder labels with the window staying open:

- **Global empty state** ("No tabs — click + to create one"): shown at startup before the user has interacted with any group, when no current-group context exists. The startup state is **always** this — no tabs are auto-created on launch, regardless of whether saved projects exist.
- **Per-group empty state**: shown when the currently-focused group has no tabs (e.g., the user closed the last tab in Project A). Label is **"Project {name} has no tabs."** for projects and **"Unsorted has no tabs."** for the Unsorted group.

Selecting any tab (clicking it in the sidebar, or creating one via `+`) replaces the empty state with that tab's terminal. Closing the last tab in the current group transitions to that group's per-group empty state — the view does **not** jump to another group's tabs automatically.

## Keyboard Shortcuts (v1)

- `Ctrl+Shift+T` — new tab in the currently-selected tab's project; if no tab is selected, new tab in Unsorted.
- `Ctrl+Shift+W` — close current tab.
- `Ctrl+Shift+C` / `Ctrl+Shift+V` — copy / paste (standard in GNOME terminals; required because `Ctrl+C` sends `SIGINT` in a terminal context).
- `Ctrl+PgUp` / `Ctrl+PgDn` — previous / next tab in sidebar order, wrapping across groups.

## Out of Scope for v1

- Tab/session restore (tabs reopening with last cwd on relaunch).
- Multiple windows.
- Find / search within terminal scrollback.
- Per-project auto-launch tab templates (e.g., spawn `docker postgres` and `mix phx.server` in two locked tabs when the project is opened) — schema reserves room.
- Locked / pinned tabs.
- Theme / color customization.
- Settings UI beyond the per-project configure dialog.
- New-project keyboard shortcut.
- `Ctrl+1..9` jump-to-tab.
- Bypassing OSC 133 entirely in favor of `tcgetpgrp`-only tracking. (Fallback only.)

## Open Questions

- **Exact VTE shell-integration API on the target version.** Resolved by the milestone 4 spike, before committing to the OSC 133 primary path.

## Milestones

Each milestone leaves the app in a runnable state.

1. **Skeleton.** `uv init`, dependencies, `AdwApplicationWindow` with a single `Vte.Terminal` running `$SHELL`.
2. **Layout.** `Gtk.Paned` with hardcoded sidebar (one Unsorted group, one tab) and `Gtk.Stack` for tab switching.
3. **Models + actions.** `Project` / `Tab` / `Unsorted` types; new tab, close tab, new project, configure project (name + dir + disband), persistence to `projects.json`.
4. **Status dot.** Custom widget; OSC 7 cwd tracking; OSC 133 running-state via VTE signals (with the API verification spike at the start); `tcgetpgrp` fallback; fill-state computation against project directory.
5. **Dot-click menu.** "Move to project / Unsorted" popover with greyed-out placeholder when no project matches.
6. **Drag-and-drop.** Within-group reorder and across-group moves.
7. **Polish.** Keyboard shortcuts, empty state, label truncation, copy/paste.
