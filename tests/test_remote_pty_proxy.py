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
