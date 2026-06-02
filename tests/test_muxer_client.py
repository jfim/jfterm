import json
import threading
from pathlib import Path

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
        {"session_id": "a", "argv": ["bash"], "cwd": "/tmp", "running": True,
         "has_client": False, "created_at": 1.0}
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
