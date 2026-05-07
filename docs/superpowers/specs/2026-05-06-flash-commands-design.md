# Flash Commands — Design

## Overview

Per-project "flash commands": one-shot commands launched from a dropdown
button on each project row in the sidebar. Each command opens a new tab,
runs in the project's directory, and (by default) auto-closes the tab on
exit code 0. On failure, the tab stays open with a shell prompt for
inspection.

## Data model

Add to `src/jfterm/models.py`:

```python
@dataclass
class FlashCommand:
    name: str
    command: str
    keep_open_on_success: bool = False
    focus_on_launch: bool = True
```

Add to `Project.__init__`:

```python
flash_commands: list[FlashCommand] | None = None
# ...
self.flash_commands: list[FlashCommand] = list(flash_commands or [])
```

## Persistence

`src/jfterm/persistence.py` gains a `_load_flash_commands(raw)` parallel to
`_load_commands` and serializes `flash_commands` alongside `startup_commands`
in the project save block. Each entry on disk:

```json
{
  "name": "Git push",
  "command": "git push",
  "keep_open_on_success": false,
  "focus_on_launch": true
}
```

`Project._extra` already preserves unknown keys, so older code reading newer
files won't lose data.

## Command wrapping

When launching a flash command, the string fed into the freshly spawned
shell depends on `keep_open_on_success`:

- **False (default)** — wrap so success exits the shell, failure prints a
  message and drops to the prompt:
  ```sh
  { <user-command>; }; __ec=$?; if [ $__ec -eq 0 ]; then exit; else echo "Command failed (exit $__ec)"; fi
  ```
  Failure message text is hardcoded.
- **True** — feed the raw command unwrapped. Shell stays open after the
  command finishes regardless of exit code.

Success path: shell `exit`s → existing VTE `child-exited` signal →
existing `JFTermWindow._on_close_tab` removes the tab. No new close path.

## UI: sidebar button

In `src/jfterm/sidebar.py` (around line 143, where the play button is built),
add a `Gtk.MenuButton` immediately after the play button on each project row:

- Icon: `weather-storm-symbolic` (final choice can be adjusted during
  implementation if a better symbolic exists).
- Tooltip: "Flash commands".
- `flat` CSS class to match the play/cog/plus buttons.
- `set_sensitive(bool(project.flash_commands))`.
- Popover content: a `Gio.Menu` listing each `FlashCommand` by `name`, in
  order. Activating an entry triggers a new `Gtk.Sidebar` signal:
  ```
  flash-command-launched(project: Project, fc: FlashCommand)
  ```

`JFTermWindow` connects to this signal and calls a new helper that:

1. Builds the wrapped (or raw) command string per the rules above.
2. Calls `self._spawn_tab(project, command=<wrapped>, focus=fc.focus_on_launch)`.
3. Overrides the tab title to `f"⚡ {fc.name}"` (set on `Tab.title` after
   `_spawn_tab` returns; the existing title-changed handler will still
   update it later if VTE reports a title).

## Config UI

In `src/jfterm/dialogs.py`, the project edit dialog gains a "Flash commands"
section directly below the startup commands section. Structure mirrors the
startup commands list, with these per-row controls:

- **Name** entry (text)
- **Command** entry (text)
- **Keep open on exit 0** checkbox
- **Focus tab when launching** checkbox
- Up / Down / Delete buttons (reuse the existing reorder pattern)

An "Add flash command" button appends a new row with defaults
(`keep_open_on_success=False`, `focus_on_launch=True`, empty name/command).

Empty rows (both name and command blank) are dropped on save.

## Testing

- Unit test: persistence round-trip of `flash_commands` including all four
  fields, with at least one entry per checkbox combination.
- Unit test: wrapper string generation — both `keep_open_on_success` modes,
  including a command containing `;` and `&&` to confirm the `{ ...; }`
  grouping is correct.
- Manual UI verification (per `CLAUDE.md` guidance for UI changes):
  - Menu shows commands in configured order; insensitive when empty.
  - Successful command auto-closes tab; failing command leaves shell prompt
    with the failure message above it.
  - `focus_on_launch=False` opens the tab without switching to it.
  - Reorder/delete in the config dialog persists across restart.

## Out of scope

- Global (cross-project) flash commands.
- Keyboard shortcuts for flash commands.
- Capturing/displaying command output anywhere other than the tab itself.
