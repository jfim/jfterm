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
