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
