# Configurable Launcher Shortcut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users pick the quick launcher hotkey from a curated dropdown of presets (Double Shift / Ctrl+Shift+P / Ctrl+P / Ctrl+Shift+F2), persisted in settings and applied live.

**Architecture:** Add a `launcher_shortcut` enum string to `AppSettings` with a small whitelist. In `JFTermWindow`, replace the hard-coded `DoubleTapDetector` install with two helpers (`_install_launcher_shortcut` / `_uninstall_launcher_shortcut`) that dispatch on the preset ID — installing either the existing detector or a `Gtk.ShortcutController` with one accelerator. Wire the existing `_on_settings_changed` handler to re-bind on change. Add one `Adw.ComboRow` to `AppPreferencesDialog`.

**Tech Stack:** Python 3.12, GTK4 / libadwaita via PyGObject, pytest. Test runner: `uv run pytest` (or `just test`). Lint/format: `uv run ruff check .` / `uv run ruff format .`.

**Reference spec:** [docs/superpowers/specs/2026-05-07-configurable-launcher-shortcut-design.md](docs/superpowers/specs/2026-05-07-configurable-launcher-shortcut-design.md)

---

## Task 1: Add `launcher_shortcut` to settings with preset whitelist

**Files:**
- Modify: `src/jfterm/settings.py`
- Test: `tests/test_settings.py`

The whitelist of valid IDs is the single source of truth for which presets exist. Defining it in `settings.py` lets both the window wiring and the Preferences UI import the same tuple.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
def test_load_default_launcher_shortcut(tmp_path: Path):
    s = load(tmp_path / "missing.json")
    assert s.launcher_shortcut == "double_shift"


def test_save_then_load_roundtrips_launcher_shortcut(tmp_path: Path):
    path = tmp_path / "settings.json"
    save(AppSettings(launcher_shortcut="ctrl_shift_p"), path)
    s = load(path)
    assert s.launcher_shortcut == "ctrl_shift_p"


def test_load_unknown_launcher_shortcut_falls_back(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"launcher_shortcut": "double_alt"}))
    s = load(path)
    assert s.launcher_shortcut == "double_shift"


def test_load_non_string_launcher_shortcut_falls_back(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"launcher_shortcut": 42}))
    s = load(path)
    assert s.launcher_shortcut == "double_shift"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_settings.py -v`
Expected: 4 new tests FAIL (AttributeError on `launcher_shortcut`).

- [ ] **Step 3: Implement the field and validation**

Edit `src/jfterm/settings.py`. Add the whitelist constant near the top of the file (after the imports, before `AppSettings`):

```python
LAUNCHER_SHORTCUT_IDS: tuple[str, ...] = (
    "double_shift",
    "ctrl_shift_p",
    "ctrl_p",
    "ctrl_shift_f2",
)
DEFAULT_LAUNCHER_SHORTCUT = "double_shift"
```

Add the field to `AppSettings`:

```python
@dataclass
class AppSettings:
    font_desc: str = ""
    palette_id: str = "system"
    mcp_enabled: bool = False
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 7820
    launcher_shortcut: str = DEFAULT_LAUNCHER_SHORTCUT
```

Update `load()` to parse and validate the new key. The full new body of `load()`:

```python
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
    defaults = AppSettings()
    try:
        port = int(data.get("mcp_port", defaults.mcp_port))
    except (TypeError, ValueError):
        port = defaults.mcp_port
    if not (1 <= port <= 65535):
        port = defaults.mcp_port
    raw_shortcut = data.get("launcher_shortcut", DEFAULT_LAUNCHER_SHORTCUT)
    shortcut = (
        raw_shortcut
        if isinstance(raw_shortcut, str) and raw_shortcut in LAUNCHER_SHORTCUT_IDS
        else DEFAULT_LAUNCHER_SHORTCUT
    )
    return AppSettings(
        font_desc=str(data.get("font_desc", "")),
        palette_id=str(data.get("palette_id", "system")),
        mcp_enabled=bool(data.get("mcp_enabled", defaults.mcp_enabled)),
        mcp_host=str(data.get("mcp_host", defaults.mcp_host)),
        mcp_port=port,
        launcher_shortcut=shortcut,
    )
```

`save()` is unchanged — `asdict()` picks up the new field automatically.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_settings.py -v`
Expected: all tests PASS (existing ones still green, 4 new ones green).

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/settings.py tests/test_settings.py
git commit -m "feat(settings): add launcher_shortcut preset with validation"
```

---

## Task 2: Extract launcher shortcut presets into a small mapping module

**Files:**
- Create: `src/jfterm/launcher_shortcut.py`
- Test: `tests/test_launcher_shortcut.py`

This module owns the mapping from preset ID to (display label, accelerator string) and serves as the install target for both window wiring and Preferences UI. Keeping it separate from `window.py` makes it testable without GTK setup.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_launcher_shortcut.py`:

```python
import pytest

from jfterm.launcher_shortcut import (
    LAUNCHER_SHORTCUT_PRESETS,
    accelerator_for,
    label_for,
)
from jfterm.settings import LAUNCHER_SHORTCUT_IDS


def test_presets_cover_all_settings_ids():
    assert tuple(LAUNCHER_SHORTCUT_PRESETS.keys()) == LAUNCHER_SHORTCUT_IDS


def test_double_shift_has_no_accelerator():
    assert accelerator_for("double_shift") is None


@pytest.mark.parametrize(
    "preset_id,expected",
    [
        ("ctrl_shift_p", "<Control><Shift>p"),
        ("ctrl_p", "<Control>p"),
        ("ctrl_shift_f2", "<Control><Shift>F2"),
    ],
)
def test_chord_accelerator_strings(preset_id: str, expected: str):
    assert accelerator_for(preset_id) == expected


def test_labels_are_human_readable():
    assert label_for("double_shift") == "Double Shift"
    assert label_for("ctrl_shift_p") == "Ctrl+Shift+P"
    assert label_for("ctrl_p") == "Ctrl+P"
    assert label_for("ctrl_shift_f2") == "Ctrl+Shift+F2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_launcher_shortcut.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jfterm.launcher_shortcut'`.

- [ ] **Step 3: Implement the module**

Create `src/jfterm/launcher_shortcut.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LauncherShortcutPreset:
    label: str
    accelerator: str | None  # None means double-tap, no Gtk accelerator


LAUNCHER_SHORTCUT_PRESETS: dict[str, LauncherShortcutPreset] = {
    "double_shift": LauncherShortcutPreset("Double Shift", None),
    "ctrl_shift_p": LauncherShortcutPreset("Ctrl+Shift+P", "<Control><Shift>p"),
    "ctrl_p": LauncherShortcutPreset("Ctrl+P", "<Control>p"),
    "ctrl_shift_f2": LauncherShortcutPreset("Ctrl+Shift+F2", "<Control><Shift>F2"),
}


def label_for(preset_id: str) -> str:
    return LAUNCHER_SHORTCUT_PRESETS[preset_id].label


def accelerator_for(preset_id: str) -> str | None:
    return LAUNCHER_SHORTCUT_PRESETS[preset_id].accelerator
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_launcher_shortcut.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/launcher_shortcut.py tests/test_launcher_shortcut.py
git commit -m "feat(launcher): preset table mapping shortcut IDs to accelerators"
```

---

## Task 3: Refactor window launcher install into helpers (no behavior change)

**Files:**
- Modify: `src/jfterm/window.py` (the install block at ~lines 171-184 and the handler at ~lines 1080-1087)

This task keeps behavior identical (`double_shift` only) but reshapes the wiring so Task 4 can swap modes cleanly. Verification is manual: run the app and confirm double-Shift still opens the launcher.

- [ ] **Step 1: Replace the inline install block with a helper call**

In `src/jfterm/window.py`, find the block starting near line 171:

```python
        # Command launcher (issue #19)
        from jfterm.double_tap import DoubleTapDetector
        from jfterm.launcher import Launcher

        self._launcher = Launcher(self, dispatch=self._dispatch_launcher_action)
        self._double_shift = DoubleTapDetector(
            target_keyval=Gdk.KEY_Shift_L,
            interval_ms=300,
            callback=self._open_launcher,
        )
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", self._on_window_key_pressed)
        self.add_controller(key_ctrl)
```

Replace with:

```python
        # Command launcher (issue #19)
        from jfterm.launcher import Launcher

        self._launcher = Launcher(self, dispatch=self._dispatch_launcher_action)
        self._launcher_shortcut_state: tuple[Gtk.EventControllerKey | None, Gtk.ShortcutController | None] = (None, None)
        self._double_shift = None
        self._install_launcher_shortcut(self._settings.launcher_shortcut)
```

- [ ] **Step 2: Add the install/uninstall helpers**

Add these methods to `JFTermWindow` (place them near `_open_launcher`, around line 1086):

```python
    def _install_launcher_shortcut(self, preset_id: str) -> None:
        from jfterm.double_tap import DoubleTapDetector
        from jfterm.launcher_shortcut import accelerator_for

        accel = accelerator_for(preset_id)
        key_ctrl: Gtk.EventControllerKey | None = None
        shortcut_ctrl: Gtk.ShortcutController | None = None

        if accel is None:
            self._double_shift = DoubleTapDetector(
                target_keyval=Gdk.KEY_Shift_L,
                interval_ms=300,
                callback=self._open_launcher,
            )
            key_ctrl = Gtk.EventControllerKey()
            key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            key_ctrl.connect("key-pressed", self._on_window_key_pressed)
            self.add_controller(key_ctrl)
        else:
            self._double_shift = None
            shortcut_ctrl = Gtk.ShortcutController()
            shortcut_ctrl.set_scope(Gtk.ShortcutScope.LOCAL)
            shortcut_ctrl.add_shortcut(
                Gtk.Shortcut.new(
                    Gtk.ShortcutTrigger.parse_string(accel),
                    Gtk.CallbackAction.new(self._on_launcher_accelerator),
                )
            )
            self.add_controller(shortcut_ctrl)

        self._launcher_shortcut_state = (key_ctrl, shortcut_ctrl)

    def _uninstall_launcher_shortcut(self) -> None:
        key_ctrl, shortcut_ctrl = self._launcher_shortcut_state
        if key_ctrl is not None:
            self.remove_controller(key_ctrl)
        if shortcut_ctrl is not None:
            self.remove_controller(shortcut_ctrl)
        self._double_shift = None
        self._launcher_shortcut_state = (None, None)

    def _on_launcher_accelerator(self, _widget, _args) -> bool:
        self._open_launcher()
        return True
```

- [ ] **Step 3: Update `_on_window_key_pressed` and `_open_launcher` to handle a None detector**

Find `_on_window_key_pressed` (around line 1080):

```python
    def _on_window_key_pressed(self, _ctrl, keyval, _keycode, _state) -> bool:
        from gi.repository import GLib

        self._double_shift.on_press(keyval, GLib.get_monotonic_time() // 1000)
        return False
```

Replace with:

```python
    def _on_window_key_pressed(self, _ctrl, keyval, _keycode, _state) -> bool:
        from gi.repository import GLib

        if self._double_shift is not None:
            self._double_shift.on_press(keyval, GLib.get_monotonic_time() // 1000)
        return False
```

Find `_open_launcher` (around line 1086):

```python
    def _open_launcher(self) -> None:
        self._double_shift.reset()
        self._launcher.open(self.ws)
```

Replace with:

```python
    def _open_launcher(self) -> None:
        if self._double_shift is not None:
            self._double_shift.reset()
        self._launcher.open(self.ws)
```

- [ ] **Step 4: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS (no test changes; this verifies nothing regressed).

- [ ] **Step 5: Manual smoke test**

Run: `uv run python -m jfterm`
- Press Left-Shift twice quickly. Expected: launcher opens.
- Type some characters, then Left-Shift twice quickly. Expected: launcher opens.
- Close the app.

- [ ] **Step 6: Lint and format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: both pass. If ruff format fails, run `uv run ruff format .` and re-check.

- [ ] **Step 7: Commit**

```bash
git add src/jfterm/window.py
git commit -m "refactor(window): extract launcher shortcut install into helpers"
```

---

## Task 4: Wire chord presets through the helpers (live re-bind on settings change)

**Files:**
- Modify: `src/jfterm/window.py` — the `_on_settings_changed` handler at ~line 1035

After Task 3, the helpers already support both modes. This task only adds the live re-bind path.

- [ ] **Step 1: Update `_on_settings_changed` to re-bind when the shortcut changed**

Find `_on_settings_changed` (around line 1035):

```python
    def _on_settings_changed(self, _dialog, settings: AppSettings) -> None:
        self._settings = settings
        try:
            save_settings(settings, self._settings_path)
        except OSError as e:
            print(f"jfterm: failed to save settings: {e}", file=sys.stderr)
        for terminal in self._iter_terminals():
            terminal.apply_appearance(settings)
```

Replace with:

```python
    def _on_settings_changed(self, _dialog, settings: AppSettings) -> None:
        previous_shortcut = self._settings.launcher_shortcut
        self._settings = settings
        try:
            save_settings(settings, self._settings_path)
        except OSError as e:
            print(f"jfterm: failed to save settings: {e}", file=sys.stderr)
        for terminal in self._iter_terminals():
            terminal.apply_appearance(settings)
        if settings.launcher_shortcut != previous_shortcut:
            self._uninstall_launcher_shortcut()
            self._install_launcher_shortcut(settings.launcher_shortcut)
```

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS.

- [ ] **Step 3: Manual smoke test of all four presets**

Run: `uv run python -m jfterm`

The Preferences dropdown lands in Task 5, so for now exercise the install path by editing `~/.config/jfterm/settings.json` (or `$XDG_CONFIG_HOME/jfterm/settings.json`) between launches:

- Set `"launcher_shortcut": "ctrl_shift_p"`, restart, press Ctrl+Shift+P → launcher opens.
- Set `"launcher_shortcut": "ctrl_p"`, restart, press Ctrl+P → launcher opens.
- Set `"launcher_shortcut": "ctrl_shift_f2"`, restart, press Ctrl+Shift+F2 → launcher opens.
- Set `"launcher_shortcut": "double_shift"`, restart, double-Left-Shift → launcher opens.
- Set `"launcher_shortcut": "garbage"`, restart, double-Left-Shift → launcher opens (fallback).

Note: in `ctrl_p` mode, Ctrl+P is consumed by the launcher, so terminal apps that use Ctrl+P (e.g. vim previous-line) will not receive it while the binding is active. This is expected — the user opted in.

- [ ] **Step 4: Lint and format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: both pass.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(window): rebind launcher shortcut live when setting changes"
```

---

## Task 5: Add the launcher shortcut dropdown to Preferences

**Files:**
- Modify: `src/jfterm/preferences.py`

- [ ] **Step 1: Extend `AppPreferencesDialog.__init__` to seed the new field**

Find the `self._settings = AppSettings(...)` block at the top of `__init__` (around line 40):

```python
        self._settings = AppSettings(
            font_desc=settings.font_desc,
            palette_id=settings.palette_id,
            mcp_enabled=settings.mcp_enabled,
            mcp_host=settings.mcp_host,
            mcp_port=settings.mcp_port,
        )
```

Replace with:

```python
        self._settings = AppSettings(
            font_desc=settings.font_desc,
            palette_id=settings.palette_id,
            mcp_enabled=settings.mcp_enabled,
            mcp_host=settings.mcp_host,
            mcp_port=settings.mcp_port,
            launcher_shortcut=settings.launcher_shortcut,
        )
```

- [ ] **Step 2: Add the import for the preset table**

Find the imports near the top of `preferences.py`:

```python
from jfterm.palettes import PALETTES  # noqa: E402
from jfterm.settings import AppSettings  # noqa: E402
```

Replace with:

```python
from jfterm.launcher_shortcut import LAUNCHER_SHORTCUT_PRESETS  # noqa: E402
from jfterm.palettes import PALETTES  # noqa: E402
from jfterm.settings import LAUNCHER_SHORTCUT_IDS, AppSettings  # noqa: E402
```

- [ ] **Step 3: Add the dropdown row to the Terminal group**

Find the end of the palette row block (just after `group.add(self._palette_row)`, around line 90) and BEFORE `page.add(group)`. Insert:

```python
        # --- Quick launcher shortcut row ---
        shortcut_names = Gtk.StringList()
        for preset_id in LAUNCHER_SHORTCUT_IDS:
            shortcut_names.append(LAUNCHER_SHORTCUT_PRESETS[preset_id].label)
        self._launcher_shortcut_row = Adw.ComboRow()
        self._launcher_shortcut_row.set_title("Quick launcher shortcut")
        self._launcher_shortcut_row.set_model(shortcut_names)
        current_shortcut_index = next(
            (
                i
                for i, sid in enumerate(LAUNCHER_SHORTCUT_IDS)
                if sid == self._settings.launcher_shortcut
            ),
            0,
        )
        self._launcher_shortcut_row.set_selected(current_shortcut_index)
        self._launcher_shortcut_row.connect(
            "notify::selected", self._on_launcher_shortcut_changed
        )
        group.add(self._launcher_shortcut_row)
```

- [ ] **Step 4: Add the change handler**

Add this method to `AppPreferencesDialog` alongside the other `_on_*_changed` handlers:

```python
    def _on_launcher_shortcut_changed(self, row: Adw.ComboRow, _pspec) -> None:
        idx = row.get_selected()
        if 0 <= idx < len(LAUNCHER_SHORTCUT_IDS):
            self._settings.launcher_shortcut = LAUNCHER_SHORTCUT_IDS[idx]
            self.emit("changed", self._copy())
```

- [ ] **Step 5: Update `_copy` to include the new field**

Find `_copy` (around line 147):

```python
    def _copy(self) -> AppSettings:
        return AppSettings(
            font_desc=self._settings.font_desc,
            palette_id=self._settings.palette_id,
            mcp_enabled=self._settings.mcp_enabled,
            mcp_host=self._settings.mcp_host,
            mcp_port=self._settings.mcp_port,
        )
```

Replace with:

```python
    def _copy(self) -> AppSettings:
        return AppSettings(
            font_desc=self._settings.font_desc,
            palette_id=self._settings.palette_id,
            mcp_enabled=self._settings.mcp_enabled,
            mcp_host=self._settings.mcp_host,
            mcp_port=self._settings.mcp_port,
            launcher_shortcut=self._settings.launcher_shortcut,
        )
```

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS.

- [ ] **Step 7: Manual end-to-end smoke test**

Run: `uv run python -m jfterm`

- Open Preferences. Verify the "Quick launcher shortcut" row shows the four labels in order: Double Shift, Ctrl+Shift+P, Ctrl+P, Ctrl+Shift+F2.
- The current value (Double Shift on a fresh install) is selected.
- Change selection to "Ctrl+Shift+P". Close Preferences. Without restarting, press Ctrl+Shift+P → launcher opens.
- Re-open Preferences, change to "Ctrl+P". Close. Press Ctrl+P → launcher opens.
- Re-open Preferences, change to "Ctrl+Shift+F2". Close. Press Ctrl+Shift+F2 → launcher opens.
- Re-open Preferences, change back to "Double Shift". Close. Double-Left-Shift → launcher opens.
- Inspect `~/.config/jfterm/settings.json` after each change to confirm the value is persisted.

- [ ] **Step 8: Lint, format, and typecheck**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pyright`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/jfterm/preferences.py
git commit -m "feat(preferences): add quick launcher shortcut dropdown"
```

---

## Task 6: Final verification

- [ ] **Step 1: Run full CI-equivalent suite**

Run: `just check`
Expected: lint, format-check, typecheck, and tests all PASS.

- [ ] **Step 2: Manually verify backward compatibility**

Delete `~/.config/jfterm/settings.json` (or back it up first). Run: `uv run python -m jfterm`. Expected: app launches with Double Shift as the active binding (default for fresh install).

Restore your settings file if you backed it up.

- [ ] **Step 3: Confirm no stray TODOs remain**

Run: `git diff master -- src/jfterm tests | grep -i -E "TODO|FIXME|XXX" || echo "clean"`
Expected: prints `clean`.
