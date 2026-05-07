# Command Launcher — Design

GitHub issue: [#19](https://github.com/jfim/jfterm/issues/19)

## Overview

A Quicksilver/Spotlight-style fuzzy launcher invoked by a keyboard
shortcut. Opens a modal popup over the main window with a search field
and a ranked list of actions: flash commands, project-level actions
(new shell tab, run startup commands), and jump-to-tab. Pressing Enter
fires the highlighted action.

Goals:

- One shortcut to do anything that today requires sidebar navigation.
- Keyboard-only — no mouse needed for any action.
- Fast: visible within a frame of the trigger; typing feels instant.

## Trigger

Double-tap **Left Shift** (`Shift_L`) — two press events within 300ms,
with no other key pressed in between.

GTK's `set_accels_for_action()` cannot bind a bare modifier, so the
detector is implemented as a `Gtk.EventControllerKey` attached to the
main window:

- On every key-press: if the keyval is `Shift_L`, compare its event
  timestamp to the previous `Shift_L` press. If within 300ms and no
  intervening non-shift press happened, fire the launcher.
- Any non-`Shift_L` key press resets the timer.
- The detector is its own small helper in `src/jfterm/shortcuts.py`
  (or a new `src/jfterm/double_tap.py` if it grows), parameterized by
  keyval, interval, and callback. Easy to unit-test by feeding
  synthetic `(keyval, timestamp)` events.

Esc closes the launcher. No fallback accelerator in v1; configurability
is deferred to a follow-up.

## UI

A modal `Adw.Window` (transient for and centered over the main window),
~600px wide, hosting:

- Top: a `Gtk.SearchEntry` with focus on open.
- Below: a scrollable `Gtk.ListView` showing up to ~10 visible rows of
  results. The first row is auto-highlighted.

Keyboard:

- Up / Down — move highlight.
- Enter — activate highlighted row.
- Esc — close without acting.
- Typing — updates the search entry, which re-runs ranking.

The launcher is rebuilt fresh each time it opens (item list snapshotted
from the current `Workspace`).

## Items

Every row has the form **`<Project>: <Object>`**. Tabs that live in
the Unsorted bucket use the literal project name `Unsorted`.

| Row format | Action |
|---|---|
| `<Project>: ⚡ <FlashName>` | Run that flash command in its project (same path as the sidebar) |
| `<Project>: ▦ <TabTitle>` | Activate that open tab |
| `<Project>: New Shell Tab` | Spawn a fresh shell tab in that project |
| `<Project>: Run Startup Commands` | Same as the sidebar launch button |

`Unsorted: New Shell Tab` and `Unsorted: Run Startup Commands` are
omitted (Unsorted has no project to act on); only `Unsorted: ▦ <TabTitle>`
rows appear for tabs in the Unsorted bucket.

No "Focus project" verb in v1.

## Empty state

When the launcher opens with an empty query, it shows the last ~8 items
launched via the launcher this session, most-recent first. Recents are
held in RAM on the window object and discarded on app restart.

Items that no longer exist (deleted project, closed tab, removed flash
command) are filtered out at display time, not at launch time.

## Ranking

When the query is non-empty, every item is scored against it and the
results are sorted by score descending. Items that fail to match are
dropped.

The matcher lives in a new module `src/jfterm/fuzzy.py` and exposes:

```python
def score(query: str, candidate: str) -> int | None: ...
def rank(query: str, items: list[T], key: Callable[[T], str]) -> list[T]: ...
```

### Scoring algorithm

Subsequence match with word-boundary and consecutivity bonuses,
case-handling in the IntelliJ style:

1. **Match check.** The query must appear as a case-insensitive
   subsequence of the candidate. If not, return `None`.
2. **Best alignment.** A small DP over `(query_index, candidate_index)`
   finds the alignment that maximizes the score below. Candidate
   strings are short (typically <80 chars), so this is fast.
3. **Per-matched-character bonuses.**
   - **Word-boundary bonus** if the matched candidate char sits at a
     word boundary: first char of the candidate, or immediately after
     one of `space`, `:`, `_`, `-`, `/`, or at a lowercase→uppercase
     transition (`projectA` — `A` is a boundary).
   - **Consecutive bonus** if this match immediately follows the
     previous match (no skipped chars in between).
   - Plus a small baseline per matched char.
4. **Case sensitivity (IntelliJ-style).** If the query has any
   uppercase letters, each uppercase query char must match an
   uppercase or word-boundary char in the candidate. Lowercase query
   chars match anywhere case-insensitively.
5. **Tiebreakers.** Shorter candidates win; remaining ties broken
   alphabetically.

The exact bonus constants are not pinned in this spec; they will be
tuned with unit tests during implementation. The fixtures will include:

- `panst` matching `Project A: New Shell Tab` (all-boundary acronym
  match) ranks above other candidates.
- `PANST` matches the same string (uppercase query against word
  boundaries).
- A consecutive-run query (`proj`) outranks a scattered subsequence
  (`pjt`) on the same candidate.

## Architecture

New modules:

- `src/jfterm/fuzzy.py` — pure scoring/ranking functions. No GTK
  dependency; fully unit-testable.
- `src/jfterm/launcher.py` — the popup widget. Builds the item list
  from a `Workspace`, owns the GTK widgets, manages recents, emits an
  `item-activated` signal carrying a typed action object.
- Either an addition to `src/jfterm/shortcuts.py` or a new
  `src/jfterm/double_tap.py` for the double-Shift detector.

Wiring:

- [window.py:88-105](src/jfterm/window.py:88) gains a double-tap
  detector that calls `launcher.open(self)`.
- A new handler `JFTermWindow._on_launcher_activated(action)` switches
  on the action type and dispatches:
  - **Flash command** → reuse `_on_flash_command_launched`.
  - **New shell tab in project** → reuse the same code path as the
    `Ctrl+Shift+T` shortcut, with the target project supplied
    explicitly.
  - **Run startup commands** → reuse the code the sidebar launch
    button calls.
  - **Jump to tab** → activate that tab via the existing tab-activation
    path.

Action objects (lightweight dataclasses in `launcher.py`):

```python
@dataclass
class FlashAction:
    project: Project
    flash: FlashCommand

@dataclass
class NewTabAction:
    project: Project

@dataclass
class StartupAction:
    project: Project

@dataclass
class JumpAction:
    tab: Tab
```

Each action carries a `display() -> str` method so the launcher and the
recents list never store raw strings.

## Testing

- **`fuzzy` unit tests** — score behavior on small fixtures, including
  the IntelliJ-style cases above; `rank()` ordering on heterogeneous
  candidate lists.
- **Item-list builder unit tests** — given a constructed `Workspace`,
  the builder returns the expected rows in the expected display form,
  including the Unsorted-tab handling.
- **Double-tap detector unit test** — synthetic `(keyval, timestamp)`
  event sequences exercise within-window, outside-window, and
  intervening-key cases.
- **Launcher widget smoke test** — open / close / activate via a
  scripted query, consistent with existing widget tests in this repo.

## Out of scope (v1)

- Configurable shortcut.
- Persistence of recents across sessions.
- Modifier-key secondary actions on rows.
- A "Focus project" verb.
- Custom user-defined launcher items.
- A subject→verb (two-pane) Quicksilver mode.
