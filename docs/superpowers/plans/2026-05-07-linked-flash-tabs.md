# Linked Flash Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `linked:` flash-command form that launches one process and one browser view in a single tab — webview top, terminal bottom — so the tab's lifetime matches the process and closing the tab kills it.

**Architecture:** A `linked: <url|auto> <command>` prefix on a `FlashCommand.command` string is parsed at launch time alongside the existing `is_web_url` branch. The new `LinkedTab` model holds both a `JFTermTerminal` and a `JFTermWebView` mounted in a `Gtk.Paned` (vertical, 80/20 default). The terminal is launched via the existing `wrap_flash_command` wrapper so clean exits close the whole tab and crashes leave a shell prompt; on non-zero exit the webview pane collapses to ~4px so the terminal output fills the tab. `auto` URL mode taps a new `output-data` signal on `JFTermTerminal` to scan the process's stdout for the first `https?://\S+` and loads it.

**Tech Stack:** Python 3, PyGObject (GTK 4 + VTE 3.91 + WebKit 6.0), pytest. No new dependencies.

---

## File Structure

**Create:**
- `src/jfterm/linked.py` — pure parser: `parse_linked(text: str) -> LinkedSpec | None` and `LinkedSpec` dataclass (`url: str | None`, `command: str`). `url=None` means `auto`.
- `src/jfterm/url_scanner.py` — `UrlScanner` class: buffers bytes, returns first `https?://\S+` match (or `None`).
- `src/jfterm/linkedtab.py` — `JFTermLinkedView(Gtk.Paned)` widget composing a `JFTermTerminal` (bottom) and `JFTermWebView` (top), with `collapse_webview()` method. Lazy WebKit import like `webtab.py`.
- `tests/test_linked.py` — parser tests.
- `tests/test_url_scanner.py` — scanner tests.

**Modify:**
- `src/jfterm/models.py` — add `LinkedTab(Tab)` dataclass with both `terminal` and `web_view` runtime fields plus the same lifecycle flags `TerminalTab` carries (`shell_pid`, `pty_fd`, `current_cwd`, `is_running`, `osc133_seen`, `launched_command`, `flash_name`, `is_restarting`).
- `src/jfterm/terminal.py` — add new `output-data(bytes)` GObject signal emitted from `_on_proxy_data`. (Existing `feed()` call is unchanged.)
- `src/jfterm/window.py` — add `_spawn_linked_tab(...)` and detect `linked:` prefix in `_on_flash_command_launched`. Wire child-exited handler that closes tab on exit 0 and collapses the webview otherwise. Make `_on_close_tab` and the dot/title rendering handle `LinkedTab`.
- `tests/test_flash.py` — extend with one launch-dispatch test if existing test structure permits (otherwise leave alone; new tests live in `test_linked.py`).

**Not modified:**
- `models.py`'s `FlashCommand` schema (we encode in the existing `command` string).
- Persistence (`persistence.py`): unchanged because `FlashCommand.command` is already a free-form string.
- `dialogs.py` flash-command editor: user just types `linked: ...` in the existing command field.

---

## Task 1: Parser for `linked:` flash strings

**Files:**
- Create: `src/jfterm/linked.py`
- Test: `tests/test_linked.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_linked.py
import pytest

from jfterm.linked import LinkedSpec, parse_linked


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Not linked
        ("echo hi", None),
        ("https://example.com", None),
        ("", None),
        ("   ", None),
        ("linked:", None),  # nothing after prefix
        ("linkedfoo: x y", None),  # prefix must be exactly "linked: "
        # Auto mode
        ("linked: auto jupyter notebook", LinkedSpec(url=None, command="jupyter notebook")),
        ("linked:   auto   jupyter notebook", LinkedSpec(url=None, command="jupyter notebook")),
        ("linked: AUTO jupyter notebook", LinkedSpec(url=None, command="jupyter notebook")),
        # Explicit URL
        (
            "linked: http://localhost:4200 quarto preview",
            LinkedSpec(url="http://localhost:4200", command="quarto preview"),
        ),
        (
            "linked: https://localhost:8888 jupyter notebook --no-browser",
            LinkedSpec(url="https://localhost:8888", command="jupyter notebook --no-browser"),
        ),
        # Command preserved verbatim including shell metacharacters
        (
            "linked: auto a && b; c",
            LinkedSpec(url=None, command="a && b; c"),
        ),
        # Missing command after url is invalid
        ("linked: auto", None),
        ("linked: http://localhost:4200", None),
        # Unrecognized first token (not auto, not http(s)) is invalid
        ("linked: ftp://x cmd", None),
        ("linked: localhost:4200 cmd", None),
    ],
)
def test_parse_linked(text: str, expected: LinkedSpec | None) -> None:
    assert parse_linked(text) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_linked.py -v`
Expected: ImportError or FAIL — `jfterm.linked` does not exist.

- [ ] **Step 3: Implement parser**

```python
# src/jfterm/linked.py
from __future__ import annotations

import re
from dataclasses import dataclass

_PREFIX_RE = re.compile(r"^\s*linked:\s+(.*)$", re.IGNORECASE | re.DOTALL)
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


@dataclass(frozen=True)
class LinkedSpec:
    """A parsed `linked: <url|auto> <command>` string.

    `url is None` means auto-detect from the process's stdout. Otherwise
    `url` is the absolute http(s) URL to load immediately.
    `command` is the raw shell command, with all metacharacters preserved.
    """

    url: str | None
    command: str


def parse_linked(text: str) -> LinkedSpec | None:
    """Return a LinkedSpec if `text` matches `linked: <url|auto> <cmd>`, else None.

    The first whitespace-delimited token after `linked: ` must be either
    the literal `auto` (case-insensitive) or an absolute http(s) URL.
    Everything after that token is the raw command. Returns None for any
    string that does not match this shape.
    """
    m = _PREFIX_RE.match(text)
    if not m:
        return None
    rest = m.group(1).strip()
    if not rest:
        return None
    parts = rest.split(None, 1)
    if len(parts) != 2:
        return None
    head, command = parts[0], parts[1].strip()
    if not command:
        return None
    if head.lower() == "auto":
        return LinkedSpec(url=None, command=command)
    if _URL_RE.match(head):
        return LinkedSpec(url=head, command=command)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_linked.py -v`
Expected: all parametrized cases PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/linked.py tests/test_linked.py
git commit -m "feat(linked): add parser for 'linked: <url|auto> <cmd>' flash strings"
```

---

## Task 2: Streaming URL scanner

**Files:**
- Create: `src/jfterm/url_scanner.py`
- Test: `tests/test_url_scanner.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_url_scanner.py
from jfterm.url_scanner import UrlScanner


def test_scanner_starts_empty():
    s = UrlScanner()
    assert s.first_url() is None


def test_scanner_finds_url_in_one_chunk():
    s = UrlScanner()
    s.feed(b"Server running at http://localhost:4200/ ready\n")
    assert s.first_url() == "http://localhost:4200/"


def test_scanner_finds_first_url_only():
    s = UrlScanner()
    s.feed(b"start http://a.test/x then http://b.test/y end")
    assert s.first_url() == "http://a.test/x"


def test_scanner_handles_url_split_across_chunks():
    s = UrlScanner()
    s.feed(b"Listening on http://localh")
    assert s.first_url() is None
    s.feed(b"ost:8888/?token=abc\n")
    assert s.first_url() == "http://localhost:8888/?token=abc"


def test_scanner_supports_https():
    s = UrlScanner()
    s.feed(b"open https://localhost:9443/app\n")
    assert s.first_url() == "https://localhost:9443/app"


def test_scanner_strips_trailing_punctuation():
    s = UrlScanner()
    s.feed(b"Visit http://localhost:4200/.\n")
    assert s.first_url() == "http://localhost:4200/"


def test_scanner_strips_ansi_color_escapes():
    # Many dev servers wrap URLs in ANSI escapes (e.g. underline + color).
    s = UrlScanner()
    s.feed(b"\x1b[1mLocal:\x1b[0m  \x1b[36mhttp://localhost:5173/\x1b[0m\n")
    assert s.first_url() == "http://localhost:5173/"


def test_scanner_caps_buffer_to_avoid_unbounded_growth():
    s = UrlScanner(max_buffer=1024)
    # Feed garbage that will never match; buffer stays bounded.
    s.feed(b"x" * 10_000)
    s.feed(b"http://a.test/y\n")
    # Even after eviction, a clean match in the latest chunk is found.
    assert s.first_url() == "http://a.test/y"


def test_scanner_idempotent_after_match():
    s = UrlScanner()
    s.feed(b"http://a.test/1\n")
    assert s.first_url() == "http://a.test/1"
    # Subsequent feeds do not change the first match.
    s.feed(b"http://b.test/2\n")
    assert s.first_url() == "http://a.test/1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_url_scanner.py -v`
Expected: ImportError — `jfterm.url_scanner` does not exist.

- [ ] **Step 3: Implement the scanner**

```python
# src/jfterm/url_scanner.py
from __future__ import annotations

import re

# ANSI CSI sequences (e.g. \x1b[1;36m). We strip these before matching so
# URLs printed by dev servers with color/underline styling still match.
_ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]")
_URL_RE = re.compile(rb"https?://[^\s\x00-\x1f]+")
# Trailing punctuation that's almost never part of an actual URL but often
# appears next to one in prose ("Visit http://x/."). Stripped from the tail.
_TRAILING_TRIM = b").,;:!?]>\"'"


class UrlScanner:
    """Buffers bytes from a terminal output stream and exposes the first
    http(s) URL it observes.

    Designed for the linked-flash `auto` mode: we cannot know in advance
    when a server will print its URL, and the URL may be split across
    several chunks delivered to `data-ready`. The buffer is capped so a
    long-running tail does not grow without bound; once a URL is found it
    is latched and `first_url()` returns it forever.
    """

    def __init__(self, max_buffer: int = 64 * 1024) -> None:
        self._buf = bytearray()
        self._url: str | None = None
        self._max_buffer = max_buffer

    def feed(self, data: bytes) -> None:
        if self._url is not None:
            return
        self._buf.extend(data)
        if len(self._buf) > self._max_buffer:
            # Keep only the tail; the in-flight prefix of a URL would be
            # at the END of the buffer, not the beginning.
            del self._buf[: len(self._buf) - self._max_buffer]
        clean = _ANSI_RE.sub(b"", bytes(self._buf))
        m = _URL_RE.search(clean)
        if not m:
            return
        url_bytes = m.group(0).rstrip(_TRAILING_TRIM)
        try:
            self._url = url_bytes.decode("utf-8")
        except UnicodeDecodeError:
            self._url = url_bytes.decode("utf-8", errors="replace")

    def first_url(self) -> str | None:
        return self._url
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_url_scanner.py -v`
Expected: all 9 cases PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/url_scanner.py tests/test_url_scanner.py
git commit -m "feat(linked): add streaming URL scanner for auto-detect mode"
```

---

## Task 3: Expose terminal output as a GObject signal

**Files:**
- Modify: `src/jfterm/terminal.py:29-34, 186-187`
- Test: `tests/test_window.py` (smoke; only if WebKit/VTE available — see existing pattern)

This task adds a single GObject signal `output-data(bytes)` to `JFTermTerminal` that fires on every PTY chunk, alongside the existing `feed()` call. `LinkedTab` (Task 5) needs this to drive `UrlScanner`. We touch `terminal.py` rather than reaching into the private `_proxy` so future PTY refactors don't break linked tabs.

- [ ] **Step 1: Read current emit shape**

Read `src/jfterm/terminal.py:29-34` and `src/jfterm/terminal.py:186-187` to confirm the existing `__gsignals__` dict layout and the `_on_proxy_data` handler shape.

- [ ] **Step 2: Add the signal declaration**

Modify `src/jfterm/terminal.py:29-34`. Replace the `__gsignals__` block:

```python
    __gsignals__ = {
        "cwd-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "running-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "title-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "progress-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        "output-data": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
```

(GObject does not have a native "bytes" type code; `object` boxes the Python `bytes` value.)

- [ ] **Step 3: Emit from `_on_proxy_data`**

Modify `src/jfterm/terminal.py:186-187`. Replace `_on_proxy_data` to also emit the new signal:

```python
    def _on_proxy_data(self, _p, data: bytes) -> None:
        self.feed(data)
        self.emit("output-data", data)
```

- [ ] **Step 4: Run the existing test suite to confirm no regressions**

Run: `pytest tests/ -x -q`
Expected: all previously-passing tests still pass. (No new test in this task — Task 5's LinkedTab smoke test will exercise the signal end-to-end.)

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/terminal.py
git commit -m "feat(terminal): emit output-data signal on every PTY chunk"
```

---

## Task 4: `LinkedTab` model class

**Files:**
- Modify: `src/jfterm/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_models.py`:

```python
def test_linked_tab_defaults():
    from jfterm.models import LinkedTab

    t = LinkedTab()
    assert t.terminal is None
    assert t.web_view is None
    assert t.paned is None
    assert t.shell_pid is None
    assert t.pty_fd is None
    assert t.current_cwd is None
    assert t.is_running is False
    assert t.osc133_seen is False
    assert t.launched_command is None
    assert t.flash_name is None
    assert t.is_restarting is False
    assert t.linked_url is None
    # Inherits id and title from Tab
    assert t.title == ""
    assert isinstance(t.id, str) and len(t.id) > 0


def test_linked_tab_widget_returns_paned():
    from jfterm.models import LinkedTab

    sentinel = object()
    t = LinkedTab(paned=sentinel)
    assert t.widget is sentinel
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py::test_linked_tab_defaults tests/test_models.py::test_linked_tab_widget_returns_paned -v`
Expected: FAIL — `LinkedTab` does not exist.

- [ ] **Step 3: Add `LinkedTab` to `models.py`**

Insert this dataclass after `WebTab` in `src/jfterm/models.py` (just before `class Group`):

```python
@dataclass
class LinkedTab(Tab):
    """A `linked:` flash tab: a single tab containing both a terminal (a
    JFTermTerminal driving a shell) and a webview (a JFTermWebView)
    arranged vertically in a Gtk.Paned. The tab's lifetime is tied to
    the shell, exactly like TerminalTab — the wrap_flash_command wrapper
    causes the shell to exit on success, and on non-zero exit the
    webview pane is collapsed so the terminal output fills the tab.
    """

    # Runtime widgets (populated when the tab is materialised):
    terminal: Any = None
    web_view: Any = None
    paned: Any = None

    # Mirrors of TerminalTab's lifecycle fields — populated/updated by
    # the same handlers, so existing dot/progress/title plumbing works.
    shell_pid: int | None = None
    pty_fd: int | None = None
    current_cwd: str | None = None
    is_running: bool = False
    osc133_seen: bool = False
    launched_command: str | None = None
    flash_name: str | None = None
    is_restarting: bool = False

    # The URL we are showing (or about to show, in `auto` mode after
    # the scanner picks one up). None means we are still waiting in
    # auto-detect mode.
    linked_url: str | None = None

    @property
    def widget(self) -> Any:
        return self.paned
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: all model tests including the two new ones PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jfterm/models.py tests/test_models.py
git commit -m "feat(models): add LinkedTab dataclass for linked-flash tabs"
```

---

## Task 5: `JFTermLinkedView` widget

**Files:**
- Create: `src/jfterm/linkedtab.py`

This widget composes a `JFTermWebView` (top) and `JFTermTerminal` (bottom) inside a `Gtk.Paned`. It does NOT own lifecycle — the window owns spawning and tab removal. The widget exposes:
- `terminal`: the `JFTermTerminal` instance.
- `web_view`: the `JFTermWebView` instance.
- `set_url(url: str)`: load the given URL in the webview (used by both explicit-URL mode at startup and auto-mode when the scanner picks one up).
- `collapse_webview()`: set the paned position to ~4px so the terminal fills the tab but the divider remains grabbable.

There is no separate test file for this module — it requires GTK + WebKit + VTE which the test environment may lack. The integration test in Task 6 exercises it.

- [ ] **Step 1: Create `linkedtab.py`**

```python
# src/jfterm/linkedtab.py
"""Composite view for `linked:` flash tabs: a vertical Gtk.Paned with a
JFTermWebView on top and a JFTermTerminal on the bottom.

Imports WebKit lazily via `webtab.is_available()`; callers must check
`is_available()` before constructing a JFTermLinkedView. WebKit and VTE
are both required.
"""

from __future__ import annotations

from typing import Any

from gi.repository import Gtk

from jfterm.terminal import JFTermTerminal
from jfterm.webtab import JFTermWebView, is_available  # re-export

# Width (in pixels) the webview pane shrinks to when the process exits
# non-zero. Small enough to be effectively hidden, large enough that the
# Gtk.Paned divider is still visible and drag-grabbable so the user can
# pull the (now-broken) browser back into view if they want to.
COLLAPSED_WEBVIEW_PX = 4


class JFTermLinkedView(Gtk.Paned):
    """Vertical Paned: webview top, terminal bottom. Default split is
    roughly 80% webview / 20% terminal; the divider is user-draggable.
    """

    def __init__(
        self,
        *,
        cwd: str | None,
        send_after_spawn: str | None,
        appearance: Any,
        initial_url: str | None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        # initial_url=None means "auto-detect"; show a blank placeholder.
        url_to_load = initial_url if initial_url is not None else "about:blank"
        self.web_view = JFTermWebView(url=url_to_load)
        self.web_view.set_vexpand(True)
        self.web_view.set_hexpand(True)

        self.terminal = JFTermTerminal(
            cwd=cwd,
            send_after_spawn=send_after_spawn,
            appearance=appearance,
        )
        self.terminal.set_vexpand(True)
        self.terminal.set_hexpand(True)

        self.set_start_child(self.web_view)
        self.set_end_child(self.terminal)
        self.set_resize_start_child(True)
        self.set_resize_end_child(True)
        self.set_shrink_start_child(True)
        self.set_shrink_end_child(True)

        # Default 80/20 split is applied once the widget gets its size.
        # Until then a Paned defaults to giving the start child all the
        # space, which is fine; we adjust on first allocation.
        self._initial_split_applied = False
        self.connect("notify::max-position", self._maybe_apply_default_split)

    def _maybe_apply_default_split(self, *_: Any) -> None:
        if self._initial_split_applied:
            return
        max_pos = self.get_property("max-position")
        if max_pos <= 0:
            return
        self.set_position(int(max_pos * 0.8))
        self._initial_split_applied = True

    def set_url(self, url: str) -> None:
        """Load `url` in the webview. Used both at startup (explicit URL)
        and from auto-mode when the scanner picks one up."""
        # JFTermWebView exposes load via its internal _web; reuse the
        # entry-activate behavior by loading via the public webkit method.
        self.web_view._web.load_uri(url)  # noqa: SLF001 — internal but stable

    def collapse_webview(self) -> None:
        """Shrink the webview to a hairline so the terminal fills the
        tab. Called when the process exits non-zero so the failure
        output is what the user sees, while leaving the Paned divider
        grabbable."""
        self.set_position(COLLAPSED_WEBVIEW_PX)

    def grab_focus(self) -> bool:  # type: ignore[override]
        return self.terminal.grab_focus()


__all__ = ["JFTermLinkedView", "is_available", "COLLAPSED_WEBVIEW_PX"]
```

- [ ] **Step 2: Quick smoke import**

Run: `python -c "from jfterm.linkedtab import JFTermLinkedView, is_available, COLLAPSED_WEBVIEW_PX; print(COLLAPSED_WEBVIEW_PX)"`
Expected: `4` printed (no import errors). If `gi`/`Gtk` is missing this will fail; the actual widget construction is tested via the window in later tasks where GTK is required regardless.

- [ ] **Step 3: Commit**

```bash
git add src/jfterm/linkedtab.py
git commit -m "feat(linked): add JFTermLinkedView composite widget (paned + webview + terminal)"
```

---

## Task 6: Window-level spawn for linked tabs

**Files:**
- Modify: `src/jfterm/window.py` (multiple regions; see steps)
- Modify: `src/jfterm/window.py` `_on_flash_command_launched` at line 605

This task adds `_spawn_linked_tab` and dispatches to it from `_on_flash_command_launched`. We reuse `wrap_flash_command` so clean exits close the tab and crashes leave a shell prompt; the only new lifecycle behaviour is "on non-zero exit, collapse the webview".

- [ ] **Step 1: Add `_spawn_linked_tab` method**

Insert this method in `src/jfterm/window.py` immediately after `_spawn_web_tab` (around line 299). Note we adapt `_wire_terminal` for `LinkedTab` by hooking `child-exited` ourselves.

```python
    def _spawn_linked_tab(
        self,
        group: Group,
        *,
        spec,  # jfterm.linked.LinkedSpec
        flash_name: str,
        focus: bool = True,
    ) -> "LinkedTab":
        from jfterm.linked import LinkedSpec  # noqa: F401  (typing only)
        from jfterm.linkedtab import JFTermLinkedView, is_available
        from jfterm.models import LinkedTab
        from jfterm.url_scanner import UrlScanner

        if not is_available():
            # Fall back to a plain terminal tab with a "WebKit missing" note.
            from jfterm.webtab import WEBKIT_PACKAGE

            fb = self._spawn_tab(
                group,
                command=f'echo "JFTerm: linked: needs {WEBKIT_PACKAGE}"',
                focus=focus,
            )
            fb.flash_name = flash_name
            fb.title = f"⚡ {flash_name}"
            return fb  # caller treats as best-effort

        cwd = group.directory if isinstance(group, Project) else None
        wrapped = wrap_flash_command(
            FlashCommand(name=flash_name, command=spec.command),
        )
        view = JFTermLinkedView(
            cwd=cwd,
            send_after_spawn=wrapped,
            appearance=self._settings,
            initial_url=spec.url,  # None means auto-detect
        )

        tab = LinkedTab(
            title=f"⚡ {flash_name}",
            terminal=view.terminal,
            web_view=view.web_view,
            paned=view,
            launched_command=spec.command,
            flash_name=flash_name,
            linked_url=spec.url,
        )

        # Wire terminal lifecycle signals — same handlers as TerminalTab
        # so dot/progress/title plumbing still works. We replace the
        # close-tab handler with a linked-tab-aware version that decides
        # whether to collapse the webview or close the whole tab.
        term = view.terminal
        term.connect(
            "cwd-changed",
            lambda _t, path, t=tab, x=term: (
                self._on_tab_cwd_changed(t, path) if t.terminal is x else None
            ),
        )
        term.connect(
            "running-changed",
            lambda _t, running, t=tab, x=term: (
                self._on_tab_running_changed(t, running) if t.terminal is x else None
            ),
        )
        term.connect(
            "title-changed",
            lambda _t, title, t=tab, x=term: (
                self._on_tab_title_changed(t, title) if t.terminal is x else None
            ),
        )
        term.connect(
            "progress-changed",
            lambda _t, state, value, t=tab, x=term: (
                self._on_tab_progress(t, state, value) if t.terminal is x else None
            ),
        )
        term.connect(
            "child-exited",
            lambda _t, status, t=tab, v=view, x=term: (
                self._on_linked_child_exited(t, v, status) if t.terminal is x else None
            ),
        )

        # auto-detect URL: scan terminal output for the first http(s) URL.
        if spec.url is None:
            scanner = UrlScanner()

            def _on_output(_t, data, sc=scanner, v=view, t=tab, x=term):
                if t.terminal is not x or t.linked_url is not None:
                    return
                sc.feed(data)
                found = sc.first_url()
                if found is not None:
                    t.linked_url = found
                    v.set_url(found)

            term.connect("output-data", _on_output)

        # Mount in the same stack used by terminal/web tabs.
        self.terminal_stack.add_child(view)
        group.add_tab(tab)
        if focus:
            self._current_group = group
            self.terminal_stack.set_visible_child(view)
            self.sidebar.set_active_tab(tab)
            view.grab_focus()
        self.sidebar.refresh()
        return tab

    def _on_linked_child_exited(self, tab, view, status: int) -> None:
        # Mirror wrap_flash_command's contract: on exit 0 the wrapper
        # ran `exit` itself, so close the whole tab. On non-zero, the
        # shell stays alive at a prompt — collapse the webview so the
        # error output fills the tab.
        if status == 0:
            self._on_close_tab(self.sidebar, tab)
        else:
            view.collapse_webview()
```

- [ ] **Step 2: Dispatch `linked:` from `_on_flash_command_launched`**

Modify `src/jfterm/window.py` `_on_flash_command_launched` (currently at line 605). Insert a `linked:` check BEFORE the existing `is_web_url` branch:

```python
    def _on_flash_command_launched(self, _sb, project: Project, fc: FlashCommand) -> None:
        if not project.expanded:
            project.expanded = True
            save_projects(self.ws, default_path())
            self.sidebar.refresh()

        from jfterm.linked import parse_linked
        from jfterm.url_routing import is_web_url

        linked_spec = parse_linked(fc.command)
        if linked_spec is not None:
            self._spawn_linked_tab(
                project,
                spec=linked_spec,
                flash_name=fc.name,
                focus=fc.focus_on_launch,
            )
            self.sidebar.refresh()
            return

        if is_web_url(fc.command):
            try:
                self._spawn_web_tab(
                    project,
                    url=fc.command.strip(),
                    focus=fc.focus_on_launch,
                    flash_name=fc.name,
                )
            except RuntimeError as e:
                fb = self._spawn_tab(
                    project,
                    command=f'echo "JFTerm: {e}"',
                    focus=fc.focus_on_launch,
                )
                fb.flash_name = fc.name
                fb.title = f"⚡ {fc.name}"
            self.sidebar.refresh()
            return

        wrapped = wrap_flash_command(fc)
        tab = self._spawn_tab(project, command=wrapped, focus=fc.focus_on_launch)
        tab.flash_name = fc.name
        tab.title = f"⚡ {fc.name}"
        self.sidebar.refresh()
```

- [ ] **Step 3: Verify `_on_close_tab` already handles `LinkedTab`**

Read `src/jfterm/window.py` `_on_close_tab` (around line 335). Confirm the function:
- removes the tab from its group
- removes the widget from `terminal_stack` via `tab.widget` (not `tab.terminal`)
- closes the PTY (only branches on `TerminalTab`)

If `_on_close_tab` only closes the PTY for `TerminalTab`, modify it to also close the PTY when the tab is a `LinkedTab`. Concretely, look for the existing isinstance check and change:

```python
if isinstance(tab, TerminalTab):
    # ... close terminal/proxy
```

to:

```python
from jfterm.models import LinkedTab  # local import to avoid cycles

if isinstance(tab, (TerminalTab, LinkedTab)):
    # ... close terminal/proxy
    # use tab.terminal in both cases
```

(Adjust to whatever local naming the file uses.) Make sure any references to `tab.terminal` work for both classes — both have a `terminal` attribute.

- [ ] **Step 4: Update sidebar/dot rendering if it special-cases TerminalTab**

Run: `grep -n "TerminalTab\|isinstance" src/jfterm/sidebar.py src/jfterm/window.py`

For each `isinstance(_, TerminalTab)` branch that drives:
- the status dot
- the title prefix (`⚡` flash name)
- progress overlay

Extend it to also accept `LinkedTab`. The two model classes share the lifecycle field shape (`is_running`, `osc133_seen`, `flash_name`), so the change is mechanical: replace `isinstance(x, TerminalTab)` with `isinstance(x, (TerminalTab, LinkedTab))` on lines that read those fields.

Do NOT extend places that read terminal-only attributes (`launched_command` for restart, `is_restarting` for the restart guard) yet — restart for linked tabs is out of scope for v1; if such code paths fire on a `LinkedTab` they'll just be no-ops because `is_restarting` is False.

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -x -q`
Expected: all existing tests still pass; new `test_linked.py` and `test_url_scanner.py` continue to pass. (No new automated test in this task — the integration is verified manually in Task 7.)

- [ ] **Step 6: Commit**

```bash
git add src/jfterm/window.py
git commit -m "feat(linked): wire linked: flash commands into window spawn path"
```

---

## Task 7: Manual verification

**Files:** none.

This task is an explicit smoke-test gate before declaring the feature done. It is bite-sized but cannot be automated because it exercises a real WebKit + VTE + sub-process chain.

- [ ] **Step 1: Add a transient `linked:` flash command to a project**

Open jfterm. Pick any project. Edit it. Add a flash command:

- Name: `Test linked explicit`
- Command: `linked: http://example.com sleep 30`

Save.

- [ ] **Step 2: Launch it and verify split layout**

Trigger the flash. Expected:
- New tab in the project, titled `⚡ Test linked explicit`.
- Tab content: webview (loading example.com) on top, terminal running `sleep 30` on bottom.
- Webview pane occupies ~80% height; terminal ~20%; the divider is draggable.

- [ ] **Step 3: Verify clean exit closes the tab**

In the terminal pane, press `Ctrl+C`. The wrap_flash_command wrapper treats SIGINT-killed `sleep` as non-zero, so this is the failure path — see Step 4. To test the success path, instead use a flash command:

- Command: `linked: http://example.com true`

Launch. Expected: the `true` command exits 0 immediately, so the wrapper runs `exit`, the shell dies, and the entire tab closes within a second of launch.

- [ ] **Step 4: Verify non-zero exit collapses webview**

Add a flash command:

- Command: `linked: http://example.com false`

Launch. Expected:
- Tab opens with the split layout.
- `false` exits 1 immediately. The wrapper prints `Command failed (exit 1)` and stays at a shell prompt.
- The webview pane collapses to a hairline (~4px), terminal pane fills the rest.
- The divider remains grabbable: drag it down and the webview reappears.

- [ ] **Step 5: Verify auto-detect**

Add a flash command:

- Command: `linked: auto python3 -c "import http.server, socketserver, time; s=socketserver.TCPServer(('127.0.0.1',8765), http.server.SimpleHTTPRequestHandler); print('Serving at http://127.0.0.1:8765/'); s.serve_forever()"`

Launch. Expected:
- Tab opens with `about:blank` placeholder in the webview.
- Within ~1s the terminal prints the `Serving at http://127.0.0.1:8765/` line.
- The webview navigates to `http://127.0.0.1:8765/` and shows the directory listing of the project's cwd.

- [ ] **Step 6: Verify closing the tab kills the process**

With the auto-detect tab from Step 5 still running, close the tab via the sidebar's close-tab affordance. Expected:
- Tab disappears.
- The python http.server process is gone (verify with `ps aux | grep SimpleHTTPRequestHandler` — no match).

- [ ] **Step 7: Clean up the test flash commands**

Delete the three temporary flash commands you added.

- [ ] **Step 8: Commit (docs only, optional)**

If you noticed any rough edges during manual testing that warrant a follow-up, file them as TODOs in a notes file or as an issue. Otherwise no commit needed.

---

## Self-review summary

**Spec coverage:**
- `linked: <url|auto> <cmd>` syntax: Task 1.
- `auto` URL discovery from stdout: Task 2 + Task 3 + Task 6 Step 1.
- Split tab (webview top / terminal bottom, 80/20, draggable): Task 5.
- Lifecycle: clean exit closes tab, non-zero exit collapses webview: Task 6 Step 1 (`_on_linked_child_exited`) + reuse of `wrap_flash_command`.
- Tab close kills process: Task 6 Step 3 (extending `_on_close_tab`).
- No schema/persistence changes: confirmed in File Structure.
- Manual verification: Task 7.

**No placeholders:** every step gives the exact code to write or the exact command to run.

**Type consistency:** `LinkedSpec(url, command)` used identically in Task 1 (definition) and Task 6 (consumption). `LinkedTab` fields used in Task 4 (definition) match those read in Task 6 (`tab.terminal`, `tab.web_view`, `tab.flash_name`, `tab.linked_url`). `JFTermLinkedView` methods (`set_url`, `collapse_webview`, `terminal`, `web_view`) used in Task 5 (definition) match those called in Task 6.
