# MCP Server (issue #20) — MVP Design

## Goal

Expose JFTerm's tab/project model to Claude Code (or any MCP client) running
inside a JFTerm tab, so Claude can list projects, list tabs, spawn new tabs,
and restart startup-command tabs without the user having to swivel-chair
between Claude and JFTerm.

This spec covers an **MVP** focused on proving the MCP server itself works
end-to-end. I/O tools (`read_output`, `send_input`, `wait_for`) are
deliberately deferred to a follow-up spec.

## Scope

In:

- HTTP MCP server embedded in the JFTerm process, fixed port `7820`, no auth.
- Tools: `list_projects`, `list_tabs`, `spawn_tab`, `restart_tab`.

Out (deferred):

- `read_output` / `send_input` / `wait_for` (require an output mirror buffer,
  enough work to deserve their own spec).
- Preferences UI to enable/disable the server or change the port — for now
  the server starts unconditionally on the hardcoded port. A follow-up will
  add config and probably auth.
- Persistent tab IDs across JFTerm restarts. Tab IDs are session-scoped
  (the existing `Tab.id` uuid hex, regenerated on each launch).

## Architecture

### Transport

- Streamable HTTP MCP, single endpoint `POST/GET /mcp` on
  `http://127.0.0.1:7820/mcp`.
- No TLS. Localhost only — bind to `127.0.0.1`, never `0.0.0.0`.
- No auth header. Acceptable for MVP because the loopback bind already
  restricts access to local users; a malicious local user could already
  attach to the JFTerm process. Documented as a known limitation.
- User configures Claude Code once with:
  `claude mcp add --transport http jfterm http://127.0.0.1:7820/mcp`.

### Process model

- Server lives in the JFTerm process. New module `src/jfterm/mcp_server.py`.
- Uses the official `mcp` Python SDK (added to `pyproject.toml` runtime
  dependencies). The SDK provides Streamable HTTP server bindings and
  handles the JSON-RPC framing, `initialize`, capability negotiation, and
  tool schema export.
- The SDK runs on `asyncio`; JFTerm's UI runs on GTK's `GLib.MainLoop`.
  Bridge: spawn a daemon thread at app startup that runs
  `asyncio.run(server.run_streamable_http_async(host, port))`. Tool
  handlers execute on the asyncio thread and marshal any workspace
  mutation onto the GTK thread via `GLib.idle_add`, awaiting the result
  through a `concurrent.futures.Future`.
- Lifecycle: server thread starts in `JFTermApplication.do_startup` (or
  `JFTermWindow.__init__`, whichever is cleaner — pick the one with a
  stable handle to the `Workspace`). Stopped on app shutdown by
  cancelling the asyncio task and joining the thread with a short
  timeout.

### Boundary

A single class `MCPController` is the seam between the MCP server and the
GTK app. It exposes the four operations the tools need:

```
class MCPController:
    def list_projects(self) -> list[ProjectInfo]: ...
    def list_tabs(self, project_name: str | None) -> list[TabInfo]: ...
    def spawn_tab(self, project_name: str, command: str) -> TabInfo: ...
    def restart_tab(self, tab_id: str) -> None: ...
```

The real implementation holds a reference to `JFTermWindow` and bounces
each call through `GLib.idle_add`. Tool handlers in `mcp_server.py` only
ever talk to the controller, never to GTK directly. This keeps the GTK ↔
asyncio boundary in one place and makes the tool-dispatch layer testable
with a fake controller.

### Tab/project identification

- **Projects** identified by their `name` string in the API surface (matches
  what the user sees in the sidebar). The Unsorted bucket is addressed
  with the literal string `"Unsorted"` — same value its `name` attribute
  already uses.
- **Tabs** identified by `Tab.id` (the existing uuid4 hex). Session-scoped.

## Tool surface

All tools return JSON. Errors are returned as MCP tool errors with a
human-readable message; no special error codes for MVP.

### `list_projects() -> {projects: ProjectInfo[]}`

```
ProjectInfo = {
  name: str,         # also the addressable identifier
  directory: str,    # project's working directory
  tab_count: int,    # number of tabs currently in the project
}
```

Includes the Unsorted bucket as an entry with `name="Unsorted"` and
`directory=""`.

### `list_tabs(project_name?: str) -> {tabs: TabInfo[]}`

```
TabInfo = {
  id: str,                       # Tab.id
  title: str,                    # Tab.title (with the ▶/⚡ prefixes preserved)
  project: str,                  # owning group's name ("Unsorted" for the bucket)
  cwd: str | null,               # Tab.current_cwd
  busy: bool,                    # Tab.is_running (OSC 133 / tcgetpgrp fallback)
  launched_command: str | null,  # Tab.launched_command (null for plain shells)
}
```

If `project_name` is omitted, returns all tabs across all groups. If given,
filters to that group; unknown name → error.

### `spawn_tab(project_name: str, command: str) -> {tab: TabInfo}`

Spawns a new tab in the named project, equivalent to the existing
`JFTermWindow._spawn_tab(group, command=command, focus=False)` path.

- `project_name` required; `"Unsorted"` permitted.
- `command` required and non-empty. (A future iteration may allow a plain
  shell — out of scope for MVP.)
- Working directory follows existing behavior: project directory for
  Project groups, none for Unsorted.
- The new tab is **not** focused, so the MCP call doesn't yank the user's
  attention away from whatever they're doing.
- Returns the freshly-created `TabInfo`.

### `restart_tab(tab_id: str) -> {tab: TabInfo}`

Restart-in-place, equivalent to clicking the existing restart button on a
startup-command tab.

- Errors if `tab_id` is unknown.
- Errors if the tab has no `launched_command` (matches the existing UI
  guard at `window.py:209`).
- Returns the same `tab_id` with refreshed `TabInfo` after the restart
  begins (the new shell may not be fully spawned yet — `busy` reflects the
  current state at return time).

## Error handling

Returned as `isError: true` MCP tool results with a `text` content block
explaining the failure. No structured error codes for MVP. Cases:

- `project_name` not found.
- `tab_id` not found.
- `restart_tab` on a tab with no `launched_command`.
- `spawn_tab` with an empty `command`.

Internal exceptions (bugs) propagate to the MCP SDK's default handler,
which surfaces them as a tool error. Logged with `logging.exception`.

## Dependencies

Add to `pyproject.toml` runtime deps:

```
"mcp>=1.0",
```

Pure Python, installs cleanly under the existing `--system-site-packages`
venv setup.

## Testing

Two layers:

1. **Unit tests for the tool layer** (`tests/test_mcp_tools.py`).
   Construct an `MCPController` fake (in-memory list of fake projects /
   tabs, no GTK), instantiate the tool dispatch, and call each tool's
   handler directly. Assert returned shapes, error cases, and that
   mutations hit the fake controller. No HTTP, no asyncio.

2. **Smoke test for the HTTP server** (`tests/test_mcp_server.py`).
   Start the server against a fake controller on an ephemeral port, do a
   real MCP `initialize` + `tools/list` + `tools/call` round trip with
   the SDK's client, assert the same shapes. Confirms the
   asyncio/threading wiring and the SDK integration. Skipped if `mcp` is
   not importable (defensive — the dep is required, but PyGObject's
   system-venv setup occasionally surprises).

The GTK-bound `MCPController` adapter is exercised only manually for
MVP — wiring it into a unit test would require a running GTK app, and
the controller is mostly a thin marshaller. Follow-up plan: see if
`tests/test_window.py` (which already drives a real window) can host a
single end-to-end test that issues a `spawn_tab` against the live app.

## Known limitations / follow-ups

- No auth on localhost. A user with shell access to the same machine can
  drive your JFTerm. Acceptable for MVP; revisit alongside the prefs UI.
- Fixed port. Two JFTerm instances on the same machine will collide; the
  second one fails to start its MCP server (logged, app continues).
- No `read_output` / `send_input` / `wait_for`. These are the highest-value
  tools per the issue and will be the next spec. The output mirror
  buffer needed for them is not built in this MVP.
- Tab IDs are session-scoped — Claude must `list_tabs` after a JFTerm
  restart to rediscover IDs.
