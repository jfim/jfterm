from __future__ import annotations

from pathlib import Path

from jfterm.mcp_token import default_path, load_or_create, regenerate


def test_load_or_create_generates_when_missing(tmp_path: Path):
    path = tmp_path / "mcp-token"
    token = load_or_create(path)
    assert token
    assert path.exists()
    assert path.read_text().strip() == token


def test_load_or_create_is_stable_across_calls(tmp_path: Path):
    path = tmp_path / "mcp-token"
    first = load_or_create(path)
    second = load_or_create(path)
    assert first == second


def test_generated_file_has_0600_mode(tmp_path: Path):
    path = tmp_path / "mcp-token"
    load_or_create(path)
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_load_or_create_tightens_loose_perms(tmp_path: Path):
    path = tmp_path / "mcp-token"
    load_or_create(path)
    path.chmod(0o644)
    load_or_create(path)
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_regenerate_replaces_existing(tmp_path: Path):
    path = tmp_path / "mcp-token"
    first = load_or_create(path)
    second = regenerate(path)
    assert first != second
    assert path.read_text().strip() == second


def test_load_or_create_creates_parent_dir(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "mcp-token"
    token = load_or_create(path)
    assert path.exists()
    assert token


def test_default_path_uses_xdg_config_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_path() == tmp_path / "jfterm" / "mcp-token"
