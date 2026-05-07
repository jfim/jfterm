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
