# Terminal appearance configuration — design

Issue: #15

## Goal

Add global appearance configuration for terminals: font (family + size) and
color scheme. Settings are reached from a hamburger menu in the header bar,
persist to `~/.config/jfterm/settings.json`, and apply live to every open
terminal as well as future ones.

This is the first pass (scope A: global only). Per-project overrides
(scope B) are explicitly deferred but the design leaves room for them.

## User experience

- A hamburger button (`open-menu-symbolic`) appears at the right end of the
  header bar, next to the window controls — the standard GNOME location.
- Its menu contains "Preferences" (with room for future "Keyboard Shortcuts"
  and "About" entries).
- "Preferences" opens an `Adw.PreferencesDialog` with one "Appearance" page
  containing a single group with two rows:
  - **Font** — `Gtk.FontDialogButton` filtered to monospace fonts.
  - **Color scheme** — `Adw.ComboRow` listing built-in palettes.
- Changes apply live to every open terminal. No OK/Cancel; close the dialog
  when done. This matches modern libadwaita preference patterns.

## Architecture

Four new modules and two modified files.

### New: `src/jfterm/settings.py`

```python
@dataclass
class AppSettings:
    font_desc: str = ""        # Pango font string, e.g. "Monospace 11";
                               # empty means "system default"
    palette_id: str = "system"
```

- `default_settings_path() -> Path` returns `~/.config/jfterm/settings.json`
  (XDG-aware, mirroring `persistence.default_projects_path()`).
- `load(path: Path) -> AppSettings` — returns defaults if the file is
  missing or malformed (logs a warning to stderr; never raises).
- `save(settings: AppSettings, path: Path) -> None` — writes JSON,
  creating parent directories as needed.
- Unknown keys in the JSON are ignored (forward compatibility).

### New: `src/jfterm/palettes.py`

```python
@dataclass(frozen=True)
class Palette:
    id: str
    display_name: str
    background: str            # "#rrggbb"
    foreground: str            # "#rrggbb"
    cursor: str | None         # optional
    colors: tuple[str, ...]    # exactly 16 hex strings (ANSI 0..15)
```

- Module-level `PALETTES: tuple[Palette, ...]` with the initial set:
  System, Tango, Solarized Dark, Solarized Light, Gruvbox Dark, Nord,
  Dracula.
- The `"system"` palette has empty `colors=()` and is the sentinel for
  "do not override VTE defaults".
- `get(palette_id: str) -> Palette` returns the matching palette, falling
  back to the system palette for unknown ids (graceful behavior on stale
  config or downgrades).

### New: `src/jfterm/preferences.py`

`AppPreferencesDialog(Adw.PreferencesDialog)`:

- One `Adw.PreferencesPage` titled "Appearance" with one
  `Adw.PreferencesGroup`.
- A "Font" `Adw.ActionRow` with a `Gtk.FontDialogButton` suffix; the inner
  `Gtk.FontDialog` is configured with a monospace filter
  (`Pango.FontFamily.is_monospace` via `Gtk.FontDialog.set_filter`).
- A "Color scheme" `Adw.ComboRow` backed by a `Gtk.StringList` populated
  from `PALETTES`. The selected index maps to the palette id.
- Constructor takes the current `AppSettings`; controls are initialized
  from it.
- Emits a `"changed"` signal carrying a fresh `AppSettings` whenever
  either control changes (live apply).

### Modified: `src/jfterm/terminal.py`

Add `apply_appearance(self, settings: AppSettings) -> None`:

- **Font:** if `settings.font_desc` is empty, call `self.set_font(None)`;
  otherwise `self.set_font(Pango.FontDescription.from_string(settings.font_desc))`.
- **Palette:** `palette = palettes.get(settings.palette_id)`. If
  `palette.id == "system"`, call `self.set_colors(None, None, [])` to
  clear overrides. Otherwise convert `palette.foreground`,
  `palette.background`, and `palette.colors` to `Gdk.RGBA` and call
  `self.set_colors(fg, bg, list_of_16)`.
- **Cursor:** if the palette has `cursor`, call
  `self.set_color_cursor(rgba)`; otherwise `self.set_color_cursor(None)`.
- Idempotent — safe to call repeatedly. Called once during construction
  and again every time settings change.

`JFTermTerminal.__init__` gains an optional `appearance: AppSettings | None`
argument; if supplied, `apply_appearance` is called near the end of
`__init__`.

### Modified: `src/jfterm/window.py`

- Add a `Gtk.MenuButton` to the existing `Adw.HeaderBar`, packed at the
  end (so it sits next to the window controls), with the
  `open-menu-symbolic` icon and a `Gio.Menu` containing one item now
  ("Preferences" → `win.preferences`).
- Register a `Gio.SimpleAction("preferences")` on the window that
  instantiates and presents `AppPreferencesDialog`.
- The window owns the live `AppSettings` instance. It is loaded from
  disk at startup. On the dialog's `"changed"` signal:
  1. Replace the in-memory settings.
  2. `settings.save(...)` to disk.
  3. Iterate every live `JFTermTerminal` and call `apply_appearance`.
- New terminals constructed elsewhere in the window receive the current
  `AppSettings` so they match existing tabs.

## Data flow

```
settings.json ──load──▶ AppSettings ──┬──▶ JFTermTerminal.apply_appearance
                            │         │       (called per terminal)
                            ▼         │
              AppPreferencesDialog ───┘
                  (changed signal)
                            │
                            ▼
                       save() + re-apply to all terminals
```

## File format

`~/.config/jfterm/settings.json`:

```json
{
  "font_desc": "Monospace 12",
  "palette_id": "solarized-dark"
}
```

Empty `font_desc` (or missing key) means system default. Unknown
`palette_id` is treated as `"system"` at load time but the file is left
unmodified (so the user gets their palette back if they re-install a
plugin or upgrade).

## Error handling

- Malformed `settings.json` → log a warning to stderr, return defaults,
  do not crash. Same posture as `persistence.py`.
- Unknown palette id → `palettes.get` returns the system palette; settings
  file is not rewritten.
- Invalid font string → `Pango.FontDescription.from_string` is
  permissive; if the family is missing the system fallback kicks in.
  No special handling needed.
- Missing `~/.config/jfterm/` directory → `save` creates it.

## Testing

- `tests/test_settings.py`
  - Round-trip: `save` then `load` returns identical settings.
  - Missing file returns `AppSettings()` defaults.
  - Malformed JSON returns defaults (logs warning, no exception).
  - Unknown keys in JSON are ignored.
- `tests/test_palettes.py`
  - `get("system")` returns the system palette.
  - `get("does-not-exist")` returns the system palette.
  - Every non-system palette has exactly 16 entries in `colors`.
  - Every hex string in every palette parses as a valid `Gdk.RGBA`.

GTK widget tests (the dialog, the menu button) are not added — the
project does not currently have a display-bound test harness, and the
existing convention is to manually verify UI changes.

## Out of scope

Deferred for follow-up work:

- **Per-project overrides** (scope B). The settings/palette modules are
  designed so a `ProjectAppearance` layer can sit on top later: take the
  global `AppSettings`, overlay any project-specific fields, hand the
  result to the terminal.
- Custom palette editing / individual color pickers.
- Cursor shape, transparency, scrollback length.
- Font ligatures, line spacing, bold-as-bright toggle.
- Light/dark palette auto-switching tied to system theme.
- "About" and "Keyboard Shortcuts" entries in the hamburger menu —
  reserved space, not implemented.
