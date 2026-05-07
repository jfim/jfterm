# Configurable Quick Launcher Shortcut

## Summary

The quick launcher is currently bound to a hard-coded double-tap of left Shift
(JetBrains-style). Make the binding user-selectable from a small set of curated
presets via Preferences, applied live without restart. The default preserves
today's behavior so existing users see no change.

## Motivation

Double-Shift is muscle memory for JetBrains users but unfamiliar to most others.
A few presets covering the common conventions (VS Code, Warp, Kitty) let users
pick the binding that matches their other tools. We deliberately do not offer
free-form key entry — the curated list avoids the rabbit hole of validating
arbitrary accelerators and steers users away from chords that collide with
desktop-environment shortcuts (Super, Ctrl+Space, etc.).

## Presets

Four options, identified by stable string IDs in the settings file:

| ID                 | Label              | Mechanism                  |
|--------------------|--------------------|----------------------------|
| `double_shift`     | Double Shift       | `DoubleTapDetector` (today)|
| `ctrl_shift_p`     | Ctrl+Shift+P       | Gtk accelerator            |
| `ctrl_p`           | Ctrl+P             | Gtk accelerator            |
| `ctrl_shift_f2`    | Ctrl+Shift+F2      | Gtk accelerator            |

`double_shift` is the default. Any unknown value loaded from disk falls back
to the default (matching existing behavior for `palette_id` in
[settings.py](src/jfterm/settings.py)).

## Settings

Add one field to `AppSettings` in [src/jfterm/settings.py](src/jfterm/settings.py):

```python
launcher_shortcut: str = "double_shift"
```

`load()` validates the value against the known preset IDs and falls back to the
default on miss. `save()` writes it via the existing `asdict` path — no other
changes needed.

## Window wiring

Today, [window.py:175-184](src/jfterm/window.py:175) unconditionally constructs
a `DoubleTapDetector` and a capture-phase key controller. Refactor that block
into a small helper pair:

- `_install_launcher_shortcut(preset_id: str)` — installs the binding for the
  given preset and stores enough state to undo it.
- `_uninstall_launcher_shortcut()` — tears down whatever the previous call
  installed (removes the controller / clears the accelerator / drops the
  detector reference).

For `double_shift`, the helper installs the existing `DoubleTapDetector` and
capture-phase key controller exactly as today.

For the chord presets, the helper registers a `Gtk.ShortcutController` with a
single `Gtk.Shortcut` whose action calls `self._open_launcher()`. The chord
strings map to standard Gtk accelerator syntax: `<Control><Shift>p`,
`<Control>p`, `<Control><Shift>F2`. These are window-scoped, not application
actions, so they live on a controller attached to the window — separate from
the application-level accelerators set at [window.py:150](src/jfterm/window.py:150).

Only one mode is active at any time. Switching modes calls uninstall then
install.

## Live application

The Preferences dialog already emits a `changed` signal handled by
`_on_settings_changed` in [window.py:1035](src/jfterm/window.py:1035), which
persists the new `AppSettings` and propagates appearance updates to terminals.
Extend that handler: when `launcher_shortcut` differs from the previous value,
call `_uninstall_launcher_shortcut()` then `_install_launcher_shortcut(new_id)`.
No restart required.

If multiple windows exist, each window's `_on_settings_changed` re-binds its
own controller, matching how appearance updates already propagate per-window.

## Preferences UI

Add one row to [src/jfterm/preferences.py](src/jfterm/preferences.py) labeled
"Quick launcher shortcut", a `Gtk.DropDown` populated with the four preset
labels in the order shown above. Selection writes the corresponding ID to
settings and triggers the live re-bind described above.

Place the row in whatever section currently holds keyboard / launcher related
settings; if none exists, group it with general appearance options at the
bottom of the dialog.

## Testing

- Unit test `settings.load()`: known IDs round-trip; unknown ID falls back to
  `double_shift`; missing field falls back to `double_shift`.
- Unit test for the chord-string lookup table (small, but worth a single test
  to catch typos in accelerator strings).
- No GTK integration test — each install branch is a few lines and the cost
  of headless GTK testing isn't justified here.

## Out of scope

- Free-form accelerator entry.
- Per-window or per-tab overrides.
- Rebinding any other shortcut (new-tab, close-tab, etc.) — those stay
  hard-coded as today.
- Conflict detection with system / DE shortcuts. The preset list is curated
  to avoid the obvious conflicts; users who add to it later own the choice.
