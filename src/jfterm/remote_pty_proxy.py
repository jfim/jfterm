from __future__ import annotations

import contextlib
import json
import socket

import gi

gi.require_version("Vte", "3.91")
from gi.repository import GLib, GObject  # noqa: E402

from jfterm import muxer_proto as mp  # noqa: E402


class RemotePtyProxy(GObject.Object):
    """Drop-in for PtyProxy backed by a jftermd session socket.

    Exposes the identical signals so JFTermTerminal's handlers are unchanged:
      data-ready(bytes), progress-changed(int,int), running-changed(bool),
      child-exited(int).
    """

    __gsignals__ = {
        "data-ready": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "progress-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        "running-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "child-exited": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    READ_CHUNK = 65536

    def __init__(
        self,
        sock: socket.socket,
        *,
        session_id: str,
        cwd: str,
        argv: list[str],
        cols: int,
        rows: int,
        want_chunks: int = 0,
        send_after_open: str | None = None,
    ) -> None:
        super().__init__()
        self._sock = sock
        self._sock.setblocking(False)
        self._dec = mp.FrameDecoder()
        self._closed = False
        self._fd_watch: int | None = None

        self._send(
            mp.encode_json_frame(
                mp.FrameType.ATTACH_OR_OPEN,
                {
                    "session_id": session_id,
                    "cwd": cwd,
                    "argv": argv,
                    "want_chunks": want_chunks,
                    "cols": cols,
                    "rows": rows,
                },
            )
        )
        # Only a freshly OPENed session gets the launch command; an adopted
        # (attached) session passes send_after_open=None.
        if send_after_open is not None:
            self._send(mp.encode_frame(mp.FrameType.INPUT, (send_after_open + "\n").encode()))

        self._fd_watch = GLib.unix_fd_add_full(
            GLib.PRIORITY_DEFAULT,
            self._sock.fileno(),
            GLib.IOCondition.IN | GLib.IOCondition.HUP,
            self._on_readable,
        )

    # PtyProxy-compatible shape; shells live in the daemon now.
    @property
    def shell_pid(self) -> int | None:
        return None

    @property
    def pty_fd(self) -> int | None:
        return None

    def _send(self, frame: bytes) -> None:
        if self._closed:
            return
        with contextlib.suppress(OSError):
            self._sock.sendall(frame)

    def _on_readable(self, _fd: int, condition: GLib.IOCondition) -> bool:
        if self._closed:
            return False
        try:
            chunk = self._sock.recv(self.READ_CHUNK)
        except BlockingIOError:
            return True
        except OSError:
            self._detach_cleanup()
            return False
        if not chunk:  # EOF: takeover/detach or daemon gone (NOT a child exit)
            self._detach_cleanup()
            return False
        try:
            frames = self._dec.feed(chunk)
        except mp.ProtocolError:
            self._detach_cleanup()
            return False
        for ftype, value in frames:
            self._dispatch(ftype, value)
        return True

    def _dispatch(self, ftype: int, value: bytes) -> None:
        if ftype == mp.FrameType.DATA:
            self.emit("data-ready", value)
        elif ftype == mp.FrameType.STATUS:
            obj = json.loads(value) if value else {}
            if "running" in obj:
                self.emit("running-changed", bool(obj["running"]))
            if "progress" in obj:
                # Protocol gives a scalar 0-100 or null; map onto the existing
                # (state, value) progress-changed signal: null -> hidden (0, 0),
                # else set (1, value).
                progress = obj["progress"]
                if progress is None:
                    self.emit("progress-changed", 0, 0)
                else:
                    self.emit("progress-changed", 1, int(progress))
        elif ftype == mp.FrameType.EXIT:
            obj = json.loads(value) if value else {}
            self.emit("child-exited", int(obj.get("status", 0)))

    def _detach_cleanup(self) -> None:
        if self._fd_watch is not None:
            GLib.source_remove(self._fd_watch)
            self._fd_watch = None
        if not self._closed:
            self._closed = True
            with contextlib.suppress(OSError):
                self._sock.close()

    def write(self, data: bytes) -> None:
        self._send(mp.encode_frame(mp.FrameType.INPUT, data))

    def resize(self, rows: int, cols: int) -> None:
        if rows <= 0 or cols <= 0:
            return
        self._send(mp.encode_json_frame(mp.FrameType.RESIZE, {"cols": cols, "rows": rows}))

    def close(self, grace_ms: int = 0) -> None:
        """Kill the daemon session and tear down. Idempotent. The daemon SIGHUPs
        the shell's process group, escalating to SIGKILL after grace_ms if set;
        signal choice/escalation lives in the daemon, not the client."""
        if self._closed:
            return
        self._send(mp.encode_json_frame(mp.FrameType.CLOSE, {"grace_ms": grace_ms}))
        self._detach_cleanup()

    def detach(self) -> None:
        """Tear down the socket without CLOSE; leaves the daemon session alive."""
        self._detach_cleanup()
