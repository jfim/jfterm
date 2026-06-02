from __future__ import annotations

import os
import socket
from pathlib import Path

from jfterm import muxer_proto as mp


def socket_path() -> Path:
    """$XDG_RUNTIME_DIR/jfterm/muxer.sock, or /tmp/jfterm-$UID/ as a fallback."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path(f"/tmp/jfterm-{os.getuid()}")
    return base / "jfterm" / "muxer.sock"


def _recv_one_frame(sock: socket.socket) -> tuple[int, bytes]:
    """Blocking read of exactly one TLV frame from a (blocking) socket."""
    import json as _json  # noqa: F401  (kept local; see decode helpers)

    dec = mp.FrameDecoder()
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("muxer closed during frame read")
        frames = dec.feed(chunk)
        if frames:
            return frames[0]


def hello(sock: socket.socket) -> dict:
    """Send HELLO, return the daemon's HELLO_OK payload. Raises on mismatch."""
    import json

    sock.sendall(mp.encode_json_frame(mp.FrameType.HELLO, {"proto_version": mp.PROTO_VERSION}))
    ftype, value = _recv_one_frame(sock)
    if ftype != mp.FrameType.HELLO_OK:
        raise ConnectionError(f"expected HELLO_OK, got frame type {ftype}")
    payload = json.loads(value)
    if payload.get("proto_version") != mp.PROTO_VERSION:
        raise ConnectionError(
            f"proto mismatch: client {mp.PROTO_VERSION}, daemon {payload.get('proto_version')}"
        )
    return payload


def list_sessions(sock: socket.socket) -> list[dict]:
    """Send LIST, return the SESSIONS array."""
    import json

    sock.sendall(mp.encode_frame(mp.FrameType.LIST, b""))
    ftype, value = _recv_one_frame(sock)
    if ftype != mp.FrameType.SESSIONS:
        raise ConnectionError(f"expected SESSIONS, got frame type {ftype}")
    return json.loads(value)
