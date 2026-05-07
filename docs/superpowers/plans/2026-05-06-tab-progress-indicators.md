# Tab Progress Indicators (OSC 9;4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a thin progress bar pinned to the bottom edge of each tab's title button, driven by `OSC 9;4` sequences emitted by tools running in the shell.

**Architecture:** A new in-process pty proxy (`PtyProxy`) replaces VTE's `spawn_async`. The shell runs on a pty we own; output flows through an `OscScanner` that strips `OSC 9;4` sequences and `feed()`s the rest into VTE; input flows from VTE's `commit` signal back to the pty master. Progress events are surfaced via a new `progress-changed(int, int)` signal on `JFTermTerminal`, then rendered by a `TabProgressBar` widget overlaid on each sidebar tab row's title button.

**Tech Stack:** Python 3, GTK 4 / libadwaita, VTE 3.91 (lib 0.76), GLib (`unix_fd_add`, `child_watch_add`), `pty` / `os` / `fcntl` / `termios` from the stdlib, pytest, ruff, pyright.

**Spec:** [docs/superpowers/specs/2026-05-06-tab-progress-indicators-design.md](../specs/2026-05-06-tab-progress-indicators-design.md)

---

## File Structure

**New files:**
- `src/jfterm/osc_scanner.py` — pure-Python OSC 9;4 scanner. No GTK imports. Single class `OscScanner` + `ProgressEvent` dataclass.
- `src/jfterm/pty_proxy.py` — manages the shell-side pty, the child process, the GLib watcher, and bridges OSC events to GObject signals. One class `PtyProxy(GObject.Object)`.
- `src/jfterm/progress_bar.py` — `TabProgressBar(Gtk.Widget)`. Renders the bar via `snapshot()`. Owns its own `_state`/`_value` and animation timer.
- `tests/test_osc_scanner.py` — pytest unit tests, no GTK.
- `tests/test_progress_bar.py` — light unit tests for the widget's state transitions (visibility toggling, animation timer start/stop). Skip if GTK not importable, like `test_window.py`.

**Modified files:**
- `src/jfterm/terminal.py` — drop `spawn_async`; construct a `PtyProxy`; wire `commit`, `char-size-changed`, and progress signals.
- `src/jfterm/sidebar.py` — wrap title button in `Gtk.Overlay`, add `TabProgressBar`, add CSS, stash `tab._progress_bar`.
- `src/jfterm/window.py` — in `_wire_terminal`, handle `progress-changed`; in the `running-changed(False)` path, also clear progress.

**Unchanged:** `models.py` (per coordination — another agent is refactoring it).

---

## Task 1: OscScanner — basic structure and pass-through

**Files:**
- Create: `src/jfterm/osc_scanner.py`
- Create: `tests/test_osc_scanner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_osc_scanner.py`:

```python
from jfterm.osc_scanner import OscScanner, ProgressEvent


def test_passthrough_plain_text():
    scanner = OscScanner()
    out, events = scanner.feed(b"hello world")
    assert out == b"hello world"
    assert events == []


def test_passthrough_other_osc_unchanged():
    scanner = OscScanner()
    # OSC 7 (cwd) should NOT be touched.
    data = b"prefix\x1b]7;file:///tmp\x1b\\suffix"
    out, events = scanner.feed(data)
    assert out == data
    assert events == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_osc_scanner.py -v`
Expected: collection FAIL with `ModuleNotFoundError: No module named 'jfterm.osc_scanner'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/jfterm/osc_scanner.py`:

```python
from dataclasses import dataclass


_MAX_CARRY = 256
_OSC_INTRO = b"\x1b]"
_ST = b"\x1b\\"
_BEL = b"\x07"


@dataclass(frozen=True)
class ProgressEvent:
    state: int
    value: int


class OscScanner:
    """Scan a byte stream for OSC 9;4 progress sequences.

    All other bytes (plain text, other OSCs, CSI, etc.) are passed through
    unchanged. The hot path is bytes.find() — no per-byte Python loop.
    """

    def __init__(self) -> None:
        self._carry = b""

    def feed(self, chunk: bytes) -> tuple[bytes, list[ProgressEvent]]:
        data = self._carry + chunk
        self._carry = b""
        out = bytearray()
        events: list[ProgressEvent] = []

        i = 0
        n = len(data)
        while i < n:
            j = data.find(_OSC_INTRO, i)
            if j == -1:
                out += data[i:]
                break
            # Forward bytes before the OSC introducer.
            out += data[i:j]
            # Find the terminator (ST or BEL) starting after the introducer.
            term_st = data.find(_ST, j + 2)
            term_bel = data.find(_BEL, j + 2)
            term, term_len = _earliest(term_st, len(_ST), term_bel, len(_BEL))
            if term == -1:
                # No terminator yet. If we've already accumulated more than
                # the cap without finding one, this is malformed: flush the
                # opening bytes and continue past them.
                if n - j > _MAX_CARRY:
                    out += data[j : j + 2]
                    i = j + 2
                    continue
                # Otherwise stash the partial sequence as carry and stop.
                self._carry = data[j:]
                break
            body = data[j + 2 : term]
            ev = _try_parse_progress(body)
            if ev is not None:
                events.append(ev)
                # Drop the entire OSC 9;4 sequence (introducer + body + term).
            else:
                # Pass other OSCs through unchanged.
                out += data[j : term + term_len]
            i = term + term_len

        return bytes(out), events


def _earliest(a: int, a_len: int, b: int, b_len: int) -> tuple[int, int]:
    if a == -1:
        return (b, b_len) if b != -1 else (-1, 0)
    if b == -1:
        return (a, a_len)
    if a < b:
        return (a, a_len)
    return (b, b_len)


def _try_parse_progress(body: bytes) -> ProgressEvent | None:
    # Body looks like: 9;4;<state>[;<value>]
    if not body.startswith(b"9;4"):
        return None
    parts = body.split(b";")
    # parts[0] == b"9", parts[1] == b"4"
    if len(parts) < 3:
        return None
    try:
        state = int(parts[2])
    except ValueError:
        return None
    value = 0
    if len(parts) >= 4 and parts[3]:
        try:
            value = int(parts[3])
        except ValueError:
            value = 0
    return ProgressEvent(state=state, value=value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_osc_scanner.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/osc_scanner.py tests/test_osc_scanner.py
git commit -m "feat(osc): add OscScanner skeleton with passthrough"
```

---

## Task 2: OscScanner — recognize OSC 9;4 sequences

**Files:**
- Modify: `tests/test_osc_scanner.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_osc_scanner.py`:

```python
def test_parses_state_1_with_value_st_terminator():
    scanner = OscScanner()
    out, events = scanner.feed(b"before\x1b]9;4;1;42\x1b\\after")
    assert out == b"beforeafter"
    assert events == [ProgressEvent(state=1, value=42)]


def test_parses_state_1_with_value_bel_terminator():
    scanner = OscScanner()
    out, events = scanner.feed(b"\x1b]9;4;1;75\x07")
    assert out == b""
    assert events == [ProgressEvent(state=1, value=75)]


def test_parses_state_0_clear():
    scanner = OscScanner()
    out, events = scanner.feed(b"\x1b]9;4;0\x1b\\")
    assert out == b""
    assert events == [ProgressEvent(state=0, value=0)]


def test_parses_state_2_error_no_value():
    scanner = OscScanner()
    out, events = scanner.feed(b"\x1b]9;4;2;0\x1b\\")
    assert out == b""
    assert events == [ProgressEvent(state=2, value=0)]


def test_parses_state_3_indeterminate():
    scanner = OscScanner()
    out, events = scanner.feed(b"\x1b]9;4;3\x1b\\")
    assert out == b""
    assert events == [ProgressEvent(state=3, value=0)]


def test_parses_state_4_paused():
    scanner = OscScanner()
    out, events = scanner.feed(b"\x1b]9;4;4;50\x1b\\")
    assert out == b""
    assert events == [ProgressEvent(state=4, value=50)]


def test_multiple_sequences_in_one_chunk():
    scanner = OscScanner()
    out, events = scanner.feed(
        b"a\x1b]9;4;1;10\x1b\\b\x1b]9;4;1;90\x1b\\c"
    )
    assert out == b"abc"
    assert events == [
        ProgressEvent(state=1, value=10),
        ProgressEvent(state=1, value=90),
    ]


def test_unknown_osc_passes_through_unchanged():
    scanner = OscScanner()
    raw = b"\x1b]133;A\x1b\\"
    out, events = scanner.feed(raw)
    assert out == raw
    assert events == []
```

- [ ] **Step 2: Run tests to verify behavior**

Run: `uv run pytest tests/test_osc_scanner.py -v`
Expected: all eight new tests PASS (the implementation from Task 1 already handles these).

- [ ] **Step 3: Commit**

```bash
git add tests/test_osc_scanner.py
git commit -m "test(osc): cover all OSC 9;4 states and terminators"
```

---

## Task 3: OscScanner — split sequences across reads

**Files:**
- Modify: `tests/test_osc_scanner.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_osc_scanner.py`:

```python
def test_split_at_every_byte_boundary():
    full = b"x\x1b]9;4;1;42\x1b\\y"
    for split in range(1, len(full)):
        scanner = OscScanner()
        out1, ev1 = scanner.feed(full[:split])
        out2, ev2 = scanner.feed(full[split:])
        assert out1 + out2 == b"xy", f"split={split}"
        assert ev1 + ev2 == [ProgressEvent(state=1, value=42)], f"split={split}"


def test_split_between_st_bytes():
    # Boundary lands exactly between \x1b and \\ of the ST terminator.
    scanner = OscScanner()
    out1, ev1 = scanner.feed(b"\x1b]9;4;1;5\x1b")
    out2, ev2 = scanner.feed(b"\\tail")
    assert out1 + out2 == b"tail"
    assert ev1 + ev2 == [ProgressEvent(state=1, value=5)]


def test_carry_preserved_across_no_op_feed():
    scanner = OscScanner()
    out1, ev1 = scanner.feed(b"\x1b]9;4;1;5")
    assert out1 == b""
    assert ev1 == []
    out2, ev2 = scanner.feed(b"")
    assert out2 == b""
    assert ev2 == []
    out3, ev3 = scanner.feed(b"\x1b\\done")
    assert out3 == b"done"
    assert ev3 == [ProgressEvent(state=1, value=5)]
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_osc_scanner.py -v`
Expected: all PASS. (The Task 1 implementation already carries partial sequences.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_osc_scanner.py
git commit -m "test(osc): cover sequences split across feed boundaries"
```

---

## Task 4: OscScanner — bail out on runaway sequences

**Files:**
- Modify: `tests/test_osc_scanner.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_osc_scanner.py`:

```python
def test_runaway_sequence_flushes_introducer_and_recovers():
    scanner = OscScanner()
    # 300 bytes of garbage after \x1b] with no terminator.
    junk = b"X" * 300
    out1, ev1 = scanner.feed(b"\x1b]" + junk)
    # The introducer should be flushed as data; junk continues being scanned.
    assert b"\x1b]" in out1
    assert ev1 == []
    # Now feed a proper sequence; carry must be empty so it parses cleanly.
    out2, ev2 = scanner.feed(b"\x1b]9;4;1;5\x1b\\")
    assert ev2 == [ProgressEvent(state=1, value=5)]
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_osc_scanner.py::test_runaway_sequence_flushes_introducer_and_recovers -v`
Expected: PASS. (Bailout logic already exists in Task 1.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_osc_scanner.py
git commit -m "test(osc): cover malformed sequence recovery"
```

---

## Task 5: PtyProxy — spawn shell, expose pty fd, child-exited signal

**Files:**
- Create: `src/jfterm/pty_proxy.py`

- [ ] **Step 1: Write the implementation**

Create `src/jfterm/pty_proxy.py`:

```python
import fcntl
import os
import pty
import struct
import termios

import gi

gi.require_version("Vte", "3.91")
from gi.repository import GLib, GObject  # noqa: E402

from jfterm.osc_scanner import OscScanner, ProgressEvent


class PtyProxy(GObject.Object):
    """Owns a pty pair and a shell child, sniffs OSC 9;4 from the output.

    Signals:
      data-ready(bytes)         clean output bytes to feed into VTE
      progress-changed(int,int) parsed OSC 9;4 (state, value)
      child-exited(int)         shell exit status (mirrors VTE's signal)
    """

    __gsignals__ = {
        "data-ready": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "progress-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        "child-exited": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    READ_CHUNK = 65536

    def __init__(self, cwd: str, argv: list[str]) -> None:
        super().__init__()
        self._scanner = OscScanner()
        self._master_fd: int | None = None
        self._child_pid: int | None = None
        self._fd_watch: int | None = None
        self._child_watch: int | None = None
        self._spawn(cwd, argv)

    @property
    def shell_pid(self) -> int | None:
        return self._child_pid

    @property
    def pty_fd(self) -> int | None:
        return self._master_fd

    def _spawn(self, cwd: str, argv: list[str]) -> None:
        pid, master_fd = pty.fork()
        if pid == 0:
            # Child: chdir, exec the shell. If exec fails, _exit so we don't
            # run any parent-side teardown.
            try:
                os.chdir(cwd)
            except OSError:
                pass
            try:
                os.execvp(argv[0], argv)
            except OSError:
                os._exit(127)
        # Parent.
        self._master_fd = master_fd
        self._child_pid = pid
        # Non-blocking reads so the GLib watcher can drain in one call.
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self._fd_watch = GLib.unix_fd_add_full(
            GLib.PRIORITY_DEFAULT,
            master_fd,
            GLib.IOCondition.IN | GLib.IOCondition.HUP,
            self._on_readable,
        )
        self._child_watch = GLib.child_watch_add(
            GLib.PRIORITY_DEFAULT, pid, self._on_child_exited
        )

    def _on_readable(self, fd: int, condition: GLib.IOCondition) -> bool:
        if condition & GLib.IOCondition.HUP and not (condition & GLib.IOCondition.IN):
            self._fd_watch = None
            return False
        try:
            chunk = os.read(fd, self.READ_CHUNK)
        except BlockingIOError:
            return True
        except OSError:
            self._fd_watch = None
            return False
        if not chunk:
            self._fd_watch = None
            return False
        clean, events = self._scanner.feed(chunk)
        if clean:
            self.emit("data-ready", clean)
        for ev in events:
            self.emit("progress-changed", ev.state, ev.value)
        return True

    def _on_child_exited(self, pid: int, status: int) -> None:
        self._child_watch = None
        self._child_pid = None
        self.emit("child-exited", status)

    def write(self, data: bytes) -> None:
        if self._master_fd is None:
            return
        try:
            os.write(self._master_fd, data)
        except OSError:
            pass

    def resize(self, rows: int, cols: int) -> None:
        if self._master_fd is None or rows <= 0 or cols <= 0:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def close(self) -> None:
        if self._fd_watch is not None:
            GLib.source_remove(self._fd_watch)
            self._fd_watch = None
        if self._child_watch is not None:
            GLib.source_remove(self._child_watch)
            self._child_watch = None
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
```

Note `ProgressEvent` is imported but only used by the type checker for clarity — it's referenced via `ev.state`/`ev.value` only, so the import is fine.

- [ ] **Step 2: Type-check the new module**

Run: `uv run pyright src/jfterm/pty_proxy.py`
Expected: no errors.

- [ ] **Step 3: Lint and format**

Run: `uv run ruff check src/jfterm/pty_proxy.py && uv run ruff format src/jfterm/pty_proxy.py`
Expected: clean.

If `ProgressEvent` is flagged as unused, drop the import — it's only referenced by attribute access on event objects.

- [ ] **Step 4: Commit**

```bash
git add src/jfterm/pty_proxy.py
git commit -m "feat(pty): add PtyProxy that owns shell pty and parses OSC 9;4"
```

---

## Task 6: JFTermTerminal — wire PtyProxy in place of spawn_async

**Files:**
- Modify: `src/jfterm/terminal.py`

- [ ] **Step 1: Replace the spawn_async block and add new signal**

Replace the entire current `JFTermTerminal` class with this version. The diff is large enough that a full replacement is clearer than per-region edits. Open `src/jfterm/terminal.py` and replace lines 15-167 (the class body) with:

```python
class JFTermTerminal(Vte.Terminal):
    """A VTE terminal driven by an in-process pty proxy.

    Emits:
      cwd-changed(str)            whenever VTE reports a new OSC 7 cwd
      running-changed(bool)       when foreground command starts/finishes
      title-changed(str)          when VTE's window title changes (OSC 0/2)
      progress-changed(int, int)  parsed OSC 9;4 (state, value)
    """

    __gsignals__ = {
        "cwd-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "running-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "title-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "progress-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
    }

    def __init__(
        self,
        cwd: str | None = None,
        send_after_spawn: str | None = None,
    ) -> None:
        super().__init__()
        self._initial_cwd = cwd or str(Path.home())
        self._osc133_seen = False
        self._send_after_spawn = send_after_spawn

        self.connect("current-directory-uri-changed", self._on_cwd_uri_changed)
        self.connect("window-title-changed", self._on_title_changed)
        self.connect("commit", self._on_commit)
        self.connect("char-size-changed", self._on_char_size_changed)

        for sig, handler in (
            ("shell-preexec", self._on_shell_preexec),
            ("shell-precmd", self._on_shell_precmd),
        ):
            with contextlib.suppress(TypeError, ValueError):
                self.connect(sig, handler)

        shell = os.environ.get("SHELL") or "/bin/bash"
        self._proxy = PtyProxy(self._initial_cwd, [shell, "-l"])
        self._proxy.connect("data-ready", self._on_proxy_data)
        self._proxy.connect("progress-changed", self._on_proxy_progress)
        self._proxy.connect("child-exited", self._on_proxy_child_exited)

        if self._send_after_spawn is not None:
            # Shell may not have read its initial prompt yet; pty buffers it.
            self._proxy.write((self._send_after_spawn + "\n").encode())
            self._send_after_spawn = None

        self._poll_source: int | None = GLib.timeout_add(250, self._poll_tcgetpgrp)

        self._install_context_menu()

    @property
    def shell_pid(self) -> int | None:
        return self._proxy.shell_pid

    @property
    def pty_fd(self) -> int | None:
        return self._proxy.pty_fd

    # --- context menu (unchanged) ---

    def _install_context_menu(self) -> None:
        menu = Gio.Menu()
        menu.append("Copy", "term.copy")
        menu.append("Paste", "term.paste")
        self._popover = Gtk.PopoverMenu.new_from_model(menu)
        self._popover.set_parent(self)
        self._popover.set_has_arrow(False)

        actions = Gio.SimpleActionGroup()
        copy_action = Gio.SimpleAction.new("copy", None)
        copy_action.connect("activate", lambda *_: self._do_copy())
        actions.add_action(copy_action)
        paste_action = Gio.SimpleAction.new("paste", None)
        paste_action.connect("activate", lambda *_: self._do_paste())
        actions.add_action(paste_action)
        self._copy_action = copy_action
        self.insert_action_group("term", actions)

        click = Gtk.GestureClick()
        click.set_button(Gdk.BUTTON_SECONDARY)
        click.connect("pressed", self._on_right_click)
        self.add_controller(click)

    def _on_right_click(self, _gesture, _n_press, x: float, y: float) -> None:
        self._copy_action.set_enabled(self.get_has_selection())
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def _do_copy(self) -> None:
        if self.get_has_selection():
            self.copy_clipboard_format(Vte.Format.TEXT)

    def _do_paste(self) -> None:
        self.paste_clipboard()

    # --- VTE callbacks ---

    def _on_cwd_uri_changed(self, _t) -> None:
        uri = self.get_current_directory_uri()
        if not uri:
            return
        parsed = urlparse(uri)
        path = unquote(parsed.path)
        self.emit("cwd-changed", path)

    def _on_title_changed(self, _t) -> None:
        title = self.get_window_title() or ""
        self.emit("title-changed", title)

    def _on_shell_preexec(self, _t) -> None:
        self._osc133_seen = True
        self.emit("running-changed", True)

    def _on_shell_precmd(self, _t) -> None:
        self._osc133_seen = True
        self.emit("running-changed", False)

    def _on_commit(self, _t, text: str, size: int) -> None:
        # VTE's commit signal hands us already-encoded bytes as a Python
        # string of length `size`. Convert via latin-1 to preserve bytes 1:1.
        self._proxy.write(text[:size].encode("latin-1"))

    def _on_char_size_changed(self, _t, _w, _h) -> None:
        cols = self.get_column_count()
        rows = self.get_row_count()
        self._proxy.resize(rows, cols)

    # --- proxy callbacks ---

    def _on_proxy_data(self, _p, data: bytes) -> None:
        self.feed(data)

    def _on_proxy_progress(self, _p, state: int, value: int) -> None:
        self.emit("progress-changed", state, value)

    def _on_proxy_child_exited(self, _p, status: int) -> None:
        # VTE has its own child-exited signal; we surface ours through the
        # same name so existing subscribers (e.g. tab close-on-exit logic)
        # keep working. If nothing currently subscribes, this is harmless.
        try:
            self.emit("child-exited", status)
        except TypeError:
            # `child-exited` is a built-in VTE signal with a fixed signature;
            # if our emit shape doesn't match, fall back to no-op.
            pass

    # --- polling fallback ---

    def _poll_tcgetpgrp(self) -> bool:
        if self._osc133_seen:
            self._poll_source = None
            return False
        if self.pty_fd is None or self.shell_pid is None:
            return True
        try:
            fg = os.tcgetpgrp(self.pty_fd)
        except OSError:
            return True
        running = fg != self.shell_pid
        self.emit("running-changed", running)
        return True
```

Then update the imports at the top of the file. Replace lines 1-13 with:

```python
import contextlib
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Vte", "3.91")

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Vte  # noqa: E402

from jfterm.pty_proxy import PtyProxy  # noqa: E402
```

- [ ] **Step 2: Type-check**

Run: `uv run pyright src/jfterm/terminal.py`
Expected: no errors. (If pyright complains about `child-exited` being an unknown signal, drop the `try/except` block and the `_on_proxy_child_exited` body's emit — leave the method but make it a no-op — and add a `# noqa` if needed. Document this decision in the commit.)

- [ ] **Step 3: Lint, format**

Run: `uv run ruff check src/jfterm/terminal.py && uv run ruff format src/jfterm/terminal.py`
Expected: clean.

- [ ] **Step 4: Smoke test by launching the app**

Run: `just run` (this will launch the GUI). Open a tab, type a few commands, run `ls`, run `top` (Ctrl-C to exit), resize the window. Verify everything still feels normal — typing works, output renders, prompt detection still flips the status dot.

If anything is broken, fix before committing. Common issues to check:
- Bytes vs str at `_on_commit`: VTE emits a UTF-8 string; encoding via `latin-1` round-trips the underlying bytes since GIR delivers them re-decoded. If commit doesn't reach the shell, try `text.encode("utf-8")` instead.
- Resize not propagating: ensure `_on_char_size_changed` fires; if not, also hook `size-allocate` and call `proxy.resize` from there.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/terminal.py
git commit -m "feat(terminal): drive shell via PtyProxy, expose progress-changed"
```

---

## Task 7: TabProgressBar widget

**Files:**
- Create: `src/jfterm/progress_bar.py`
- Create: `tests/test_progress_bar.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_progress_bar.py`:

```python
import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

# Headless GTK init — same pattern as test_window.py uses.
if not Gtk.init_check():
    pytest.skip("GTK cannot initialize", allow_module_level=True)

from jfterm.progress_bar import TabProgressBar  # noqa: E402


def test_initial_state_hidden():
    bar = TabProgressBar()
    assert bar.get_visible() is False


def test_state_1_makes_visible():
    bar = TabProgressBar()
    bar.set_progress(1, 50)
    assert bar.get_visible() is True
    assert bar.has_css_class("progress-normal")


def test_state_0_hides():
    bar = TabProgressBar()
    bar.set_progress(1, 50)
    bar.set_progress(0, 0)
    assert bar.get_visible() is False


def test_state_2_error_class():
    bar = TabProgressBar()
    bar.set_progress(2, 0)
    assert bar.has_css_class("progress-error")
    assert bar.get_visible() is True


def test_state_4_paused_class():
    bar = TabProgressBar()
    bar.set_progress(4, 30)
    assert bar.has_css_class("progress-paused")


def test_changing_state_swaps_css_class():
    bar = TabProgressBar()
    bar.set_progress(1, 50)
    bar.set_progress(2, 100)
    assert not bar.has_css_class("progress-normal")
    assert bar.has_css_class("progress-error")
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `uv run pytest tests/test_progress_bar.py -v`
Expected: collection FAIL (`No module named 'jfterm.progress_bar'`).

- [ ] **Step 3: Write the widget**

Create `src/jfterm/progress_bar.py`:

```python
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402


_STATE_CLASSES = {
    1: "progress-normal",
    2: "progress-error",
    3: "progress-indeterminate",
    4: "progress-paused",
}

_BAR_HEIGHT = 3
_INDETERMINATE_PERIOD_MS = 1500
_INDETERMINATE_TICK_MS = 33  # ~30 fps
_INDETERMINATE_WIDTH_FRAC = 0.30


class TabProgressBar(Gtk.Widget):
    """Thin progress bar overlaid on a tab title.

    Reads its color from the resolved CSS color of whichever
    `progress-*` class is active.
    """

    def __init__(self) -> None:
        super().__init__()
        self._state = 0
        self._value = 0
        self._anim_phase = 0.0  # 0..1
        self._anim_source: int | None = None
        self.set_visible(False)
        self.set_size_request(-1, _BAR_HEIGHT)
        self.set_valign(Gtk.Align.END)
        self.set_hexpand(True)
        # Don't intercept input.
        self.set_can_target(False)
        self.set_can_focus(False)

    def set_progress(self, state: int, value: int) -> None:
        if state == self._state and value == self._value:
            return
        # Swap CSS class.
        for cls in _STATE_CLASSES.values():
            if self.has_css_class(cls):
                self.remove_css_class(cls)
        new_class = _STATE_CLASSES.get(state)
        if new_class is not None:
            self.add_css_class(new_class)
        self._state = state
        self._value = max(0, min(100, value))
        self.set_visible(state != 0)
        if state == 3:
            self._start_animation()
        else:
            self._stop_animation()
        self.queue_draw()

    def _start_animation(self) -> None:
        if self._anim_source is not None:
            return
        self._anim_source = GLib.timeout_add(_INDETERMINATE_TICK_MS, self._tick)

    def _stop_animation(self) -> None:
        if self._anim_source is not None:
            GLib.source_remove(self._anim_source)
            self._anim_source = None
        self._anim_phase = 0.0

    def _tick(self) -> bool:
        self._anim_phase = (self._anim_phase + _INDETERMINATE_TICK_MS / _INDETERMINATE_PERIOD_MS) % 1.0
        self.queue_draw()
        return True

    def do_unmap(self) -> None:  # type: ignore[override]
        self._stop_animation()
        Gtk.Widget.do_unmap(self)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:  # type: ignore[override]
        if self._state == 0:
            return
        width = self.get_width()
        height = self.get_height()
        if width <= 0 or height <= 0:
            return

        color = self._resolve_color()

        if self._state == 3:
            # Indeterminate: a band of width INDETERMINATE_WIDTH_FRAC sweeps
            # across the bar; the leading edge moves from -W to width.
            band_w = max(1.0, width * _INDETERMINATE_WIDTH_FRAC)
            x_start = -band_w + (width + band_w) * self._anim_phase
            rect = Graphene.Rect().init(x_start, 0, band_w, height)
            snapshot.append_color(color, rect)
            return

        if self._state == 2 and self._value == 0:
            fill_w = float(width)
        else:
            fill_w = width * (self._value / 100.0)
        if fill_w <= 0:
            return
        rect = Graphene.Rect().init(0, 0, fill_w, height)
        snapshot.append_color(color, rect)

    def _resolve_color(self) -> Gdk.RGBA:
        # Pull the color the active CSS class resolves to.
        return self.get_color()
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_progress_bar.py -v`
Expected: all PASS.

- [ ] **Step 5: Type-check, lint, format**

Run:
```bash
uv run pyright src/jfterm/progress_bar.py
uv run ruff check src/jfterm/progress_bar.py
uv run ruff format src/jfterm/progress_bar.py
```
Expected: clean.

If pyright complains about `Gsk` being unused, drop it from the import. (We use `snapshot.append_color`, not a `Gsk.ColorNode` directly.)

- [ ] **Step 6: Commit**

```bash
git add src/jfterm/progress_bar.py tests/test_progress_bar.py
git commit -m "feat(ui): add TabProgressBar widget"
```

---

## Task 8: Sidebar — overlay the bar on each tab row

**Files:**
- Modify: `src/jfterm/sidebar.py`

- [ ] **Step 1: Add CSS for the four states**

In `src/jfterm/sidebar.py`, find the `_install_css` classmethod and append the new rules to its CSS string. The current method is around line 61. After the existing `.jfterm-active-tab` rule (or wherever the existing CSS string ends), add:

```css
.progress-normal       { color: @accent_bg_color; }
.progress-error        { color: @error_bg_color; }
.progress-paused       { color: @warning_bg_color; }
.progress-indeterminate{ color: @accent_bg_color; }
```

Note we use `color:` (not `background:`) — the widget pulls its fill from `get_color()`. Using `@accent_bg_color` etc. as the *foreground* lets `Gtk.Widget.get_color()` resolve the libadwaita named color cleanly.

- [ ] **Step 2: Add the import**

At the top of `src/jfterm/sidebar.py`, add (next to the `StatusDot` import):

```python
from jfterm.progress_bar import TabProgressBar
```

- [ ] **Step 3: Wrap the title in an Overlay**

In `_add_tab_row` (around line 297), find this block:

```python
        title = Gtk.Button()
        title.add_css_class("flat")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        title_label = Gtk.Label(label=tab.title or "tab", xalign=0)
        from gi.repository import Pango

        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_label.set_max_width_chars(24)
        title.set_child(title_label)
        title.connect("clicked", lambda _b, t=tab: self.emit("tab-activated", t))
```

Replace with:

```python
        title = Gtk.Button()
        title.add_css_class("flat")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        title_label = Gtk.Label(label=tab.title or "tab", xalign=0)
        from gi.repository import Pango

        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_label.set_max_width_chars(24)
        title.set_child(title_label)
        title.connect("clicked", lambda _b, t=tab: self.emit("tab-activated", t))

        title_overlay = Gtk.Overlay()
        title_overlay.set_hexpand(True)
        title_overlay.set_child(title)
        progress_bar = TabProgressBar()
        title_overlay.add_overlay(progress_bar)
        tab._progress_bar = progress_bar  # so window.py can update it
```

Then find the widget assembly block (around line 330):

```python
        widgets: list[Gtk.Widget] = [dot, title]
        if restart is not None:
            widgets.append(restart)
        widgets.append(close)
```

Replace `title` with `title_overlay`:

```python
        widgets: list[Gtk.Widget] = [dot, title_overlay]
        if restart is not None:
            widgets.append(restart)
        widgets.append(close)
```

- [ ] **Step 4: Manual smoke test**

Run: `just run`
Open a few tabs. Sidebar should look identical (bar is hidden until set).

- [ ] **Step 5: Type-check, lint, format**

Run:
```bash
uv run pyright src/jfterm/sidebar.py
uv run ruff check src/jfterm/sidebar.py
uv run ruff format src/jfterm/sidebar.py
```
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/jfterm/sidebar.py
git commit -m "feat(sidebar): overlay TabProgressBar on tab title"
```

---

## Task 9: Wire progress-changed into the sidebar; auto-clear on running false

**Files:**
- Modify: `src/jfterm/window.py`

- [ ] **Step 1: Inspect the existing _wire_terminal**

Read `src/jfterm/window.py` around lines 144-180 to see the existing handler-wiring pattern. You'll find handlers for `cwd-changed` and `running-changed` that follow the `t.terminal is term` guard pattern.

- [ ] **Step 2: Add the progress-changed wiring**

Inside `_wire_terminal`, after the existing `running-changed` connection, add:

```python
        terminal.connect(
            "progress-changed",
            lambda _t, state, value, t=tab, term=terminal: (
                self._on_tab_progress(t, state, value) if t.terminal is term else None
            ),
        )
```

- [ ] **Step 3: Implement the handlers**

Add two new methods to the same class, near the other `_on_tab_*` handlers:

```python
    def _on_tab_progress(self, tab: Tab, state: int, value: int) -> None:
        bar = getattr(tab, "_progress_bar", None)
        if bar is not None:
            bar.set_progress(state, value)

    def _clear_tab_progress(self, tab: Tab) -> None:
        bar = getattr(tab, "_progress_bar", None)
        if bar is not None:
            bar.set_progress(0, 0)
```

- [ ] **Step 4: Auto-clear on running-changed(False)**

Find the existing `running-changed` lambda in `_wire_terminal` (the one that calls something like `self._on_tab_running_changed`). Locate the corresponding handler method (probably `_on_tab_running_changed`) and add a single line at the top: if `running` is False, also call `self._clear_tab_progress(tab)`.

If the handler is inline in the lambda, refactor minimally: change the lambda to call a method that does both the existing work and the progress clear. Keep the diff small.

- [ ] **Step 5: Manual end-to-end smoke test**

Run: `just run`. In a tab, run:

```bash
printf '\e]9;4;1;25\e\\'    # bar at 25% accent
printf '\e]9;4;1;75\e\\'    # bar at 75%
printf '\e]9;4;2;0\e\\'     # full red
printf '\e]9;4;3\e\\'       # animated sweep
printf '\e]9;4;4;50\e\\'    # yellow at 50%
printf '\e]9;4;0\e\\'       # clear
```

Each should change the bar appropriately. Then with the bar non-zero, hit Enter at the prompt — bar should clear (auto-clear via `running-changed(False)`).

- [ ] **Step 6: Type-check, lint, format**

Run:
```bash
uv run pyright src/jfterm/window.py
uv run ruff check src/jfterm/window.py
uv run ruff format src/jfterm/window.py
```
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(window): route progress-changed to TabProgressBar; auto-clear"
```

---

## Task 10: Verify CI checks pass end-to-end

- [ ] **Step 1: Run the full check suite**

Run: `just check`

This runs `lint`, `fmt-check`, `typecheck`, and `test` in order. Fix anything that fails.

- [ ] **Step 2: Final smoke**

Run: `just run`. Walk the manual smoke matrix from the spec one more time, plus:
- Open multiple tabs in the same project; emit a sequence in one — only that tab's bar should change.
- Run an `npm run build` (or any progress-emitting tool you have available) — bar should track its real progress.
- Restart a launched-command tab via the restart button — new shell, bar starts fresh hidden.

- [ ] **Step 3: Final commit if any fixups**

If `just check` required fixups, commit them with a focused message. Otherwise nothing to do.

---

## Self-Review Notes

**Spec coverage:** All five spec sections (architecture, components, state mapping, auto-clear, testing) are covered. The "out of scope" items are correctly absent from the plan.

**Type consistency:** `set_progress(state, value)` is the single mutation surface for the bar; `progress-changed(int, int)` is the only signal; `_progress_bar` is the only widget back-reference name. All consistent.

**Risks / known sharp edges:**
- `commit` signal encoding: documented in Task 6 step 4. May need to switch from `latin-1` to `utf-8` if the round-trip doesn't behave; verify in smoke test.
- `child-exited` re-emission from PtyProxy: the existing `JFTermTerminal` code does NOT currently subscribe to `child-exited` itself (verified — original `terminal.py` has no such handler). The re-emit `try/except` block is defensive and may be removed if pyright is unhappy. Per Task 6 step 2, dropping it is fine.
- `do_snapshot` / `do_unmap` overrides via PyGObject use the `do_*` naming convention; if pyright objects to the override, the `# type: ignore[override]` comments are already in place.
