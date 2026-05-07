# Webkit tabs design

Tracking issue: #22.

JFTerm tabs are currently always VTE terminals. This spec adds a second tab
kind — a WebKitGTK-based "web tab" — useful for keeping a project's dev
server (e.g. `http://localhost:4000`) visible alongside the shells that run
it.

## Goals

- Treat any startup or flash command that starts with `http://` or
  `https://` as a web tab instead of a shell command.
- Add an ad-hoc "New web tab…" entry via right-click on the sidebar `+`
  button.
- Embed a small mini-browser (back / forward / reload / editable URL bar)
  with persistent cookies, so logins to the dev server stick.
- Refactor the tab model into a base class with terminal and web subclasses
  so future tab kinds slot in cleanly.

## Non-goals

- Bookmarks, history pane, download manager.
- URL schemes other than `http(s)://` (no `file://`, no auto-prepending).
- Per-project isolated cookie jars.
- Auto-detecting URLs printed in terminal output.
- Persisting tabs across JFTerm restarts (terminal tabs aren't persisted
  today either; out of scope).

## Model refactor

`src/jfterm/models.py` splits `Tab` into a base class and two concrete
subclasses:

```python
@dataclass
class Tab:
    title: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _dot: Any = None

    @property
    def widget(self) -> Any:
        raise NotImplementedError

@dataclass
class TerminalTab(Tab):
    terminal: Any = None
    shell_pid: int | None = None
    pty_fd: int | None = None
    current_cwd: str | None = None
    is_running: bool = False
    osc133_seen: bool = False
    launched_command: str | None = None
    flash_name: str | None = None
    from_startup: bool = False
    is_restarting: bool = False

    @property
    def widget(self) -> Any:
        return self.terminal

@dataclass
class WebTab(Tab):
    url: str = ""
    web_view: Any = None
    from_startup: bool = False
    flash_name: str | None = None

    @property
    def widget(self) -> Any:
        return self.web_view
```

`Group.tabs` stays `list[Tab]`. Window code currently reading `tab.terminal`
just to fetch the GTK widget mounted in the stack migrates to `tab.widget`.
Code that genuinely needs terminal-only behavior (cwd-changed, running
state, restart) becomes `isinstance(tab, TerminalTab)` branches.

Persistence is unaffected — only project config (startup/flash commands)
hits disk.

## Web tab widget — `src/jfterm/webtab.py`

A new `JFTermWebView` widget — a vertical `Gtk.Box` containing:

1. A horizontal toolbar:
   - Back button (`go-previous-symbolic`), sensitive iff
     `web_view.can_go_back()`
   - Forward button (`go-next-symbolic`), sensitive iff
     `web_view.can_go_forward()`
   - Reload button (`view-refresh-symbolic`)
   - URL `Gtk.Entry` (hexpand). Pressing Enter loads the entry's text.
     `Ctrl+L` focuses and selects-all the entry. The entry text is updated
     when the page navigates.

2. A `WebKit.WebView` (vexpand). DevTools are enabled
   (`settings.set_enable_developer_extras(True)`) so the default
   right-click menu offers Inspect; F12 toggles the inspector.

The widget emits two GObject signals consumed by the window:

- `title-changed(str)` — bound from `WebView.notify::title`.
- `url-changed(str)` — bound from `WebView.notify::uri`. Also drives the
  URL entry text and back/forward sensitivity.

### Shared session

`src/jfterm/webkit_session.py` exposes `get_session() -> WebKit.NetworkSession`,
lazily constructing one persistent `NetworkSession` rooted at
`~/.local/share/jfterm/webkit/` (data) and `~/.cache/jfterm/webkit/`
(cache). All web tabs share this session, so cookies and localStorage
persist across tabs and across JFTerm restarts.

### Deferred import and graceful degradation

`webtab.py` and `webkit_session.py` perform `gi.require_version("WebKit", "6.0")`
and `from gi.repository import WebKit` only at import time of those
modules — never at app startup. If the import fails (system missing
`gir1.2-webkit-6.0`):

- The "New web tab…" item in the right-click `+` popover is shown but
  insensitive, with a tooltip naming the missing package.
- A startup or flash command matching `^https?://` falls back to spawning
  a terminal tab whose first line is an error message
  (`echo "JFTerm: WebKitGTK 6.0 not available; install gir1.2-webkit-6.0"`).
  This keeps project launches from silently dropping commands.

## Spawn paths

A new helper on the window:

```python
def _spawn_web_tab(
    self,
    group: Group,
    *,
    url: str,
    focus: bool = True,
    from_startup: bool = False,
    flash_name: str | None = None,
) -> WebTab: ...
```

parallels `_spawn_tab`. It constructs a `JFTermWebView`, builds a `WebTab`,
adds it to the stack, and applies the same focus/sidebar refresh dance.

### Right-click on `+`

Sidebar attaches a `Gtk.GestureClick(button=3)` to each group's `+` button,
emitting a new signal `new-web-tab-requested(Group, str url)`. The gesture
opens a `Gtk.PopoverMenu` with two items:

- **New terminal tab** — same as left-click; emits `new-tab-requested`.
- **New web tab…** — opens an `Adw.AlertDialog` with a single `Gtk.Entry`
  prefilled `https://`. On confirm, the dialog validates the URL against
  `^https?://` (case-insensitive, trimmed); on success it emits
  `new-web-tab-requested`. On failure the dialog stays open with an inline
  error.

If WebKit isn't available, the **New web tab…** item is insensitive (see
graceful degradation above).

### URL-detection rule

A single helper `is_web_url(text: str) -> bool` in a new
`src/jfterm/url_routing.py` returns `bool(re.match(r"https?://", text.strip(), re.IGNORECASE))`.
Used by every spawn path that takes user-authored command text.

### Startup commands

`_on_launch_project` checks each `StartupCommand.command` via `is_web_url`.
Matching commands route to `_spawn_web_tab(project, url=cmd.strip(), from_startup=True)`;
non-matching commands stay on the existing terminal path. Per-command
delays still apply.

The "skip if already running" check expands: a command is considered
already running if any existing tab in the project matches it — a
`TerminalTab` whose `launched_command == cmd` or a `WebTab` whose
`url == cmd.strip()`.

### Flash commands

`_on_flash_command_launched` checks `fc.command` via `is_web_url` *before*
calling `wrap_flash_command`. URL flash commands skip wrapping and route
to `_spawn_web_tab(project, url=fc.command.strip(), flash_name=fc.name,
focus=fc.focus_on_launch)`. Non-URL flash commands stay on the existing
terminal path. `keep_open_on_success` is meaningless for web tabs and is
ignored.

### Title plumbing

`JFTermWebView.title-changed` is wired in the window via the same pattern
as `JFTermTerminal.title-changed`: a guarded lambda checks the signal came
from the tab's *current* `web_view`. The handler updates `tab.title` using
the existing prefix logic:

- Flash web tab: `⚡ {flash_name}: {page_title}` (or `⚡ {flash_name}` if
  page title is empty).
- Startup web tab: `▶ {page_title}` (or `▶ {url}` if page title is empty).
- Ad-hoc web tab: `{page_title}` (or `{url}` if empty).

This preserves the existing visual language for command-launched tabs
without introducing a globe glyph for plain web tabs.

## Tab affordances

- **Status dot.** Web tabs do not show a status dot. Sidebar's row builder
  branches on `isinstance(tab, TerminalTab)` and only attaches a dot for
  terminal tabs.
- **Restart button.** Currently shown when `tab.launched_command` is
  truthy. New rule: shown only for `TerminalTab` instances with a truthy
  `launched_command`. WebTabs never show it.
- **Close / cycle / drag-drop / move-to.** Operate uniformly through
  `tab.widget`. No web-specific code paths.
- **Right-click on the page.** WebKitGTK's default context menu (back /
  forward / reload / copy / inspect element).
- **F12.** Toggles DevTools for the focused web view.

## Dependencies and packaging

- README's `apt install` line in the "Running" section gains
  `gir1.2-webkit-6.0`.
- README gains a "Web tabs" section under Features describing the four
  ways to open a web tab (startup `http(s)://`, flash `http(s)://`,
  right-click `+` → New web tab…), the shared cookie jar, and the apt
  dependency.
- `typings/gi/repository/WebKit.pyi` declares the module's surface as
  `Any`, mirroring the existing stubs for Gtk/Adw/Vte.
- `pyproject.toml` is unchanged.

## Tests

- `tests/test_models.py` — `TerminalTab` and `WebTab` are both `Tab`
  instances; defaults; `widget` property returns the right field.
- `tests/test_url_routing.py` — `is_web_url` cases: `https://x`,
  `HTTP://x`, leading/trailing whitespace, `httpsfoo`, empty string,
  `file:///etc/passwd`, `localhost:4000` (false — must include the scheme).

The web tab widget itself is not driven by tests, matching the existing
posture toward `JFTermTerminal` (which is also untested at the widget
level).
