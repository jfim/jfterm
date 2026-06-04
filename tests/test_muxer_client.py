import os
import subprocess
import threading
from pathlib import Path

import pytest

from jfterm import muxer_proto as mp
from jfterm.muxer_client import MuxerClient, hello, list_sessions, socket_path


def test_socket_path_uses_xdg_runtime_dir(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert socket_path() == Path("/run/user/1000/jfterm/muxer.sock")


def test_socket_path_falls_back_to_tmp(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    p = socket_path()
    assert p.name == "muxer.sock"
    assert p.parent.name == "jfterm"


def _serve_once(sock_path, responder, ready: threading.Event | None = None):
    srv = mp_unix_server(sock_path)
    if ready is not None:
        ready.set()
    conn, _ = srv.accept()
    dec = mp.FrameDecoder()
    try:
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            for ftype, value in dec.feed(chunk):
                responder(conn, ftype, value)
    finally:
        conn.close()
        srv.close()


def mp_unix_server(sock_path):
    import socket as _s

    srv = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
    srv.bind(str(sock_path))
    srv.listen(1)
    return srv


def test_hello_roundtrip(tmp_path):
    sock_path = tmp_path / "m.sock"

    def responder(conn, ftype, value):
        if ftype == mp.FrameType.HELLO:
            conn.sendall(
                mp.encode_json_frame(
                    mp.FrameType.HELLO_OK,
                    {"proto_version": mp.PROTO_VERSION, "daemon_version": "0.1"},
                )
            )

    ready = threading.Event()
    t = threading.Thread(target=_serve_once, args=(sock_path, responder, ready), daemon=True)
    t.start()
    ready.wait(timeout=5)
    import socket as _s

    c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
    c.connect(str(sock_path))
    ok = hello(c)
    assert ok == {"proto_version": mp.PROTO_VERSION, "daemon_version": "0.1"}
    c.close()


def test_list_sessions_returns_session_dicts(tmp_path):
    sock_path = tmp_path / "m.sock"
    sessions = [
        {
            "session_id": "a",
            "argv": ["bash"],
            "cwd": "/tmp",
            "running": True,
            "has_client": False,
            "created_at": 1.0,
        }
    ]

    def responder(conn, ftype, value):
        if ftype == mp.FrameType.LIST:
            conn.sendall(mp.encode_json_frame(mp.FrameType.SESSIONS, sessions))

    ready = threading.Event()
    t = threading.Thread(target=_serve_once, args=(sock_path, responder, ready), daemon=True)
    t.start()
    ready.wait(timeout=5)
    import socket as _s

    c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
    c.connect(str(sock_path))
    assert list_sessions(c) == sessions
    c.close()


class _FakeProc:
    """Stand-in for a spawned jftermd that never really launches."""

    returncode = 0

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def test_connect_or_spawn_does_not_unlink_live_socket(tmp_path, monkeypatch):
    # A transient ECONNREFUSED against a *healthy* daemon must not make the
    # client delete that daemon's live socket. Stale-socket cleanup belongs to
    # the daemon under its flock (PROTOCOL-v1 "Spawning the daemon").
    sock_path = tmp_path / "jfterm" / "muxer.sock"
    sock_path.parent.mkdir(parents=True)
    monkeypatch.setattr("jfterm.muxer_client.socket_path", lambda: sock_path)

    srv = mp_unix_server(sock_path)  # a live daemon listening on the socket
    threading.Thread(target=srv.accept, daemon=True).start()

    client = MuxerClient()
    monkeypatch.setattr(client, "SPAWN_RETRIES", 3)
    monkeypatch.setattr(client, "SPAWN_DELAY", 0.01)
    monkeypatch.setattr(client, "_spawn_daemon", lambda: _FakeProc())

    real_connect = client._connect_raw
    calls = {"n": 0}

    def flaky_connect():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionRefusedError("transient refusal")
        return real_connect()

    monkeypatch.setattr(client, "_connect_raw", flaky_connect)

    sock = client._connect_or_spawn()
    try:
        assert sock.fileno() >= 0
    finally:
        sock.close()
    assert sock_path.exists(), "client unlinked a live daemon's socket"
    srv.close()


def test_spawn_daemon_reaps_double_fork_child(tmp_path, monkeypatch):
    # jftermd double-forks, so the process the client launches exits at once.
    # The client must reap it; otherwise it lingers as a `[jftermd] <defunct>`
    # zombie until the next spawn or app exit.
    sock_path = tmp_path / "jfterm" / "muxer.sock"
    monkeypatch.setattr("jfterm.muxer_client.socket_path", lambda: sock_path)

    real_popen = subprocess.Popen
    captured = {}

    def fake_popen(_cmd, **kwargs):
        proc = real_popen(["true"], **kwargs)
        captured["pid"] = proc.pid
        return proc

    monkeypatch.setattr("jfterm.muxer_client.subprocess.Popen", fake_popen)

    MuxerClient()._spawn_daemon()

    with pytest.raises(ChildProcessError):
        os.waitpid(captured["pid"], 0)


def test_connect_session_connects_to_existing_socket(tmp_path, monkeypatch):
    sock_path = tmp_path / "jfterm" / "muxer.sock"
    sock_path.parent.mkdir(parents=True)
    monkeypatch.setattr("jfterm.muxer_client.socket_path", lambda: sock_path)

    srv = mp_unix_server(sock_path)
    accepted: list = []
    threading.Thread(target=lambda: accepted.append(srv.accept()), daemon=True).start()

    client = MuxerClient()
    sess = client.connect_session()
    assert sess.fileno() >= 0
    sess.close()
    srv.close()
