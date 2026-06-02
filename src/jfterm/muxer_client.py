from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import time
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


class MuxerClient:
    """Owns the control connection and spawns jftermd on demand."""

    SPAWN_RETRIES = 50  # ~5s at 100ms
    SPAWN_DELAY = 0.1

    def __init__(self) -> None:
        self._control: socket.socket | None = None

    def _connect_raw(self) -> socket.socket:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(socket_path()))
        return s

    def _spawn_daemon(self) -> None:
        """Self-spawn jftermd, detached from this process (setsid)."""
        socket_path().parent.mkdir(parents=True, exist_ok=True)
        # start_new_session=True == setsid; the daemon owns its own double-fork
        # + flock lockfile to win spawn races (see spec "Daemon unreachable").
        subprocess.Popen(
            ["jftermd"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _connect_or_spawn(self) -> socket.socket:
        try:
            return self._connect_raw()
        except (FileNotFoundError, ConnectionRefusedError):
            # Stale socket file → unlink; then (re)spawn and retry.
            with contextlib.suppress(FileNotFoundError):
                if socket_path().exists():
                    socket_path().unlink()
            self._spawn_daemon()
        for _ in range(self.SPAWN_RETRIES):
            try:
                return self._connect_raw()
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(self.SPAWN_DELAY)
        raise ConnectionError("could not connect to or spawn jftermd")

    def control(self) -> socket.socket:
        """Lazily establish the HELLO-validated control connection."""
        if self._control is None:
            sock = self._connect_or_spawn()
            hello(sock)
            self._control = sock
        return self._control

    def list_sessions(self) -> list[dict]:
        return list_sessions(self.control())

    def connect_session(self) -> socket.socket:
        """A fresh connected session socket (caller sends ATTACH_OR_OPEN)."""
        return self._connect_or_spawn()

    def close(self) -> None:
        if self._control is not None:
            with contextlib.suppress(OSError):
                self._control.close()
            self._control = None
