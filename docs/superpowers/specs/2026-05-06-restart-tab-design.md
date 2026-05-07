# Restart-tab button for startup-command tabs

## Goal

When a tab was launched via a project's startup command (e.g. `mix phx.server`),
let the user restart it in place with one click — kill the existing shell and
spawn a fresh one with the same command, keeping the tab's slot in the sidebar.

## Scope

In:
- Track per-tab whether the tab was launched with a startup command and what
  the command was.
- Show a refresh button on those tabs only, between the title and the close
  button.
- On click: send SIGTERM to the shell, escalate to SIGKILL after 1.5s if it's
  still alive, swap a fresh `JFTermTerminal` into the same tab.

Out:
- Persistence of tabs across app restarts (tabs aren't persisted today).
- Restart confirmation dialog.
- Auto-restart on unexpected child exit.
- Editing the command from the tab UI.
- Restart button on plain shell tabs.

## Data model

`Tab` (in `src/jfterm/models.py`) gains two runtime-only fields:

- `launched_command: str | None = None` — set when a tab is spawned with a
  non-None `command`. Persists for the tab's lifetime so subsequent restarts
  reuse it.
- `is_restarting: bool = False` — true while a restart is in flight. Used to
  suppress the old terminal's `child-exited` handler from closing the tab.
  Kept as a general flag so future features (e.g. "is this tab busy") can
  reuse the pattern.

No persistence changes; tabs live only in memory today.

## Sidebar UI

In `sidebar._add_tab_row`, when `tab.launched_command` is truthy, insert a
`view-refresh-symbolic` flat icon button between the title label and the
close button. Tooltip: "Restart command".

Add a new signal on the sidebar:

```
"restart-tab-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,))
```

The button's `clicked` handler emits it with the `Tab`.

## Restart flow (`window._on_restart_tab`)

The window connects to `restart-tab-requested` and runs:

1. Resolve the tab's group via `self.ws._find_group(tab)`. Capture
   `was_visible = self.terminal_stack.get_visible_child() is tab.terminal`
   and the command (`tab.launched_command`).
2. Set `tab.is_restarting = True`.
3. Disconnect the old terminal's signal handlers, or more simply, leave them
   connected but rely on the flag — `_on_close_tab` early-returns when
   `tab.is_restarting` is set.
4. Send SIGTERM to `tab.shell_pid` if not None. Schedule a `GLib.timeout_add`
   for 1500ms that probes the pid with `os.kill(pid, 0)` and sends SIGKILL if
   it's still alive. Wrap both signal sends in try/except for `ProcessLookupError`.
5. Remove the old `JFTermTerminal` from `self.terminal_stack`.
6. Build a new `JFTermTerminal(cwd=group.directory if Project else None,
   send_after_spawn=tab.launched_command)`, set h/vexpand, add to the stack.
7. Wire the same four signals (`cwd-changed`, `running-changed`,
   `title-changed`, `child-exited`) onto the new terminal — extract the
   wiring out of `_spawn_tab` into a helper `_wire_terminal(tab, terminal)`
   so both call sites share it.
8. Reset `tab.terminal = new_terminal`, `tab.shell_pid = None`,
   `tab.pty_fd = None`, `tab.is_running = False`, `tab.osc133_seen = False`,
   `tab.title = command`.
9. Clear `tab.is_restarting = False` (the flag has done its job — the new
   terminal's `child-exited` should close the tab normally).
10. If `was_visible`, `self.terminal_stack.set_visible_child(new_terminal)`
    and `new_terminal.grab_focus()`.
11. `self.sidebar.refresh()` so the title resets to the command string.

## `_on_close_tab` change

At the top of `window._on_close_tab`:

```
if tab.is_restarting:
    return
```

This stops the SIGTERM-induced `child-exited` on the old terminal from
removing the tab.

## Testing

The repo uses pytest. Add unit-level coverage where it's straightforward:

- `Tab` has the new fields with correct defaults.
- `_on_close_tab` is a no-op when `tab.is_restarting` is True.

Full restart flow is GTK/VTE-bound and tested manually:
- Launch a project with a `mix phx.server`-style startup command.
- Click the refresh button while it's running. Confirm the same tab keeps its
  position, a new shell starts, and the command re-runs.
- Click refresh on a tab that already exited. Confirm it still restarts.
- Close (not restart) a startup-command tab. Confirm it closes normally.

## File touch list

- `src/jfterm/models.py` — two new `Tab` fields.
- `src/jfterm/sidebar.py` — new signal, refresh button on relevant rows.
- `src/jfterm/window.py` — `_wire_terminal` helper, `_on_restart_tab`,
  `_on_close_tab` early return, set `launched_command` in `_spawn_tab`,
  connect new sidebar signal.
- `tests/` — small additions for the model defaults and close-tab guard.
