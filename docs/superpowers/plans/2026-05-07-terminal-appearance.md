# Terminal appearance configuration — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a global appearance configuration (font + color scheme) for terminals, reachable from a hamburger menu in the header bar, persisted to `~/.config/jfterm/settings.json`, and applied live to all open terminals.

**Architecture:** Add three new modules (`settings.py`, `palettes.py`, `preferences.py`); add an `apply_appearance` method to `JFTermTerminal`; add a hamburger menu to the window header bar and wire it to a `Gio.SimpleAction` that opens an `Adw.PreferencesDialog`. The window owns the live `AppSettings` and broadcasts changes to every live terminal.

**Tech Stack:** Python, GTK 4 / libadwaita, VTE 3.91, Pango.

Spec: [docs/superpowers/specs/2026-05-07-terminal-appearance-design.md](../specs/2026-05-07-terminal-appearance-design.md). Issue: #15.

---

## File structure

- **Create** `src/jfterm/settings.py` — `AppSettings` dataclass plus `default_path`, `load`, `save`.
- **Create** `src/jfterm/palettes.py` — `Palette` dataclass, `PALETTES` tuple, `get(palette_id)`.
- **Create** `src/jfterm/preferences.py` — `AppPreferencesDialog`.
- **Create** `tests/test_settings.py`.
- **Create** `tests/test_palettes.py`.
- **Modify** `src/jfterm/terminal.py` — add `apply_appearance(settings)`, accept optional `appearance` in `__init__`.
- **Modify** `src/jfterm/window.py` — load settings on startup, add hamburger menu and `preferences` action, pass settings to new terminals, broadcast changes.

---

## Task 1: AppSettings dataclass and persistence

**Files:**
- Create: `src/jfterm/settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_settings.py
import json
from pathlib import Path

from jfterm.settings import AppSettings, default_path, load, save


def test_load_missing_file_returns_defaults(tmp_path: Path):
    s = load(tmp_path / "does-not-exist.json")
    assert s == AppSettings()


def test_save_then_load_roundtrips(tmp_path: Path):
    path = tmp_path / "settings.json"
    save(AppSettings(font_desc="Monospace 12", palette_id="solarized-dark"), path)
    s = load(path)
    assert s.font_desc == "Monospace 12"
    assert s.palette_id == "solarized-dark"


def test_save_creates_parent_directories(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "settings.json"
    save(AppSettings(), path)
    assert path.exists()


def test_load_malformed_json_returns_defaults(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    s = load(path)
    assert s == AppSettings()


def test_load_unknown_keys_are_ignored(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"font_desc": "Mono 10", "future_key": "x"}))
    s = load(path)
    assert s.font_desc == "Mono 10"
    assert s.palette_id == "system"


def test_default_path_uses_xdg_config_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_path() == tmp_path / "jfterm" / "settings.json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_settings.py -v`
Expected: ImportError / module not found.

- [ ] **Step 3: Implement `settings.py`**

```python
# src/jfterm/settings.py
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppSettings:
    font_desc: str = ""          # Pango font string, e.g. "Monospace 11";
                                 # empty means "system default"
    palette_id: str = "system"


def default_path() -> Path:
    """Path to ~/.config/jfterm/settings.json (XDG_CONFIG_HOME aware)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "jfterm" / "settings.json"


def load(path: Path) -> AppSettings:
    if not path.exists():
        return AppSettings()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"jfterm: ignoring malformed {path}: {e}", file=sys.stderr)
        return AppSettings()
    if not isinstance(data, dict):
        return AppSettings()
    return AppSettings(
        font_desc=str(data.get("font_desc", "")),
        palette_id=str(data.get("palette_id", "system")),
    )


def save(settings: AppSettings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2))
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_settings.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/settings.py tests/test_settings.py
git commit -m "feat(settings): add AppSettings dataclass and JSON persistence"
```

---

## Task 2: Palette catalog

**Files:**
- Create: `src/jfterm/palettes.py`
- Test: `tests/test_palettes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_palettes.py
import re

from jfterm.palettes import PALETTES, Palette, get

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_get_system_returns_system_palette():
    p = get("system")
    assert p.id == "system"
    assert p.colors == ()


def test_get_unknown_id_falls_back_to_system():
    p = get("does-not-exist")
    assert p.id == "system"


def test_palettes_contains_system_first():
    assert PALETTES[0].id == "system"


def test_palettes_have_unique_ids():
    ids = [p.id for p in PALETTES]
    assert len(ids) == len(set(ids))


def test_non_system_palettes_have_16_colors():
    for p in PALETTES:
        if p.id == "system":
            continue
        assert len(p.colors) == 16, f"{p.id} has {len(p.colors)} colors"


def test_all_color_strings_are_valid_hex():
    for p in PALETTES:
        if p.id == "system":
            continue
        assert HEX.match(p.foreground), f"{p.id} foreground: {p.foreground}"
        assert HEX.match(p.background), f"{p.id} background: {p.background}"
        if p.cursor is not None:
            assert HEX.match(p.cursor), f"{p.id} cursor: {p.cursor}"
        for i, c in enumerate(p.colors):
            assert HEX.match(c), f"{p.id} colors[{i}]: {c}"


def test_expected_palettes_are_present():
    ids = {p.id for p in PALETTES}
    assert {
        "system",
        "tango",
        "solarized-dark",
        "solarized-light",
        "gruvbox-dark",
        "nord",
        "dracula",
    } <= ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_palettes.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `palettes.py`**

```python
# src/jfterm/palettes.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    id: str
    display_name: str
    background: str
    foreground: str
    cursor: str | None
    colors: tuple[str, ...]  # exactly 16 hex strings (ANSI 0..15), or empty for "system"


_SYSTEM = Palette(
    id="system",
    display_name="System default",
    background="",
    foreground="",
    cursor=None,
    colors=(),
)

# Tango — GNOME Terminal's classic palette.
_TANGO = Palette(
    id="tango",
    display_name="Tango",
    background="#000000",
    foreground="#ffffff",
    cursor=None,
    colors=(
        "#000000", "#cc0000", "#4e9a06", "#c4a000",
        "#3465a4", "#75507b", "#06989a", "#d3d7cf",
        "#555753", "#ef2929", "#8ae234", "#fce94f",
        "#729fcf", "#ad7fa8", "#34e2e2", "#eeeeec",
    ),
)

# Solarized — Ethan Schoonover's palette.
_SOLARIZED_DARK = Palette(
    id="solarized-dark",
    display_name="Solarized Dark",
    background="#002b36",
    foreground="#839496",
    cursor="#93a1a1",
    colors=(
        "#073642", "#dc322f", "#859900", "#b58900",
        "#268bd2", "#d33682", "#2aa198", "#eee8d5",
        "#002b36", "#cb4b16", "#586e75", "#657b83",
        "#839496", "#6c71c4", "#93a1a1", "#fdf6e3",
    ),
)

_SOLARIZED_LIGHT = Palette(
    id="solarized-light",
    display_name="Solarized Light",
    background="#fdf6e3",
    foreground="#657b83",
    cursor="#586e75",
    colors=(
        "#073642", "#dc322f", "#859900", "#b58900",
        "#268bd2", "#d33682", "#2aa198", "#eee8d5",
        "#002b36", "#cb4b16", "#586e75", "#657b83",
        "#839496", "#6c71c4", "#93a1a1", "#fdf6e3",
    ),
)

# Gruvbox Dark (medium) — Pavel Pertsev's palette.
_GRUVBOX_DARK = Palette(
    id="gruvbox-dark",
    display_name="Gruvbox Dark",
    background="#282828",
    foreground="#ebdbb2",
    cursor="#ebdbb2",
    colors=(
        "#282828", "#cc241d", "#98971a", "#d79921",
        "#458588", "#b16286", "#689d6a", "#a89984",
        "#928374", "#fb4934", "#b8bb26", "#fabd2f",
        "#83a598", "#d3869b", "#8ec07c", "#ebdbb2",
    ),
)

# Nord — Arctic, north-bluish color palette by Sven Greb.
_NORD = Palette(
    id="nord",
    display_name="Nord",
    background="#2e3440",
    foreground="#d8dee9",
    cursor="#d8dee9",
    colors=(
        "#3b4252", "#bf616a", "#a3be8c", "#ebcb8b",
        "#81a1c1", "#b48ead", "#88c0d0", "#e5e9f0",
        "#4c566a", "#bf616a", "#a3be8c", "#ebcb8b",
        "#81a1c1", "#b48ead", "#8fbcbb", "#eceff4",
    ),
)

# Dracula — Zeno Rocha's palette.
_DRACULA = Palette(
    id="dracula",
    display_name="Dracula",
    background="#282a36",
    foreground="#f8f8f2",
    cursor="#f8f8f2",
    colors=(
        "#21222c", "#ff5555", "#50fa7b", "#f1fa8c",
        "#bd93f9", "#ff79c6", "#8be9fd", "#f8f8f2",
        "#6272a4", "#ff6e6e", "#69ff94", "#ffffa5",
        "#d6acff", "#ff92df", "#a4ffff", "#ffffff",
    ),
)

PALETTES: tuple[Palette, ...] = (
    _SYSTEM,
    _TANGO,
    _SOLARIZED_DARK,
    _SOLARIZED_LIGHT,
    _GRUVBOX_DARK,
    _NORD,
    _DRACULA,
)


def get(palette_id: str) -> Palette:
    for p in PALETTES:
        if p.id == palette_id:
            return p
    return _SYSTEM
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_palettes.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/palettes.py tests/test_palettes.py
git commit -m "feat(palettes): add built-in color scheme catalog"
```

---

## Task 3: `JFTermTerminal.apply_appearance`

**Files:**
- Modify: `src/jfterm/terminal.py`

This task has no automated tests — VTE methods need a display. Verify by running the app in Task 6.

- [ ] **Step 1: Add Pango import at the top of terminal.py**

In `src/jfterm/terminal.py`, locate the existing `gi.require_version` block and the `from gi.repository import ...` line. Update them as follows:

```python
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Vte", "3.91")

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango, Vte  # noqa: E402
```

(Pango is added to the import list. No new `gi.require_version` is needed — Pango is pulled in transitively, no version pin required.)

- [ ] **Step 2: Add an import for AppSettings and palettes**

Below the existing imports, add:

```python
from jfterm.palettes import get as get_palette  # noqa: E402
from jfterm.settings import AppSettings  # noqa: E402
```

- [ ] **Step 3: Add `appearance` parameter to `__init__`**

Locate the existing `__init__` signature:

```python
    def __init__(
        self,
        cwd: str | None = None,
        send_after_spawn: str | None = None,
    ) -> None:
```

Replace with:

```python
    def __init__(
        self,
        cwd: str | None = None,
        send_after_spawn: str | None = None,
        appearance: AppSettings | None = None,
    ) -> None:
```

- [ ] **Step 4: Apply appearance at end of `__init__`**

At the very end of `__init__` (after `self._install_context_menu()`), add:

```python
        if appearance is not None:
            self.apply_appearance(appearance)
```

- [ ] **Step 5: Add `apply_appearance` method**

Add this method to `JFTermTerminal` (place it just before `_install_context_menu` or in any logical location — order does not matter):

```python
    def apply_appearance(self, settings: AppSettings) -> None:
        """Apply font + color-scheme settings. Idempotent."""
        # Font
        if settings.font_desc:
            self.set_font(Pango.FontDescription.from_string(settings.font_desc))
        else:
            self.set_font(None)

        # Palette
        palette = get_palette(settings.palette_id)
        if palette.id == "system" or not palette.colors:
            self.set_colors(None, None, [])
            self.set_color_cursor(None)
            return

        fg = Gdk.RGBA()
        fg.parse(palette.foreground)
        bg = Gdk.RGBA()
        bg.parse(palette.background)
        ansi = []
        for hex_str in palette.colors:
            rgba = Gdk.RGBA()
            rgba.parse(hex_str)
            ansi.append(rgba)
        self.set_colors(fg, bg, ansi)

        if palette.cursor is not None:
            cursor = Gdk.RGBA()
            cursor.parse(palette.cursor)
            self.set_color_cursor(cursor)
        else:
            self.set_color_cursor(None)
```

- [ ] **Step 6: Run existing tests to verify no regressions**

Run: `uv run pytest -v`
Expected: all existing tests still pass; new `tests/test_settings.py` and `tests/test_palettes.py` still pass.

- [ ] **Step 7: Commit**

```bash
git add src/jfterm/terminal.py
git commit -m "feat(terminal): add apply_appearance for font and palette"
```

---

## Task 4: AppPreferencesDialog

**Files:**
- Create: `src/jfterm/preferences.py`

This file uses GTK widgets that need a display, so no unit tests. Verify manually in Task 6.

- [ ] **Step 1: Create `preferences.py`**

```python
# src/jfterm/preferences.py
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk, Pango  # noqa: E402

from jfterm.palettes import PALETTES  # noqa: E402
from jfterm.settings import AppSettings  # noqa: E402


class _MonospaceFilter(Gtk.Filter):
    """Gtk.Filter that keeps only monospace Pango font families."""

    def do_match(self, item) -> bool:
        if isinstance(item, Pango.FontFamily):
            return item.is_monospace()
        if isinstance(item, Pango.FontFace):
            family = item.get_family()
            return family is not None and family.is_monospace()
        return False

    def do_get_strictness(self) -> Gtk.FilterMatch:
        return Gtk.FilterMatch.SOME


class AppPreferencesDialog(Adw.PreferencesDialog):
    """Global appearance preferences. Emits `changed` with a fresh AppSettings."""

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.set_title("Preferences")
        self._settings = AppSettings(
            font_desc=settings.font_desc,
            palette_id=settings.palette_id,
        )

        page = Adw.PreferencesPage()
        page.set_title("Appearance")
        page.set_icon_name("applications-graphics-symbolic")

        group = Adw.PreferencesGroup()
        group.set_title("Terminal")

        # --- Font row ---
        font_row = Adw.ActionRow()
        font_row.set_title("Font")
        font_row.set_subtitle("Monospace fonts only")

        font_dialog = Gtk.FontDialog()
        font_dialog.set_title("Pick a terminal font")
        font_dialog.set_filter(_MonospaceFilter())

        self._font_button = Gtk.FontDialogButton(dialog=font_dialog)
        self._font_button.set_use_font(True)
        self._font_button.set_valign(Gtk.Align.CENTER)
        if self._settings.font_desc:
            self._font_button.set_font_desc(
                Pango.FontDescription.from_string(self._settings.font_desc)
            )
        self._font_button.connect("notify::font-desc", self._on_font_changed)
        font_row.add_suffix(self._font_button)
        font_row.set_activatable_widget(self._font_button)
        group.add(font_row)

        # --- Palette row ---
        names = Gtk.StringList()
        for p in PALETTES:
            names.append(p.display_name)
        self._palette_row = Adw.ComboRow()
        self._palette_row.set_title("Color scheme")
        self._palette_row.set_model(names)
        # Select current palette
        current_index = next(
            (i for i, p in enumerate(PALETTES) if p.id == self._settings.palette_id),
            0,
        )
        self._palette_row.set_selected(current_index)
        self._palette_row.connect("notify::selected", self._on_palette_changed)
        group.add(self._palette_row)

        page.add(group)
        self.add(page)

    # --- handlers ---

    def _on_font_changed(self, button: Gtk.FontDialogButton, _pspec) -> None:
        desc = button.get_font_desc()
        self._settings.font_desc = desc.to_string() if desc is not None else ""
        self.emit("changed", self._copy())

    def _on_palette_changed(self, row: Adw.ComboRow, _pspec) -> None:
        idx = row.get_selected()
        if 0 <= idx < len(PALETTES):
            self._settings.palette_id = PALETTES[idx].id
            self.emit("changed", self._copy())

    def _copy(self) -> AppSettings:
        return AppSettings(
            font_desc=self._settings.font_desc,
            palette_id=self._settings.palette_id,
        )
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `uv run python -c "from jfterm.preferences import AppPreferencesDialog"`
Expected: no output, no error.

- [ ] **Step 3: Commit**

```bash
git add src/jfterm/preferences.py
git commit -m "feat(preferences): add AppPreferencesDialog with font + palette rows"
```

---

## Task 5: Wire window header bar, action, and broadcast

**Files:**
- Modify: `src/jfterm/window.py`

- [ ] **Step 1: Add imports**

At the top of `src/jfterm/window.py`, locate the existing imports. Add this line to the existing `from gi.repository import ...` import (after the require_version calls):

```python
from gi.repository import Adw, Gio, Gtk  # noqa: E402
```

(Adds `Gio`. The existing line imports `Adw, Gtk` — replace with the version above.)

Below the existing project imports, add:

```python
from jfterm.preferences import AppPreferencesDialog  # noqa: E402
from jfterm.settings import (  # noqa: E402
    AppSettings,
    default_path as default_settings_path,
    load as load_settings,
    save as save_settings,
)
```

- [ ] **Step 2: Load settings in `__init__`**

After the existing `load_projects(self.ws, default_path())` call, add:

```python
        self._settings_path = default_settings_path()
        self._settings: AppSettings = load_settings(self._settings_path)
```

- [ ] **Step 3: Add hamburger menu and preferences action**

In `__init__`, locate this block:

```python
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self._sidebar_toggle = Gtk.ToggleButton()
        self._sidebar_toggle.set_icon_name("sidebar-show-symbolic")
        self._sidebar_toggle.set_tooltip_text("Hide sidebar")
        self._sidebar_toggle.set_active(True)
        self._sidebar_toggle.connect("toggled", self._on_sidebar_toggled)
        header.pack_start(self._sidebar_toggle)
        toolbar.add_top_bar(header)
```

After `header.pack_start(self._sidebar_toggle)` and before `toolbar.add_top_bar(header)`, insert:

```python
        # Hamburger menu (right end of header bar).
        menu = Gio.Menu()
        menu.append("Preferences", "win.preferences")
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_tooltip_text("Main menu")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)

        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", self._on_preferences)
        self.add_action(prefs_action)
```

- [ ] **Step 4: Add `_on_preferences` handler**

Add this method to `JFTermWindow` (placement: alongside other `_on_*` handlers):

```python
    def _on_preferences(self, _action, _param) -> None:
        dialog = AppPreferencesDialog(self._settings)
        dialog.connect("changed", self._on_settings_changed)
        dialog.present(self)

    def _on_settings_changed(self, _dialog, settings: AppSettings) -> None:
        self._settings = settings
        try:
            save_settings(settings, self._settings_path)
        except OSError as e:
            print(f"jfterm: failed to save settings: {e}", file=__import__("sys").stderr)
        for terminal in self._iter_terminals():
            terminal.apply_appearance(settings)

    def _iter_terminals(self):
        for group in self.ws.all_groups():
            for tab in group.tabs:
                widget = getattr(tab, "widget", None)
                if isinstance(widget, JFTermTerminal):
                    yield widget
```

`Workspace.all_groups()` returns every project plus the unsorted bucket (see `src/jfterm/models.py`). This walks every live `JFTermTerminal` in the workspace.

- [ ] **Step 5: Pass settings to new terminals**

Find every `JFTermTerminal(...)` call in `src/jfterm/window.py`. There are two (per spec exploration: lines 142 and 351 — verify with `grep -n "JFTermTerminal(" src/jfterm/window.py`). For each, add the `appearance` keyword argument:

Before:
```python
terminal = JFTermTerminal(cwd=cwd, send_after_spawn=command)
```

After:
```python
terminal = JFTermTerminal(cwd=cwd, send_after_spawn=command, appearance=self._settings)
```

(Apply the same change to the second `JFTermTerminal(...)` site.)

- [ ] **Step 6: Run tests**

Run: `uv run pytest -v`
Expected: all tests pass (no regressions).

- [ ] **Step 7: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(window): hamburger menu + preferences action wired to terminals"
```

---

## Task 6: Manual verification

This is a UI feature; manual smoke test is required.

- [ ] **Step 1: Launch the app**

Run: `just run` (or `uv run python -m jfterm`).

- [ ] **Step 2: Verify hamburger menu**

- A hamburger icon (`open-menu-symbolic`) appears at the right end of the header bar.
- Clicking it shows a menu with one entry: "Preferences".

- [ ] **Step 3: Verify preferences dialog**

- Click "Preferences". An `Adw.PreferencesDialog` opens with one "Appearance" page.
- The page shows two rows: "Font" (with a font picker button) and "Color scheme" (a dropdown).
- The font picker, when clicked, opens a font chooser that lists only monospace fonts.
- The color-scheme dropdown lists: System default, Tango, Solarized Dark, Solarized Light, Gruvbox Dark, Nord, Dracula.

- [ ] **Step 4: Verify live apply**

- Open a terminal tab, then open Preferences.
- Change the color scheme to Dracula. The open terminal recolors immediately.
- Change the font (e.g. to "Monospace 14"). The open terminal re-fonts immediately.
- Open a second terminal — it inherits the new appearance.

- [ ] **Step 5: Verify persistence**

- Close the app, reopen it.
- Check that `~/.config/jfterm/settings.json` exists and contains the chosen font + palette.
- New tabs use the persisted settings.

- [ ] **Step 6: Verify reset to system**

- In Preferences, switch back to "System default" palette. Terminals revert to VTE defaults.

- [ ] **Step 7: Verify graceful degradation**

- Close the app.
- Edit `~/.config/jfterm/settings.json` and set `"palette_id": "no-such-palette"`.
- Relaunch. The app should start fine and use the system palette.
- Restore a valid palette via the Preferences dialog.

- [ ] **Step 8: Verify no regressions in existing flows**

- Create a project, launch its startup commands, drag a tab between groups, run a flash command. Everything should behave as before.

If any check fails, file the failure as a follow-up task and fix before declaring done.

---

## Task 7: Final verification + integration commit

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: all pass.

- [ ] **Step 2: Run the linter / formatter the project uses (if any)**

Check `pyproject.toml` and `justfile` for `ruff`, `black`, `mypy`, etc. Run whatever is configured. If unclear, skip.

- [ ] **Step 3: Confirm `git status` is clean and the branch is ready for review**

Run: `git status` and `git log --oneline origin/master..HEAD`
Expected: clean tree, ~5 commits matching the tasks above.

- [ ] **Step 4: Push and open a PR if requested by the user**

Do not push without explicit user instruction. Stop and ask.
