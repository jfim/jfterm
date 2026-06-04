from __future__ import annotations

import contextlib
import json
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
    dec = mp.FrameDecoder()
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("muxer closed during frame read")
        frames = dec.feed(chunk)
        # Control exchanges are strict request/response: at most one frame
        # per reply, so returning the first is sufficient.
        if frames:
            return frames[0]


def hello(sock: socket.socket) -> dict:
    """Send HELLO, return the daemon's HELLO_OK payload. Raises on mismatch."""
    sock.sendall(
        mp.encode_json_frame(
            mp.FrameType.HELLO,
            {"proto_version": mp.PROTO_VERSION, "daemon_version": ""},
        )
    )
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

    def _spawn_daemon(self) -> subprocess.Popen[bytes]:
        """Self-spawn jftermd, detached from this process (setsid), then reap it."""
        socket_path().parent.mkdir(parents=True, exist_ok=True)
        # start_new_session=True == setsid; the daemon owns its own double-fork
        # + flock lockfile to win spawn races (see spec "Daemon unreachable").
        proc = subprocess.Popen(
            ["jftermd"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # jftermd double-forks: the process we launched exits the moment it has
        # spawned the detached daemon. Reap it so it does not linger as a
        # `[jftermd] <defunct>` zombie until the next spawn or app exit.
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=self.SPAWN_RETRIES * self.SPAWN_DELAY)
        return proc

    def _connect_or_spawn(self) -> socket.socket:
        try:
            return self._connect_raw()
        except (FileNotFoundError, ConnectionRefusedError):
            # No daemon reachable → (re)spawn and retry. Stale-socket cleanup is
            # the daemon's job under its flock, so we must NOT unlink the socket
            # here: a transient refusal against a healthy daemon would otherwise
            # delete its live socket and wedge it.
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
            try:
                hello(sock)
            except Exception:
                sock.close()
                raise
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
