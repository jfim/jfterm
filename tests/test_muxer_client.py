from pathlib import Path

from jfterm.muxer_client import socket_path


def test_socket_path_uses_xdg_runtime_dir(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert socket_path() == Path("/run/user/1000/jfterm/muxer.sock")


def test_socket_path_falls_back_to_tmp(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    p = socket_path()
    assert p.name == "muxer.sock"
    assert p.parent.name == "jfterm"
