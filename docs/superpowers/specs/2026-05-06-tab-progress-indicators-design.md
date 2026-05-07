# Tab progress indicators (OSC 9;4)

Tracks issue #24. Show a thin progress bar pinned to the bottom edge of each
tab's title button, driven by `OSC 9;4` sequences emitted by tools running in
the shell (npm, cargo, ninja, fastfetch, etc.).

## Why a pty proxy

VTE 0.76 (the version on Ubuntu 24.04, our target) has no API for OSC 9;4 — it
parses unknown OSCs and silently discards them. Native progress properties
(`progress-hint`, `progress-value`) only land in VTE 0.80. Since bumping the
VTE requirement would drop our primary distro, we interpose on the shell's
output stream ourselves.

The proxy is in-process: shell runs on a pty we own, output flows through a
small OSC scanner that strips `OSC 9;4`, the rest is `feed()`-ed into VTE.
Performance is not a concern — the hot path is `bytes.find(b'\x1b]')` (CPython
memchr, GB/s) over 16-64KB chunks; per-chunk overhead is ~20-30 µs, and VTE
itself is the bottleneck on rendering.

## Components

### `pty_proxy.py` (new, ~150 lines)

`PtyProxy` class. Owns the shell-side master fd and the shell child process.

- `__init__(cwd, shell, env)` — opens a pty pair, `posix_spawn`s the shell on
  the slave side, registers `GLib.unix_fd_add(master, IN, _on_readable)`.
- `_on_readable` — reads up to 64KB, calls `OscScanner.feed`, emits
  `progress-changed` for each event, calls `terminal.feed(clean_bytes)`.
- `write(bytes)` — `os.write(master, …)`. Called from VTE's `commit` signal
  handler.
- `resize(rows, cols)` — `fcntl.ioctl(master, TIOCSWINSZ, …)`. Called on
  `terminal::char-size-changed` and on size-allocate.
- `close()` — close fds, reap child via `GLib.child_watch_add` callback that
  emits `child-exited` (mirroring VTE's signal) for the existing
  `_on_child_exited` path in `JFTermTerminal`.

`shell_pid` and `pty_fd` (the master fd) are exposed as attributes so the
existing `tcgetpgrp` polling fallback in `JFTermTerminal` keeps working
unchanged.

### `osc_scanner.py` (new)

`OscScanner` class. Holds a small carry buffer (≤256 bytes) for sequences
split across reads.

- `feed(chunk: bytes) -> tuple[bytes, list[ProgressEvent]]` — returns the
  bytes to forward to VTE (with any matched `OSC 9;4` sequences elided) and
  the parsed events.
- Algorithm:
  1. Prepend any leftover carry to `chunk`.
  2. Loop: `idx = data.find(b'\x1b]')`. If not found, append everything to
     output and return.
  3. Append `data[:idx]` to output, then look for the OSC terminator
     (`\x1b\\` or `\x07`) starting at `idx+2`.
     - Terminator found: extract the sequence body, try to parse as
       `9;4;<state>[;<value>]`. If it parses, emit a `ProgressEvent`; if
       not, pass the original sequence through to VTE unchanged. Continue
       the loop after the terminator.
     - Not found, but `len(data) - idx > 256`: bail out — flush the
       opening `\x1b]` as data and continue scanning past it. Bounds the
       carry size and prevents pathological hangs.
     - Not found and within the limit: stash `data[idx:]` as the new
       carry, return.

`ProgressEvent` is a tiny `dataclass(frozen=True)` with `state: int`,
`value: int`.

### `JFTermTerminal` (`terminal.py`) changes

- Drop `spawn_async`. Construct a `PtyProxy` instead. Connect VTE's `commit`
  signal to `proxy.write`; connect `char-size-changed` to call
  `proxy.resize`.
- Connect `proxy.connect("progress-changed", …)` and re-emit as the
  terminal's own `progress-changed(int, int)` signal.
- The polling fallback (`_poll_tcgetpgrp`) keeps working: `pty_fd` and
  `shell_pid` now come from the proxy, but its semantics are unchanged.

New signal:

```python
"progress-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
```

### `models.py`

**No changes.** Per coordination with the in-flight Tab refactor, progress
state lives entirely on the runtime widget side via the existing
`tab._dot`-style back-reference pattern. The sidebar stashes
`tab._progress_bar` and updates it directly; the bar's own `_state` /
`_value` attributes are the source of truth. Auto-clear logic lives in the
sidebar's `progress-changed` handler.

### `TabProgressBar` widget (new file `progress_bar.py` or in `sidebar.py`)

Subclasses `Gtk.Widget`. 3 px tall, `hexpand=True`. Drawn via `snapshot()`.

- `set_progress(state: int, value: int)` — updates internal state, calls
  `queue_draw()`, toggles visibility (hidden when `state == 0`), starts or
  stops the indeterminate animation timer (`state == 3` only).
- `snapshot(snap)` — appends a single `Gsk.ColorNode` for the filled portion.
  Color comes from named CSS classes resolved via `get_style_context()` —
  one of `progress-normal`, `progress-error`, `progress-paused`,
  `progress-indeterminate`. CSS lives in `Sidebar._install_css()`.
- Indeterminate animation: a `GLib.timeout_add(33, …)` running only while
  `state == 3` and the widget is mapped. Sweeps a 30%-wide highlight
  left→right with a 1.5 s period. Timer cancels itself when `state` changes
  or the widget is unmapped.

### Sidebar row layout

In `_add_tab_row`, wrap the existing title `Gtk.Button` in a `Gtk.Overlay`.
The button is the main child; a `TabProgressBar` is added as an overlay child
with `valign=END`. Stash `tab._progress_bar = bar`.

In `_wire_terminal` (in `window.py`), add a handler for `progress-changed`
that updates the bar via `tab._progress_bar`, gated on `tab.terminal is term`
(matching the existing pattern that protects against stale signals after a
restart).

In the existing `running-changed(False)` path, also call
`tab._progress_bar.set_progress(0, 0)`.

## State → visual mapping

| state | meaning | render |
|---|---|---|
| 0 | clear | bar hidden |
| 1 | normal, N% | accent-color rect, width = (N/100) × full |
| 2 | error | red rect; full-width if `value == 0`, else N% |
| 3 | indeterminate | accent, animated 30% sweep, 1.5 s loop |
| 4 | paused/warning | yellow rect, width = N% |

CSS:

```css
.progress-normal       { background: @accent_bg_color; }
.progress-error        { background: @error_bg_color; }
.progress-paused       { background: @warning_bg_color; }
.progress-indeterminate{ background: @accent_bg_color; }
```

(Snapshot reads the resolved color via `get_color()` after applying the
class.)

## Auto-clear

Bar resets to `(0, 0)` on either:
- explicit `OSC 9;4;0`
- `running-changed(False)` — covers OSC 133;D *and* the `tcgetpgrp` polling
  fallback

No timer-based clearing.

## Testing

### Unit tests (pure Python, fast, no GTK)

`tests/test_osc_scanner.py`:
- Well-formed `OSC 9;4;1;42 ST` and `OSC 9;4;1;42 BEL`.
- Every byte-boundary split of a single sequence across two `feed()` calls.
- Multiple sequences in one chunk, intermixed with regular text.
- `OSC 9;4;0` (clear).
- Unknown OSCs (`OSC 7`, `OSC 133;A`) pass through unchanged.
- Malformed: opening `\x1b]` with no terminator within 256 bytes → bail
  out, no event, original byte flushed.
- States 0/1/2/3/4, with and without value.
- Edge: terminator `\x1b\\` split exactly between the two bytes.

### Manual smoke matrix (record in PR description)

- `printf '\e]9;4;1;25\e\\'` → bar at 25%, accent color
- `printf '\e]9;4;1;75\e\\'` → bar at 75%
- `printf '\e]9;4;2;0\e\\'` → full-width red bar
- `printf '\e]9;4;3\e\\'` → animated sweep
- `printf '\e]9;4;4;50\e\\'` → yellow bar at 50%
- `printf '\e]9;4;0\e\\'` → bar disappears
- `npm run build` (or any progress-emitting tool) → bar tracks reported %
- Hit Enter at the prompt while bar is showing → bar clears (auto-clear via
  `running-changed(False)`)

## Out of scope

- Bumping VTE to ≥0.80 to use native `progress-hint` / `progress-value`. If
  the distro version catches up later, the proxy can be replaced with a
  thin wrapper around the native properties.
- Persisting progress state across restarts.
- Aggregating progress at the project-row level in the sidebar.
