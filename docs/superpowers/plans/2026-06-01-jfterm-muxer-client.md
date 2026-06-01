# JFTerm Muxer Client Integration (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make JFTerm terminals outlive the GTK window by moving shells into the `jftermd` daemon, with the client attaching over a Unix-domain-socket TLV protocol; on relaunch, every surviving session is adopted into Unsorted.

**Architecture:** A pure Python TLV codec (`muxer_proto.py`) frames messages over a per-session UDS connection. `RemotePtyProxy` is a drop-in for the in-process `PtyProxy`, exposing the same four GObject signals but sourcing bytes/status from the daemon instead of a local PTY. `MuxerClient` owns the control connection (HELLO/LIST) and self-spawns the daemon. `JFTermTerminal` and `window.py` are rewired: launch adopts live sessions into Unsorted, restart kills via a parameterized `CLOSE`, and closing the window *detaches* (leaving sessions running) instead of killing.

**Tech Stack:** Python 3.12, PyGObject (GTK4/VTE 3.91), `socket` (AF_UNIX), `struct`, `json`, pytest. The daemon (`jftermd`) is a separate Rust repo (`jfterm-muxer`) and is **not** built here — the client codes against the protocol in `docs/superpowers/specs/2026-06-01-terminal-muxer-design.md`.

**Dependency note:** jftermd does not exist yet. Every protocol/transport unit is built and tested against a **fake daemon** (the peer end of a `socket.socketpair()`), so Phases 1–7 are fully implementable and testable now. Steps that require the real daemon (self-spawn round-trip, manual acceptance) are explicitly marked **[GATED: real jftermd]** and are the only ones that cannot be verified until the Rust binary lands.

**Protocol is the contract:** `muxer_proto.py` (frame types, `PROTO_VERSION`, JSON shapes) is the single place that mirrors the muxer repo's `PROTOCOL.md`. If the real daemon diverges, fix it here and in the fake.

---

## File Structure

**Create:**
- `src/jfterm/muxer_proto.py` — TLV framing + message type constants + JSON helpers. Pure, no GTK/socket I/O.
- `src/jfterm/remote_pty_proxy.py` — `RemotePtyProxy`: GObject transport adapter over one session socket.
- `src/jfterm/muxer_client.py` — `MuxerClient`: socket path resolution, control connection (HELLO/LIST), session-socket connect, daemon self-spawn.
- `tests/fake_muxer.py` — test helper: drives the peer end of a socketpair as a fake daemon; encode/decode assertions.
- `tests/test_muxer_proto.py` — codec tests.
- `tests/test_remote_pty_proxy.py` — transport adapter tests.
- `tests/test_muxer_client.py` — control-protocol tests (against a fake control server).

**Modify:**
- `src/jfterm/models.py` — add `session_id` runtime field to `TerminalTab` and `LinkedTab`.
- `src/jfterm/terminal.py` — `JFTermTerminal` takes `session_id` + a `MuxerClient`, uses `RemotePtyProxy`, drops the `tcgetpgrp` poll.
- `src/jfterm/window.py` — create `MuxerClient`, adopt sessions into Unsorted on launch, rewire restart to `CLOSE{SIGTERM,1500}` + new `session_id`, detach all sessions on window close.

**Delete (Phase 7 cleanup):**
- `src/jfterm/pty_proxy.py`, `src/jfterm/osc_scanner.py`, `tests/test_osc_scanner.py`.

---

## Phase 1 — TLV protocol codec

### Task 1.1: Frame type constants and `PROTO_VERSION`

**Files:**
- Create: `src/jfterm/muxer_proto.py`
- Test: `tests/test_muxer_proto.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_muxer_proto.py
from jfterm import muxer_proto as mp


def test_frame_type_values_are_stable():
    assert mp.PROTO_VERSION == 1
    assert mp.FrameType.HELLO == 1
    assert mp.FrameType.HELLO_OK == 2
    assert mp.FrameType.LIST == 3
    assert mp.FrameType.SESSIONS == 4
    assert mp.FrameType.ATTACH_OR_OPEN == 5
    assert mp.FrameType.INPUT == 6
    assert mp.FrameType.RESIZE == 7
    assert mp.FrameType.CLOSE == 8
    assert mp.FrameType.DATA == 9
    assert mp.FrameType.STATUS == 10
    assert mp.FrameType.EXIT == 11
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_muxer_proto.py::test_frame_type_values_are_stable -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jfterm.muxer_proto'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/jfterm/muxer_proto.py
"""TLV wire protocol shared between JFTerm (client) and jftermd (daemon).

This module is the canonical Python mirror of the muxer repo's PROTOCOL.md.
Frame: [u8 type][u32 length big-endian][value … length bytes].
Hot-path frames (DATA, INPUT) carry raw terminal bytes; control frames carry
a JSON object encoded as UTF-8 bytes.
"""

from __future__ import annotations

import enum
import json
import struct

PROTO_VERSION = 1

_HEADER = struct.Struct(">BI")  # 1-byte type, 4-byte big-endian length


class FrameType(enum.IntEnum):
    HELLO = 1
    HELLO_OK = 2
    LIST = 3
    SESSIONS = 4
    ATTACH_OR_OPEN = 5
    INPUT = 6
    RESIZE = 7
    CLOSE = 8
    DATA = 9
    STATUS = 10
    EXIT = 11
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_muxer_proto.py::test_frame_type_values_are_stable -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/muxer_proto.py tests/test_muxer_proto.py
git commit -m "feat(muxer): TLV frame type constants and protocol version"
```

### Task 1.2: `encode_frame` and JSON frame helper

**Files:**
- Modify: `src/jfterm/muxer_proto.py`
- Test: `tests/test_muxer_proto.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_muxer_proto.py  (append)
def test_encode_frame_raw_bytes():
    frame = mp.encode_frame(mp.FrameType.DATA, b"hi")
    assert frame == bytes([9, 0, 0, 0, 2]) + b"hi"


def test_encode_json_frame_roundtrips_shape():
    frame = mp.encode_json_frame(mp.FrameType.RESIZE, {"cols": 80, "rows": 24})
    ftype = frame[0]
    (length,) = mp.struct.Struct(">I").unpack(frame[1:5])
    payload = frame[5:]
    assert ftype == mp.FrameType.RESIZE
    assert length == len(payload)
    assert json.loads(payload) == {"cols": 80, "rows": 24}
```

(Add `import json` at the top of the test file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_muxer_proto.py -k encode -v`
Expected: FAIL — `AttributeError: module 'jfterm.muxer_proto' has no attribute 'encode_frame'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/jfterm/muxer_proto.py  (append)

def encode_frame(ftype: int, value: bytes) -> bytes:
    """One TLV frame: header + raw value bytes."""
    return _HEADER.pack(int(ftype), len(value)) + value


def encode_json_frame(ftype: int, obj: object) -> bytes:
    """A control frame whose value is a compact UTF-8 JSON object."""
    return encode_frame(ftype, json.dumps(obj).encode("utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_muxer_proto.py -k encode -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/muxer_proto.py tests/test_muxer_proto.py
git commit -m "feat(muxer): frame encoders for raw and JSON values"
```

### Task 1.3: `FrameDecoder` — streaming, partial-frame-safe

**Files:**
- Modify: `src/jfterm/muxer_proto.py`
- Test: `tests/test_muxer_proto.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_muxer_proto.py  (append)
def test_decoder_yields_complete_frames():
    dec = mp.FrameDecoder()
    buf = mp.encode_frame(mp.FrameType.DATA, b"abc") + mp.encode_frame(
        mp.FrameType.EXIT, b"{}"
    )
    frames = dec.feed(buf)
    assert frames == [(mp.FrameType.DATA, b"abc"), (mp.FrameType.EXIT, b"{}")]


def test_decoder_handles_split_across_feeds():
    dec = mp.FrameDecoder()
    full = mp.encode_frame(mp.FrameType.DATA, b"hello")
    # Split mid-value.
    assert dec.feed(full[:3]) == []
    assert dec.feed(full[3:]) == [(mp.FrameType.DATA, b"hello")]


def test_decoder_handles_split_inside_header():
    dec = mp.FrameDecoder()
    full = mp.encode_frame(mp.FrameType.INPUT, b"x")
    assert dec.feed(full[:2]) == []  # header is 5 bytes
    assert dec.feed(full[2:]) == [(mp.FrameType.INPUT, b"x")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_muxer_proto.py -k decoder -v`
Expected: FAIL — `AttributeError: ... 'FrameDecoder'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/jfterm/muxer_proto.py  (append)

class FrameDecoder:
    """Accumulates bytes and yields complete (type, value) frames.

    Tolerant of arbitrary chunk boundaries: a frame split across feed() calls
    (even inside the 5-byte header) is buffered until complete.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self._buf.extend(data)
        out: list[tuple[int, bytes]] = []
        while True:
            if len(self._buf) < _HEADER.size:
                break
            ftype, length = _HEADER.unpack_from(self._buf, 0)
            end = _HEADER.size + length
            if len(self._buf) < end:
                break
            value = bytes(self._buf[_HEADER.size:end])
            del self._buf[:end]
            out.append((ftype, value))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_muxer_proto.py -k decoder -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/muxer_proto.py tests/test_muxer_proto.py
git commit -m "feat(muxer): streaming FrameDecoder tolerant of split frames"
```

---

## Phase 2 — `RemotePtyProxy` transport adapter

### Task 2.1: Fake daemon test helper

**Files:**
- Create: `tests/fake_muxer.py`

- [ ] **Step 1: Write the helper (no test of its own; it is exercised by Phase 2/3 tests)**

```python
# tests/fake_muxer.py
"""A fake jftermd peer for tests, built on socket.socketpair().

Hand `client_sock` to RemotePtyProxy/MuxerClient; drive the daemon side with
this helper: push DATA/STATUS/EXIT to the client and read the INPUT/RESIZE/
CLOSE/ATTACH_OR_OPEN frames the client sent.
"""

from __future__ import annotations

import json
import socket

from jfterm import muxer_proto as mp


class FakeMuxer:
    def __init__(self) -> None:
        self.client_sock, self.daemon_sock = socket.socketpair(socket.AF_UNIX)
        self.daemon_sock.setblocking(False)
        self._dec = mp.FrameDecoder()

    def push(self, ftype: int, value: bytes) -> None:
        self.daemon_sock.sendall(mp.encode_frame(ftype, value))

    def push_json(self, ftype: int, obj: object) -> None:
        self.daemon_sock.sendall(mp.encode_json_frame(ftype, obj))

    def read_frames(self) -> list[tuple[int, bytes]]:
        out: list[tuple[int, bytes]] = []
        while True:
            try:
                chunk = self.daemon_sock.recv(65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            out.extend(self._dec.feed(chunk))
        return out

    def read_json_frames(self) -> list[tuple[int, object]]:
        return [
            (t, json.loads(v) if v else None)
            for t, v in self.read_frames()
        ]

    def close(self) -> None:
        self.client_sock.close()
        self.daemon_sock.close()
```

- [ ] **Step 2: Sanity-check it imports**

Run: `uv run python -c "import tests.fake_muxer"`
Expected: no output, exit 0

- [ ] **Step 3: Commit**

```bash
git add tests/fake_muxer.py
git commit -m "test(muxer): socketpair-backed fake daemon helper"
```

### Task 2.2: `RemotePtyProxy` binds and emits `data-ready`

**Files:**
- Create: `src/jfterm/remote_pty_proxy.py`
- Test: `tests/test_remote_pty_proxy.py`

**Design note:** GLib watches the socket and invokes `_on_readable`. Tests do not run a GLib main loop; they call `proxy._on_readable(fd, GLib.IOCondition.IN)` directly after the fake pushes bytes. This mirrors how the real watcher fires.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_remote_pty_proxy.py
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
        "want_chunks": None,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_remote_pty_proxy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jfterm.remote_pty_proxy'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/jfterm/remote_pty_proxy.py
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
        want_chunks: int | None = None,
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
        if not chunk:  # EOF: daemon gone or forced detach
            self._detach_cleanup()
            return False
        for ftype, value in self._dec.feed(chunk):
            self._dispatch(ftype, value)
        return True

    def _dispatch(self, ftype: int, value: bytes) -> None:
        if ftype == mp.FrameType.DATA:
            self.emit("data-ready", value)
        elif ftype == mp.FrameType.STATUS:
            obj = json.loads(value) if value else {}
            if "running" in obj:
                self.emit("running-changed", bool(obj["running"]))
            progress = obj.get("progress")
            if progress is not None:
                self.emit("progress-changed", int(progress[0]), int(progress[1]))
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_remote_pty_proxy.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/remote_pty_proxy.py tests/test_remote_pty_proxy.py
git commit -m "feat(muxer): RemotePtyProxy binds session and emits data-ready"
```

### Task 2.3: `write`, `resize`, STATUS/EXIT dispatch

**Files:**
- Modify: `src/jfterm/remote_pty_proxy.py`
- Test: `tests/test_remote_pty_proxy.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_remote_pty_proxy.py  (append)
def _proxy(fake):
    p = RemotePtyProxy(
        fake.client_sock, session_id="s", cwd="/tmp", argv=["x"], cols=80, rows=24
    )
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
    fake.push_json(mp.FrameType.STATUS, {"running": True, "progress": [1, 42]})
    p._on_readable(fake.client_sock.fileno(), GLib.IOCondition.IN)
    assert running == [True]
    assert progress == [(1, 42)]
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_remote_pty_proxy.py -k "write or resize or status or exit" -v`
Expected: FAIL — `AttributeError: 'RemotePtyProxy' object has no attribute 'write'`

- [ ] **Step 3: Add `write` and `resize`** (STATUS/EXIT dispatch already exists from Task 2.2)

```python
# src/jfterm/remote_pty_proxy.py  (add methods to the class)

    def write(self, data: bytes) -> None:
        self._send(mp.encode_frame(mp.FrameType.INPUT, data))

    def resize(self, rows: int, cols: int) -> None:
        if rows <= 0 or cols <= 0:
            return
        self._send(mp.encode_json_frame(mp.FrameType.RESIZE, {"cols": cols, "rows": rows}))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_remote_pty_proxy.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/remote_pty_proxy.py tests/test_remote_pty_proxy.py
git commit -m "feat(muxer): RemotePtyProxy write/resize and STATUS/EXIT dispatch"
```

### Task 2.4: `close(signal, grace_ms)` vs `detach()`

**Files:**
- Modify: `src/jfterm/remote_pty_proxy.py`
- Test: `tests/test_remote_pty_proxy.py`

**Why two methods:** `close()` sends a `CLOSE` frame (kill the shell) then tears down; `detach()` tears down *without* `CLOSE`, leaving the daemon session alive. Both are idempotent. Window-close calls `detach()` on every session; tab-close calls `close()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_remote_pty_proxy.py  (append)
def test_close_sends_close_frame_with_signal_and_grace():
    fake = FakeMuxer()
    p = _proxy(fake)
    p.close(signal="SIGTERM", grace_ms=1500)
    frames = fake.read_json_frames()
    assert frames == [(mp.FrameType.CLOSE, {"signal": "SIGTERM", "grace_ms": 1500})]
    fake.close()


def test_close_default_is_sighup_no_grace():
    fake = FakeMuxer()
    p = _proxy(fake)
    p.close()
    assert fake.read_json_frames() == [
        (mp.FrameType.CLOSE, {"signal": "SIGHUP", "grace_ms": 0})
    ]
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_remote_pty_proxy.py -k "close or detach" -v`
Expected: FAIL — `AttributeError: 'RemotePtyProxy' object has no attribute 'close'`

- [ ] **Step 3: Add `close` and `detach`**

```python
# src/jfterm/remote_pty_proxy.py  (add methods to the class)

    def close(self, signal: str = "SIGHUP", grace_ms: int = 0) -> None:
        """Kill the daemon session, then tear down. Idempotent."""
        if self._closed:
            return
        self._send(
            mp.encode_json_frame(
                mp.FrameType.CLOSE, {"signal": signal, "grace_ms": grace_ms}
            )
        )
        self._detach_cleanup()

    def detach(self) -> None:
        """Tear down the socket without CLOSE; leaves the daemon session alive."""
        self._detach_cleanup()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_remote_pty_proxy.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/remote_pty_proxy.py tests/test_remote_pty_proxy.py
git commit -m "feat(muxer): RemotePtyProxy close(signal,grace) vs detach()"
```

---

## Phase 3 — `MuxerClient`: control connection + LIST + spawn

### Task 3.1: Socket path resolution

**Files:**
- Create: `src/jfterm/muxer_client.py`
- Test: `tests/test_muxer_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_muxer_client.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_muxer_client.py -k socket_path -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jfterm.muxer_client'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/jfterm/muxer_client.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_muxer_client.py -k socket_path -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/muxer_client.py tests/test_muxer_client.py
git commit -m "feat(muxer): socket_path resolution"
```

### Task 3.2: HELLO handshake and LIST over a connected control socket

**Files:**
- Modify: `src/jfterm/muxer_client.py`
- Test: `tests/test_muxer_client.py`

**Design note:** The handshake/LIST exchange is synchronous request/response and is tested against a fake control server running in a thread on a temp UDS path.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_muxer_client.py  (append)
import json
import threading

from jfterm import muxer_proto as mp
from jfterm.muxer_client import hello, list_sessions


def _serve_once(sock_path, responder):
    srv = mp_unix_server(sock_path)
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

    t = threading.Thread(target=_serve_once, args=(sock_path, responder), daemon=True)
    t.start()
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

    t = threading.Thread(target=_serve_once, args=(sock_path, responder), daemon=True)
    t.start()
    import socket as _s

    c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
    c.connect(str(sock_path))
    assert list_sessions(c) == sessions
    c.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_muxer_client.py -k "hello or list_sessions" -v`
Expected: FAIL — `ImportError: cannot import name 'hello'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/jfterm/muxer_client.py  (append)

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_muxer_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/muxer_client.py tests/test_muxer_client.py
git commit -m "feat(muxer): HELLO handshake and LIST over control socket"
```

### Task 3.3: `MuxerClient` connect-or-spawn + session-socket factory

**Files:**
- Modify: `src/jfterm/muxer_client.py`
- Test: `tests/test_muxer_client.py`

**Design note:** `connect_session()` just returns a connected blocking socket; `RemotePtyProxy` owns the ATTACH_OR_OPEN binding. Daemon self-spawn uses `start_new_session=True` (setsid) and retries connect with a short backoff. **[GATED: real jftermd]** — the spawn-then-connect path can only be verified end-to-end once the binary exists; here we implement it and unit-test only the connect-to-existing-socket path.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_muxer_client.py  (append)
import threading

from jfterm.muxer_client import MuxerClient


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_muxer_client.py -k connect_session -v`
Expected: FAIL — `ImportError: cannot import name 'MuxerClient'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/jfterm/muxer_client.py  (append)
import subprocess
import time


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
```

(Add `import contextlib` to the top of `muxer_client.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_muxer_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/muxer_client.py tests/test_muxer_client.py
git commit -m "feat(muxer): MuxerClient connect-or-spawn and session socket factory"
```

---

## Phase 4 — `session_id` runtime field on tab models

### Task 4.1: Add `session_id` to `TerminalTab` and `LinkedTab`

**Files:**
- Modify: `src/jfterm/models.py:46` (TerminalTab), `src/jfterm/models.py:91` (LinkedTab)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py  (append)
import uuid

from jfterm.models import LinkedTab, TerminalTab


def test_terminal_tab_has_unique_session_id():
    a = TerminalTab()
    b = TerminalTab()
    assert a.session_id != b.session_id
    # Valid uuid4 hex.
    uuid.UUID(hex=a.session_id)


def test_linked_tab_has_session_id():
    t = LinkedTab()
    uuid.UUID(hex=t.session_id)


def test_session_id_is_distinct_from_structural_id():
    t = TerminalTab()
    assert t.session_id != t.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -k session_id -v`
Expected: FAIL — `AttributeError: 'TerminalTab' object has no attribute 'session_id'`

- [ ] **Step 3: Implement — add the field to both dataclasses**

In `src/jfterm/models.py`, in `TerminalTab` (after the `terminal: Any = None` line at 48) add:

```python
    # Daemon session this tab currently points at. Distinct from `id` (the
    # tab's structural identity) so restart can swap shells without a key
    # collision. Runtime-only in v1 (rediscovered from the daemon's LIST on
    # relaunch); not persisted to disk yet.
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
```

Add the identical field to `LinkedTab` (after `terminal: Any = None` at 101).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/models.py tests/test_models.py
git commit -m "feat(muxer): session_id runtime field on terminal-bearing tabs"
```

---

## Phase 5 — `JFTermTerminal` uses `RemotePtyProxy`

### Task 5.1: Constructor takes `session_id` + `MuxerClient`; build `RemotePtyProxy`

**Files:**
- Modify: `src/jfterm/terminal.py:37-72` (constructor), `:15` (import), `:219-233` (delete poll)

**Design note:** `JFTermTerminal` no longer spawns a PTY. It is given a `MuxerClient` and a `session_id`, connects a session socket, and constructs `RemotePtyProxy`. `adopt=True` means "this came from LIST" → do not send the launch command. The `tcgetpgrp` poll and `_osc133_seen` are deleted (status is now daemon-pushed via STATUS).

- [ ] **Step 1: Replace the import** at `terminal.py:15`

```python
from jfterm.remote_pty_proxy import RemotePtyProxy  # noqa: E402
```

(Remove `from jfterm.pty_proxy import PtyProxy`.)

- [ ] **Step 2: Rewrite the constructor signature and proxy creation** (`terminal.py:37-66`)

Replace the `__init__` parameter list and the proxy-construction block with:

```python
    def __init__(
        self,
        muxer: "MuxerClient",
        session_id: str,
        *,
        cwd: str | None = None,
        argv: list[str] | None = None,
        send_after_spawn: str | None = None,
        adopt: bool = False,
        appearance: AppSettings | None = None,
    ) -> None:
        super().__init__()
        self._initial_cwd = cwd or str(Path.home())
        self.session_id = session_id

        self.connect("current-directory-uri-changed", self._on_cwd_uri_changed)
        self.connect("window-title-changed", self._on_title_changed)
        self.connect("commit", self._on_commit)
        self.connect("char-size-changed", self._on_char_size_changed)

        shell = os.environ.get("SHELL") or "/bin/bash"
        resolved_argv = argv if argv is not None else [shell, "-l"]
        sock = muxer.connect_session()
        cols = self.get_column_count() or 80
        rows = self.get_row_count() or 24
        self._proxy = RemotePtyProxy(
            sock,
            session_id=session_id,
            cwd=self._initial_cwd,
            argv=resolved_argv,
            cols=cols,
            rows=rows,
            send_after_open=None if adopt else send_after_spawn,
        )
        self._proxy.connect("data-ready", self._on_proxy_data)
        self._proxy.connect("progress-changed", self._on_proxy_progress)
        self._proxy.connect("running-changed", self._on_proxy_running_changed)
        self._proxy.connect("child-exited", self._on_proxy_child_exited)

        self._last_size: tuple[int, int] = (0, 0)
        self._install_context_menu()
        if appearance is not None:
            self.apply_appearance(appearance)
```

Add to the imports at the top of `terminal.py` (under TYPE_CHECKING is fine):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jfterm.muxer_client import MuxerClient
```

- [ ] **Step 3: Delete the poll** — remove `_poll_tcgetpgrp` (`terminal.py:219-233`), the `self._poll_source` line in `__init__`, and the `_poll_source` cleanup in `do_dispose` (`terminal.py:192-194`). In `_on_proxy_running_changed` (`terminal.py:206-208`) drop the `self._osc133_seen = True` line; keep the `self.emit("running-changed", running)`.

- [ ] **Step 4: Run the full suite to confirm nothing import-breaks**

Run: `uv run pytest tests/test_remote_pty_proxy.py tests/test_models.py -v`
Expected: PASS (terminal.py imports cleanly; window.py is updated in Phase 6)

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/terminal.py
git commit -m "feat(muxer): JFTermTerminal drives RemotePtyProxy, drops tcgetpgrp poll"
```

---

## Phase 6 — `window.py` integration

### Task 6.1: Create the `MuxerClient` and adopt live sessions into Unsorted on launch

**Files:**
- Modify: `src/jfterm/window.py:50-52` (after `load_projects`), and add `_adopt_sessions` + `_adopt_session` helpers near `_spawn_tab` (`window.py:201`).

**Design note:** After loading projects, connect to the muxer, LIST, and create one `TerminalTab` per live session in `ws.unsorted`, each attached (adopt=True). If the muxer is unreachable, log and continue with an empty session set (the app still works for spawning new tabs).

- [ ] **Step 1: Write the failing test** (pure model-level adoption, no GTK display)

```python
# tests/test_window.py  (append)
from types import SimpleNamespace

from jfterm.models import Workspace
from jfterm.window import JFTermWindow


def test_adopt_session_appends_terminal_tab_to_unsorted():
    ws = Workspace()
    created = []

    def fake_materialize(self, info):
        tab = SimpleNamespace(session_id=info["session_id"], title=info.get("argv", ["?"])[0])
        ws.unsorted.tabs.append(tab)
        created.append(tab)
        return tab

    fake_self = SimpleNamespace(
        ws=ws,
        _materialize_adopted_tab=fake_materialize.__get__(None),
    )
    sessions = [
        {"session_id": "s1", "argv": ["bash"], "cwd": "/tmp"},
        {"session_id": "s2", "argv": ["vim"], "cwd": "/home"},
    ]
    JFTermWindow._adopt_sessions(fake_self, sessions)
    assert [t.session_id for t in ws.unsorted.tabs] == ["s1", "s2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_window.py -k adopt_session -v`
Expected: FAIL — `AttributeError: type object 'JFTermWindow' has no attribute '_adopt_sessions'`

- [ ] **Step 3: Implement adoption**

In `window.py __init__`, after `self._project_saver = ProjectSaver(...)` (line 52), add:

```python
        from jfterm.muxer_client import MuxerClient

        self._muxer = MuxerClient()
        self._adopt_live_sessions()
```

Add the import `import logging` at the top if not present, and a module logger `logger = logging.getLogger(__name__)`.

Add these methods to `JFTermWindow` (near `_spawn_tab`):

```python
    def _adopt_live_sessions(self) -> None:
        try:
            sessions = self._muxer.list_sessions()
        except (ConnectionError, OSError) as exc:
            logger.warning("muxer unavailable at launch: %s", exc)
            return
        self._adopt_sessions(sessions)

    def _adopt_sessions(self, sessions: list[dict]) -> None:
        for info in sessions:
            self._materialize_adopted_tab(info)

    def _materialize_adopted_tab(self, info: dict) -> "TerminalTab":
        cwd = info.get("cwd") or str(Path.home())
        argv = info.get("argv") or []
        terminal = JFTermTerminal(
            self._muxer,
            info["session_id"],
            cwd=cwd,
            argv=argv,
            adopt=True,
            appearance=self._settings,
        )
        terminal.set_vexpand(True)
        terminal.set_hexpand(True)
        tab = TerminalTab(
            title=" ".join(argv) or "(recovered)",
            terminal=terminal,
            session_id=info["session_id"],
        )
        self._wire_terminal(tab, terminal)
        self.terminal_stack.add_child(terminal)
        self.ws.unsorted.add_tab(tab)
        self.sidebar.refresh()
        return tab
```

(Add `from pathlib import Path` to window.py imports if absent.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_window.py -k adopt_session -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/window.py tests/test_window.py
git commit -m "feat(muxer): adopt live sessions into Unsorted on launch"
```

### Task 6.2: Update `_spawn_tab` to mint a session and pass the muxer

**Files:**
- Modify: `src/jfterm/window.py:201-226` (`_spawn_tab`)

- [ ] **Step 1: Update `_spawn_tab`** so the terminal is created with a fresh `session_id` and the muxer:

```python
    def _spawn_tab(
        self,
        group: Group,
        *,
        command: str | None = None,
        focus: bool = True,
    ) -> TerminalTab:
        cwd = group.directory if isinstance(group, Project) else None
        tab = TerminalTab(
            title=command or "(starting…)",
            launched_command=command,
        )
        terminal = JFTermTerminal(
            self._muxer,
            tab.session_id,
            cwd=cwd,
            send_after_spawn=command,
            appearance=self._settings,
        )
        terminal.set_vexpand(True)
        terminal.set_hexpand(True)
        tab.terminal = terminal
        self._wire_terminal(tab, terminal)
        self.terminal_stack.add_child(terminal)
        group.add_tab(tab)
        if focus:
            self._current_group = group
            self.terminal_stack.set_visible_child(terminal)
            self.sidebar.set_active_tab(tab)
            terminal.grab_focus()
        self.sidebar.refresh()
        return tab
```

- [ ] **Step 2: Apply the same pattern** to `_spawn_web_tab`'s sibling terminal spawns — specifically `_spawn_linked_tab` (`window.py:314-393`): create the `LinkedTab` first, then build its `JFTermTerminal(self._muxer, tab.session_id, cwd=…, argv=…, send_after_spawn=…)`. Match the existing argument intent (the linked terminal's command is the wrapped flash command).

- [ ] **Step 3: Run the suite** (model-level tests still pass; GUI spawn is covered by manual acceptance)

Run: `uv run pytest tests/ -q`
Expected: PASS (no import errors; existing window tests green)

- [ ] **Step 4: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(muxer): spawn tabs through the muxer with a fresh session_id"
```

### Task 6.3: Rewire restart to `CLOSE{SIGTERM,1500}` + new `session_id`

**Files:**
- Modify: `src/jfterm/window.py:546-610` (`_on_restart_tab`), `:611-695` (`_restart_linked_tab`)

**Design note:** The old client-side `os.kill(old_pid, SIGTERM)` + 1.5s `_force_kill` block is deleted — the daemon owns escalation. Restart now: `old_terminal._proxy.close(signal="SIGTERM", grace_ms=1500)`, mint a new `session_id`, build a fresh terminal bound to it.

- [ ] **Step 1: Replace the kill block in `_on_restart_tab`**

Delete the `old_pid` capture, the `os.kill(...SIGTERM)` call, and the entire `_force_kill` + `GLib.timeout_add(1500, _force_kill)` block (`window.py:561-580`). Replace the old-terminal teardown (`window.py:582-584`) with:

```python
        old_terminal = tab.terminal
        if old_terminal is not None:
            # Daemon owns SIGTERM->grace->SIGKILL escalation; client just asks.
            old_terminal._proxy.close(signal="SIGTERM", grace_ms=1500)
            self.terminal_stack.remove(old_terminal)

        tab.session_id = uuid.uuid4().hex
        new_terminal = JFTermTerminal(
            self._muxer,
            tab.session_id,
            cwd=cwd,
            send_after_spawn=command,
            appearance=self._settings,
        )
```

(Add `import uuid` to window.py if absent. Remove the now-unused `import signal` / `os.kill` usages only if no other code in window.py needs them — verify with `grep -n "os.kill\|signal\." src/jfterm/window.py` first.)

Delete the now-obsolete `tab.shell_pid = None` / `tab.pty_fd = None` lines (`window.py:592-593`) — those fields are vestigial under the muxer.

- [ ] **Step 2: Apply the same replacement to `_restart_linked_tab`** (`window.py:611-695`): swap the kill/`_force_kill` block for `old_terminal._proxy.close(signal="SIGTERM", grace_ms=1500)`, mint `tab.session_id = uuid.uuid4().hex`, and build the new terminal through the muxer.

- [ ] **Step 3: Update the existing restart test** — `test_window.py` has a restart-related test (`test_on_close_tab_is_noop_when_tab_is_restarting`). Run it to confirm the `is_restarting` guard path is unaffected:

Run: `uv run pytest tests/test_window.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(muxer): restart via CLOSE{SIGTERM,1500} and a new session_id"
```

### Task 6.4: Tab close sends `CLOSE`; window close detaches all sessions

**Files:**
- Modify: `src/jfterm/window.py:507-545` (`_on_close_tab`), `:1301-1310` (`_on_close_request`)

**Design note:** Per-tab close kills that shell (`CLOSE{SIGHUP,0}`); the eager `_proxy.close()` already does this once `close()` defaults to SIGHUP. Window close must **detach** every session so shells survive — call `detach()` on each proxy *before* GTK dispose runs (dispose calls `_proxy.close()`, which becomes a no-op once detached).

- [ ] **Step 1: Confirm `_on_close_tab`'s eager close is correct** — at `window.py:520-522`, `terminal._proxy.close()` now defaults to `CLOSE{SIGHUP,0}`. No change needed beyond verifying the call site still reads `terminal._proxy.close()`.

- [ ] **Step 2: Add detach-on-window-close** — in `_on_close_request` (`window.py:1301-1310`), before `return False`, detach every terminal-bearing tab's proxy and close the control connection:

```python
    def _on_close_request(self, _win) -> bool:
        from gi.repository import GLib

        if self._window_save_source is not None:
            GLib.source_remove(self._window_save_source)
            self._window_save_source = None
        self._persist_window_geometry()
        # Detach (do NOT close) every session so shells outlive the window.
        for group in self.ws.all_groups():
            for tab in group.tabs:
                terminal = getattr(tab, "terminal", None)
                if terminal is not None and terminal._proxy is not None:
                    terminal._proxy.detach()
        self._muxer.close()
        self._project_saver.flush(timeout=5.0)
        return False
```

- [ ] **Step 3: Write a test** that detach-on-close visits every session proxy:

```python
# tests/test_window.py  (append)
def test_close_request_detaches_all_sessions():
    ws = Workspace()
    p = ws.add_project(name="A", directory="/tmp/a")
    detached = []

    class FakeProxy:
        def detach(self):
            detached.append(self)

    class FakeTerm:
        def __init__(self):
            self._proxy = FakeProxy()

    t1 = SimpleNamespace(terminal=FakeTerm())
    t2 = SimpleNamespace(terminal=FakeTerm())
    p.tabs.extend([t1, t2])

    fake_self = SimpleNamespace(
        ws=ws,
        _window_save_source=None,
        _persist_window_geometry=lambda: None,
        _muxer=SimpleNamespace(close=lambda: None),
        _project_saver=SimpleNamespace(flush=lambda timeout=0: None),
    )
    result = JFTermWindow._on_close_request(fake_self, None)
    assert result is False
    assert len(detached) == 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_window.py -k "close_request_detaches" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/window.py tests/test_window.py
git commit -m "feat(muxer): detach sessions on window close, CLOSE on tab close"
```

---

## Phase 7 — Retire the in-process `PtyProxy` and `OscScanner`

### Task 7.1: Delete dead modules and their tests

**Files:**
- Delete: `src/jfterm/pty_proxy.py`, `src/jfterm/osc_scanner.py`, `tests/test_osc_scanner.py`

- [ ] **Step 1: Confirm nothing still imports them**

Run: `grep -rn "pty_proxy\|osc_scanner\|OscScanner\|PtyProxy" src/ tests/`
Expected: only matches inside the files about to be deleted (and this plan). If `window.py`/`terminal.py` still reference them, fix those references first.

- [ ] **Step 2: Delete the files**

```bash
git rm src/jfterm/pty_proxy.py src/jfterm/osc_scanner.py tests/test_osc_scanner.py
```

- [ ] **Step 3: Run the full check suite**

Run: `just check`
Expected: ruff + format + pyright + pytest all green. (Per project convention, `just check` is the gate before pushing.)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(muxer): retire in-process PtyProxy and OscScanner"
```

---

## Phase 8 — Integration & manual acceptance  **[GATED: real jftermd]**

These steps require the `jftermd` binary on `PATH`. They cannot pass until the muxer repo ships a build. Do them once it does.

### Task 8.1: End-to-end smoke against the real daemon

- [ ] **Step 1:** Build/install `jftermd` from the `jfterm-muxer` repo and confirm it is on `PATH`: `which jftermd`.
- [ ] **Step 2:** Launch JFTerm (`just run`), open a plain tab, run `echo hello`. Expected: output renders; status dot reflects running/idle.
- [ ] **Step 3:** Run a long-lived TUI (`vim` or `htop`), then **close the JFTerm window**. Expected: window closes, `jftermd` still running (`pgrep jftermd`), shell still alive.
- [ ] **Step 4:** Relaunch JFTerm. Expected: the session reappears as a tab in **Unsorted**, `vim`/`htop` repaints cleanly (alt-screen redraw via the attach SIGWINCH), scrollback intact.
- [ ] **Step 5:** Verify replay-safety: a program that printed to the clipboard (OSC 52) before detach does **not** re-clobber the clipboard on reattach; the bell does not machine-gun on replay.
- [ ] **Step 6:** Restart a command tab via the ↻ control. Expected: old shell dies (SIGTERM, then SIGKILL after ~1.5s if it ignores it), a fresh shell opens and re-runs the command; no key collision, tab stays in place.
- [ ] **Step 7:** Close a single tab via ✕. Expected: that shell is killed (`CLOSE{SIGHUP,0}`); other sessions unaffected.

### Task 8.2: Record any protocol divergence

- [ ] **Step 1:** If the real daemon's frame shapes differ from `muxer_proto.py`, reconcile: update `muxer_proto.py` + `tests/fake_muxer.py` to match the muxer repo's `PROTOCOL.md`, bump `PROTO_VERSION` if the wire format changed, and re-run Phases 1–7 tests.
- [ ] **Step 2:** Commit any reconciliation as `fix(muxer): align client protocol with jftermd PROTOCOL.md vN`.

---

## Self-Review

**Spec coverage (v1 scope):**
- `RemotePtyProxy` drop-in with identical signals → Phase 2. ✓
- TLV protocol (HELLO/LIST/ATTACH_OR_OPEN/INPUT/RESIZE/CLOSE/DATA/STATUS/EXIT) → Phases 1–3. ✓
- `CLOSE{signal, grace_ms}` + daemon-owned escalation (client side) → Tasks 2.4, 6.3. ✓
- Launch reconciliation v1 (adopt all into Unsorted) → Task 6.1. ✓
- `session_id` as runtime per-tab pointer, distinct from `Tab.id` → Phase 4; restart mints a new one → Task 6.3. ✓
- Exit policy v1 (window close detaches, tab close kills) → Task 6.4. ✓
- Daemon self-spawn (setsid + retry; daemon owns flock/double-fork) → Task 3.3 (spawn path **[GATED]**). ✓
- `COLORTERM`/`TERM`, ring/sanitization, tcgetpgrp fallback, replay ordering → **daemon-side**, in the spec's "Muxer-side responsibilities"; out of scope for this client plan. ✓ (intentional)

**Deferred (v2, explicitly out of scope):** tab persistence to disk; reattach into original project/group/position; the explicit "Quit, killing all terminals" command.

**Placeholder scan:** No "TBD"/"handle errors"/"similar to". Steps gated on the real daemon are marked **[GATED: real jftermd]** with concrete manual actions, not vague stubs.

**Type/name consistency:** `RemotePtyProxy.__init__(sock, *, session_id, cwd, argv, cols, rows, want_chunks=None, send_after_open=None)`; `close(signal="SIGHUP", grace_ms=0)`; `detach()`; `resize(rows, cols)`; `write(bytes)`. `MuxerClient.list_sessions()/connect_session()/control()/close()`. `JFTermTerminal(muxer, session_id, *, cwd, argv, send_after_spawn, adopt, appearance)`. `FrameType` names match the spec's protocol table. These are used consistently across Phases 2, 3, 5, 6.

**Known caveat:** `terminal.py`'s `JFTermTerminal` constructs `RemotePtyProxy` at `__init__` time, which connects a socket — under tests that instantiate a real `JFTermTerminal` (rare; most tests are model-level) a running daemon or a fake would be required. The plan keeps `JFTermTerminal` construction out of unit tests (window tests operate on the model layer via `SimpleNamespace`), matching the existing test style.
