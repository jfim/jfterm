import gi

gi.require_version("Vte", "3.91")
from gi.repository import GLib  # noqa: E402

from jfterm import muxer_proto as mp  # noqa: E402
from jfterm.remote_pty_proxy import RemotePtyProxy  # noqa: E402
from tests.fake_muxer import FakeMuxer  # noqa: E402


def test_binds_with_attach_or_open_on_construction():
    fake = FakeMuxer()
    RemotePtyProxy(
        fake.client_sock,
        session_id="sess-1",
        cwd="/tmp",
        argv=["/bin/bash", "-l"],
        cols=80,
        rows=24,
    )
    frames = fake.read_json_frames()
    assert frames[0][0] == mp.FrameType.ATTACH_OR_OPEN
    assert frames[0][1] == {
        "session_id": "sess-1",
        "cwd": "/tmp",
        "argv": ["/bin/bash", "-l"],
        "want_chunks": 0,
        "cols": 80,
        "rows": 24,
    }
    fake.close()


def test_data_frame_emits_data_ready():
    fake = FakeMuxer()
    proxy = RemotePtyProxy(
        fake.client_sock, session_id="s", cwd="/tmp", argv=["x"], cols=80, rows=24
    )
    seen: list[bytes] = []
    proxy.connect("data-ready", lambda _p, data: seen.append(data))
    fake.push(mp.FrameType.DATA, b"output bytes")
    proxy._on_readable(fake.client_sock.fileno(), GLib.IOCondition.IN)
    assert seen == [b"output bytes"]
    fake.close()


def _proxy(fake):
    p = RemotePtyProxy(fake.client_sock, session_id="s", cwd="/tmp", argv=["x"], cols=80, rows=24)
    fake.read_frames()  # drain the ATTACH_OR_OPEN
    return p


def test_write_sends_input_frame():
    fake = FakeMuxer()
    p = _proxy(fake)
    p.write(b"ls\n")
    frames = fake.read_frames()
    assert frames == [(mp.FrameType.INPUT, b"ls\n")]
    fake.close()


def test_resize_sends_resize_json():
    fake = FakeMuxer()
    p = _proxy(fake)
    p.resize(40, 120)  # rows, cols (PtyProxy signature)
    frames = fake.read_json_frames()
    assert frames == [(mp.FrameType.RESIZE, {"cols": 120, "rows": 40})]
    fake.close()


def test_status_frame_emits_running_and_progress():
    fake = FakeMuxer()
    p = _proxy(fake)
    running: list[bool] = []
    progress: list[tuple[int, int]] = []
    p.connect("running-changed", lambda _p, r: running.append(r))
    p.connect("progress-changed", lambda _p, s, v: progress.append((s, v)))
    # Protocol: progress is a scalar 0-100 or null.
    fake.push_json(mp.FrameType.STATUS, {"running": True, "progress": 42})
    p._on_readable(fake.client_sock.fileno(), GLib.IOCondition.IN)
    fake.push_json(mp.FrameType.STATUS, {"running": False, "progress": None})
    p._on_readable(fake.client_sock.fileno(), GLib.IOCondition.IN)
    assert running == [True, False]
    assert progress == [(1, 42), (0, 0)]  # 42 -> set(1,42); null -> hidden(0,0)
    fake.close()


def test_exit_frame_emits_child_exited():
    fake = FakeMuxer()
    p = _proxy(fake)
    statuses: list[int] = []
    p.connect("child-exited", lambda _p, s: statuses.append(s))
    fake.push_json(mp.FrameType.EXIT, {"status": 0})
    p._on_readable(fake.client_sock.fileno(), GLib.IOCondition.IN)
    assert statuses == [0]
    fake.close()


def test_close_sends_close_frame_with_grace():
    fake = FakeMuxer()
    p = _proxy(fake)
    p.close(grace_ms=1500)
    frames = fake.read_json_frames()
    assert frames == [(mp.FrameType.CLOSE, {"grace_ms": 1500})]
    fake.close()


def test_close_default_grace_is_zero():
    fake = FakeMuxer()
    p = _proxy(fake)
    p.close()
    assert fake.read_json_frames() == [(mp.FrameType.CLOSE, {"grace_ms": 0})]
    fake.close()


def test_detach_sends_no_frame():
    fake = FakeMuxer()
    p = _proxy(fake)
    p.detach()
    assert fake.read_frames() == []
    fake.close()


def test_close_is_idempotent_after_detach():
    fake = FakeMuxer()
    p = _proxy(fake)
    p.detach()
    p.close()  # must not raise and must not send (socket already closed)
    assert fake.read_frames() == []
    fake.close()
