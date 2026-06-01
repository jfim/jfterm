# Terminal multiplexer (detach / reattach) — design

## Goal

Let JFTerm terminals outlive the GTK window. Today every shell is owned in-process
by `PtyProxy` and dies when the app closes, so closing JFTerm (e.g. to apply code
changes) destroys all running terminals. This design moves shell sessions into a
separate long-lived daemon (`jftermd`) so the window becomes a *viewer*: quitting
detaches, relaunching reattaches "as if nothing happened" — scrollback, running
TUIs, and shell status intact.

Scope: all PTY-backed tabs (plain shells, startup-command tabs, flash-command
tabs, and the terminal half of linked tabs). The daemon knows nothing about tabs,
groups, or webviews — those stay entirely client-side.

## Principles

- **The muxer is semantically dumb about JFTerm.** It owns PTY sessions: an id, a
  shell child, a replayable byte ring, a size, and a small cache of shell status.
  Tabs, groups, webviews, the linked-tab `Gtk.Paned` — all client concerns.
- **The shell's lifetime is decoupled from any client.** A session keeps running
  (and its ring keeps filling) whether or not a viewer is attached. A slow or
  crashed client must never stall the shell.
- **The protocol is the only contract.** TLV over a Unix domain socket. This is
  what lets the daemon be Rust while the client stays Python/GTK.

## Architecture

```
┌─ jfterm (GTK client, Python) ──┐         ┌─ jftermd (daemon, Rust) ────────┐
│ JFTermTerminal (Vte.Terminal)  │  TLV    │ Session{id}                     │
│   └ RemotePtyProxy ────────────┼──UDS────┼→  Pty (forkpty + shell child)   │
│        (same GObject signals)  │  socket │    EscParser (vte crate)        │
│ window / sidebar / persistence │         │    ChunkRing + StickyState      │
└────────────────────────────────┘         │    StatusCache{running,progress}│
   one client process, N windows           └─ N sessions, one per shell ─────┘
```

- **One daemon per user** at `$XDG_RUNTIME_DIR/jfterm/muxer.sock`; many sessions
  inside it. It is **self-spawned and double-forked** by the client (see
  Lifecycle), so it survives the app exiting. A single static binary — no
  interpreter or venv needed for the daemon.
- The daemon is the **source of truth for live sessions**. JFTerm's existing
  on-disk persistence remains the source of truth for *structure* (projects,
  groups, tab metadata, and the `session_id` each tab maps to).

### Why Rust for the daemon

- Forever-running, session-holding process: low idle footprint, no GC pauses,
  precise control over the growable chunk ring (manual buffer management is the
  core of the design).
- A single static binary is the cleanest possible target for the self-spawn
  model — the Python client just `exec`s `jftermd`.
- Alacritty's **`vte`** crate is exactly the escape-sequence tokenizer we need;
  the sticky-state machine, status cache, and action classifier become one
  `Perform` impl on top of it, removing most from-scratch parsing risk.

### Repository layout

`jftermd` lives in its **own repo** (`jfterm-muxer`) with its own `cargo` build
and CI — a Python change in JFTerm never triggers Rust tests, and vice versa. The
**protocol is the contract** between the two repos: this TLV spec plus
`proto_version` is owned canonically by the muxer repo (its README / a
`PROTOCOL.md`), and JFTerm codes against that version. The coupling is
deliberately narrow, so the boundary stays honest and the daemon remains reusable
by any terminal.

JFTerm depends only on the `jftermd` **binary being on `PATH`**: it `exec`s it for
the self-spawn (a single static binary, no interpreter/venv). JFTerm's
`just install` verifies `jftermd` is present and points at the muxer repo's build
rather than compiling Rust itself; the muxer repo owns its own
`cargo build --release` / install flow.

Stack: **Rust + `tokio`** (async `UnixListener`, `AsyncFd` on the PTY master,
`tokio::signal` for SIGCHLD reaping) + **`nix`** (`forkpty`, `TIOCSWINSZ`,
signals) + **`vte`** (parser).

`PtyProxy` and `OscScanner` are **reimplemented in Rust, not moved**; the Python
originals are retired once the daemon exists (the client no longer parses
anything).

## Session model (daemon-side)

Keyed by a `session_id` the client assigns. This is a **mutable per-tab pointer,
not the tab's own identity**: a terminal-bearing tab carries a `session_id` and
points at exactly one session at a time, distinct from its structural `Tab.id`.
Decoupling the two is what lets **restart** keep a tab while swapping in a fresh
shell under a new `session_id` — the old, still-draining session keeps its key
until the daemon reaps it, so the new shell never collides.

**v1 scope:** JFTerm does not persist tabs yet, so the **daemon's live session
list is the source of truth for what to restore**. On launch the client `LIST`s
sessions and adopts every one as a tab in **Unsorted**, attaching by `session_id`
and replaying. `session_id` is therefore a runtime field (assigned at OPEN,
rediscovered from `LIST` on relaunch), not persisted to disk. Persisting it
alongside tab structure — so sessions reattach into their original
project/group and position — is the deferred follow-up described under Launch
reconciliation.

A `Session` owns:

- **`Pty`** — `forkpty` + shell child; non-blocking master fd drained on the
  tokio loop. Drains continuously so the shell never blocks on a full pipe, even
  with no client attached.
- **`EscParser`** — `vte::Parser` driving a `Perform` impl that updates
  `StickyState`, the `StatusCache`, and the action classifier.
- **`ChunkRing`** — the replayable byte ring (see Buffer).
- **`StickyState`** — current visual state (SGR, DEC private modes, scroll
  region, charset, cursor color, OSC 7 cwd, OSC 0/2 title), serializable to a
  canonical re-assertion byte string.
- **`StatusCache`** — last semantic `running` (OSC 133) and `progress` (OSC 9;4)
  values. These drive JFTerm's status dot and never ride the ring. For shells
  without OSC 133 prompt marking, `running` falls back to a `tcgetpgrp(master) !=
  shell_pid` check the daemon polls on a timer; the first OSC 133 marker for a
  session wins and permanently disables that session's poll (mirroring the
  client's old fallback). The poll is **gated on an attached client** — the dot is
  only visible when attached — and pauses while detached. Either source updates
  `StatusCache` and pushes a `STATUS` frame, so the client never polls and needs
  no new wire message.
- **`client`** — the currently attached connection (v1: at most one; takeover on
  re-attach).

### Lifecycle

"OPEN" and "ATTACH" below name the two behaviors of the single `ATTACH_OR_OPEN`
binding frame (see Protocol), not separate wire frames.

- **Create (OPEN)** — `ATTACH_OR_OPEN` for an unknown `session_id` → daemon
  `forkpty`s the shell, sets `TERM=xterm-256color` and `COLORTERM=truecolor`
  (fixed emulator-capability env; JFTerm has no per-tab custom env today — if it
  ever does, those vars ride `ATTACH_OR_OPEN` next to `argv`/`cwd`), begins
  draining into the ring immediately.
- **Attach (ATTACH)** — `ATTACH_OR_OPEN` for a known `session_id` → replay
  handshake (see Protocol), then live frames.
- **Detach** — client disconnects (clean or crash). Session keeps running; ring
  keeps filling. No data lost.
- **Close (kill)** — `CLOSE{signal, grace_ms}` → daemon sends `signal` to the
  shell, drops the session from the attachable map immediately, then reaps in the
  background. If `grace_ms > 0` and the child has not exited by then, it escalates
  to `SIGKILL` before reaping. The escalation lives in the daemon because only it
  watches SIGCHLD — the client cannot observe when the child actually dies. Normal
  tab/window close uses `{SIGHUP, 0}` (no escalation); **restart** uses
  `{SIGTERM, 1500}`.
- **Shell exits while detached** — session enters a `dead` state retaining its
  ring until reattach or a grace timeout; reattach replays the final output +
  `EXIT`, then the session is dropped.
- **Daemon exits** after its last session ends (short grace timer), so it does not
  linger.

## Buffer: the replayable chunk ring

A ring of **growable chunks**, each a self-contained replay unit.

```
Chunk = { state_prologue: bytes,   # synthesized sticky state → cold-start fidelity
          data:           bytes }  # the (sanitized) output stream
```

Rules:

- **Soft 128 KB watermark, ground-state cut.** A chunk is cut at the next
  parser ground state (never mid-sequence) once it passes ~127 KB. A single
  unbroken sequence longer than the watermark (e.g. a large OSC 52 clipboard
  payload) lets the chunk grow past 128 KB until ground state — the cap is a
  target, not a hard bound.
- **State prologue per chunk.** At chunk creation, `StickyState` is serialized to
  canonical escape sequences and stored as the chunk's prologue. It is
  *synthesized*, not copied raw, so it can never contain a transient action.
- **Purge on clear.** On a full-screen clear / RIS (`ED 2`/`ED 3`, `\x1bc`), the
  current chunk is reset and all prior chunks are dropped — bounding memory and
  giving a clean replay base.
- **Replay = `first_selected.state_prologue + concat(selected.data)`.** A client
  asks for `want_chunks`; the default reaches the last purge boundary (full
  available scrollback). Capping below the purge boundary keeps modes/cwd/title
  correct via the prologue but trims top scrollback and assumes a home cursor at
  the first chunk — so capping is purely a memory/scrollback dial.

### Ring is replay-safe by construction

The ring stores only bytes whose replay re-creates **visual state**, never bytes
that perform an **action**. Live output reaches an attached client verbatim, but
the parser drops the following from the stored `data` (they are live-only):

- **OSC 52 (clipboard)** — replaying would clobber the clipboard on reconnect.
- **OSC 9 / OSC 777 desktop notifications** — replaying would re-fire stale
  notifications. (OSC 9;4 progress is consumed into `StatusCache`, not the ring.)
- **BEL** — replaying scrollback would machine-gun the bell.
- **Input-generating queries** — DSR (`\x1b[6n`), DA (`\x1b[c`, `\x1b[>c`),
  cursor-position reports. On replay VTE would generate responses; if routed back
  as `INPUT` they would inject spurious bytes into the shell. Must never replay.

### Replay vs. live is a daemon decision, not a client one

The client never needs to know "replay is done" — it feeds every `DATA` frame
into VTE identically. The boundary is enforced muxer-side by *what the bytes
contain*, fixed by ordering at attach:

1. The daemon snapshots the ring end, then sends prologue + selected chunk data up
   to that point — all **sanitized**, so a replayed BEL / OSC 52 / notification /
   DSR isn't in the bytes at all.
2. Everything produced *after* the snapshot streams **verbatim** as live `DATA`.

So a BEL only reaches VTE in a live frame, where it rings normally; a BEL already
in scrollback was stripped when stored and never replays. Output arriving *during*
the replay window is appended to the ring (sanitized) and forwarded to this client
as live (raw) once the replay frames flush — it counts as live, so its bell rings.
No in-band "end of replay" marker is required.

## Wire protocol (TLV over the Unix socket)

Every message is one TLV frame:

```
[u8 type][u32 length][value … length bytes]
```

The hot path (`DATA`, `INPUT`) carries **raw terminal bytes** in the value — zero
parsing. Structured control messages carry a small **JSON** value (low frequency;
readability beats packing).

One connection per session (natural per-session backpressure, no session-id on
every frame), plus one control connection per client.

**Control connection** (launch-time reconciliation):

| Type | Dir | Value |
|---|---|---|
| `HELLO` / `HELLO_OK` | ↔ | `{proto_version, daemon_version}` |
| `LIST` → `SESSIONS` | ↔ | `[{session_id, argv, cwd, running, has_client, created_at}]` |

**Session connection** (first frame binds it):

| Type | Dir | Value |
|---|---|---|
| `ATTACH_OR_OPEN` | C→D | `{session_id, cwd, argv, want_chunks, cols, rows}` — attach if exists, else open; race-free |
| `INPUT` | C→D | raw keystroke bytes |
| `RESIZE` | C→D | `{cols, rows}` |
| `CLOSE` | C→D | `{signal, grace_ms}` — signal the shell + drop session; daemon escalates to SIGKILL after `grace_ms` if still alive |
| `DATA` | D→C | raw output bytes (feed into VTE) |
| `STATUS` | D→C | `{running, progress}` — semantic dot state |
| `EXIT` | D→C | `{status}` — shell child exited |

Detach needs no frame — closing the socket *is* detach.

### Attach handshake (replay sequence)

1. Daemon sets winsize from `cols/rows`.
2. Sends the first selected chunk's `state_prologue` as a `DATA` frame.
3. Sends `data` of all selected chunks as `DATA` frames (sanitized; from the last
   purge boundary, capped by `want_chunks`).
4. Sends `STATUS{running, progress}`.
5. SIGWINCHes the shell's process group so any alt-screen TUI repaints.
6. Live `DATA` / `STATUS` / `EXIT` flow from there.

cwd needs no `STATUS` field — on reattach VTE re-parses the replayed OSC 7 and
fires `current-directory-uri-changed`, the path the dot already uses today.

### Backpressure

A slow/stuck client must never stall the shell. The daemon writes to clients
non-blocking with a bounded per-session out-queue; on overflow it **drops the
client** (forced detach) rather than blocking. The shell keeps draining into the
ring; the client reattaches and replays.

## Client integration (Python / GTK)

### `RemotePtyProxy` — drop-in for `PtyProxy`

A pure transport adapter with **zero JFTerm-authored parsing**, exposing the same
GObject signals (`data-ready`, `progress-changed`, `running-changed`,
`child-exited`):

- Owns one UDS session connection, watched via `GLib.unix_fd_add` (mirroring how
  `PtyProxy` watched the PTY fd today).
- Binds with `ATTACH_OR_OPEN{session_id=tab.session_id, …}`.
- Re-emits `DATA`→`data-ready`, `STATUS`→`progress-changed`/`running-changed`,
  `EXIT`→`child-exited`. `write()`→`INPUT`; size-allocate→`RESIZE`; tab
  close→`CLOSE`; socket drop→detach.

`terminal.py` change is tiny: swap `self._proxy = PtyProxy(cwd, [shell,"-l"])` for
`RemotePtyProxy(session_id=tab.session_id, cwd=…, argv=…)`. Every existing signal
handler stays as-is (`_on_proxy_data`→`feed`, etc.).

### Launch reconciliation

**v1 (no tab persistence):** on launch the client opens the control connection,
sends `LIST`, and **adopts every live session as a tab in Unsorted**, attaching
by `session_id` and replaying. Because tabs are not persisted, project/group
membership and order are not restored — a relaunched JFTerm shows all surviving
shells in Unsorted. The existing manual "launch project" flow is unchanged; its
spawned shells simply reappear in Unsorted after an app restart.

**v2 (tree-position restore, deferred):** once tabs persist their `session_id`
and structural placement, launch reconciles the union of persisted tabs and live
sessions, restoring each into its original group/position:

| Persisted tab? | Live session? | Action |
|---|---|---|
| yes | yes | **ATTACH** → replay ("as if nothing happened") |
| yes | no | **OPEN fresh** → re-run `launched_command` if any (daemon was restarted/rebooted; today's cold-start behavior) |
| no | yes | **Adopt orphan** → materialize a recovered tab in **Unsorted** and ATTACH (never silently lose a running shell) |

### Restart (client-side)

Restart keeps the tab — its `Tab.id`, sidebar row, group, and position — and
replaces the shell. The client sends `CLOSE{SIGTERM, 1500}` for the old
`session_id`, mints a new `session_id` and points the tab at it, binds a fresh
session with `ATTACH_OR_OPEN` (an OPEN, since the id is new) and re-runs
`launched_command`. The new terminal appears immediately while the old child dies
in the background — matching today's eager-swap UI — and because the new session
has a different id it never collides with the still-draining old one. (When tab
persistence lands in v2, the `session_id` swap is persisted **promptly**, not only
on the debounced background save, so a crash mid-restart cannot reload the stale
id and reattach to the dying shell.)

### Exit policy (client-side)

**v1:** closing the **window / quitting the app detaches** — it simply
disconnects the sockets without `CLOSE`, leaving every session running so they
reappear on relaunch (this is what makes the feature demonstrable). Closing a
single **tab** (the ✕, a shell exit, or the close-tab shortcut) sends
`CLOSE{SIGHUP, 0}` and kills that one shell. This is purely a client/UI decision;
the daemon supports both kill and detach.

**v2:** a richer split — an explicit "Quit, killing all terminals" alongside the
detaching default — once the UI for it exists.

### Daemon unreachable at launch

The client tries to self-spawn `jftermd` (Approach 1: `setsid` + double-fork,
atomic socket `bind()` + `flock` lockfile to resolve spawn races; unlink a stale
socket on `ECONNREFUSED` and re-spawn). If spawn fails, terminal creation surfaces
an error. (A later resilience option — `RemotePtyProxy` falling back to an
in-process `PtyProxy` with no persistence — is out of scope to avoid dual code
paths.)

## Muxer-side responsibilities (jftermd)

Consolidated checklist of what the daemon must implement; details live in the
sections above, and the client half is summarized under "Client integration."
jftermd lives in its own repo, so this section is the implementation contract.

- **Lifecycle & sessions:** `forkpty` a shell per `ATTACH_OR_OPEN` of an unknown
  id; set `TERM=xterm-256color` + `COLORTERM=truecolor`; drain the master
  continuously into the ring whether or not a client is attached; reap via
  SIGCHLD; enter `dead` (ring retained) on shell exit while detached; self-exit a
  short grace period after the last session ends.
- **CLOSE with escalation:** on `CLOSE{signal, grace_ms}`, send `signal`, drop the
  session from the attachable map immediately, reap in the background, and
  escalate to `SIGKILL` after `grace_ms` if the child has not exited. The daemon
  owns the escalation because only it observes SIGCHLD.
- **Chunk ring & sanitization:** 128 KB soft, ground-state-cut chunks; per-chunk
  synthesized `state_prologue`; purge-on-clear; strip OSC 52 / OSC 9 / OSC 777 /
  BEL / DSR / DA / cursor-reports from *stored* data while passing them live.
- **Replay ordering:** snapshot ring end at attach, send prologue + sanitized
  chunk data, then stream live verbatim (see "Replay vs. live").
- **Status:** maintain `StatusCache` from OSC 133 + OSC 9;4; for shells without
  OSC 133, fall back to an **attach-gated** `tcgetpgrp` poll that the first 133
  marker permanently disables; push `STATUS` frames (the client never polls).
- **Protocol:** TLV framing; control connection (`HELLO`/`LIST`); per-session
  connection (`ATTACH_OR_OPEN`/`INPUT`/`RESIZE`/`CLOSE` ↔ `DATA`/`STATUS`/`EXIT`);
  validate `proto_version` in `HELLO` and reject mismatches.
- **Concurrency & robustness:** bounded per-session out-queue, drop slow clients
  (forced detach) without stalling the shell; most-recent-wins takeover on a
  second attach; atomic socket `bind()` + `flock` to resolve spawn races; unlink a
  stale socket on `ECONNREFUSED`; SIGWINCH the shell's process group on
  resize/attach.
- **Security:** socket under `$XDG_RUNTIME_DIR/jfterm/` (`0700`), socket `0600`;
  single-user, no in-band auth.

## Error handling & edge cases

| Case | Handling |
|---|---|
| Daemon crash (whole process) | All PTYs die with it. Clients see EOF on every session socket → mark tabs disconnected; command tabs offer restart via the existing ↻, plain shells show "session lost". Next action self-spawns a fresh daemon; persisted tabs reconcile as OPEN fresh. |
| Shell exits while detached | `dead` session retains its ring until reattach or grace timeout; reattach replays final output + `EXIT`, then drops. |
| Spawn race (two windows) | Atomic socket `bind()` + `flock`; loser connects to the winner. |
| Stale socket file | `connect()` → `ECONNREFUSED` → unlink + re-spawn. |
| Slow/stuck client | Bounded out-queue; overflow → drop client (forced detach); shell unaffected. |
| Second attach to a live session | Most-recent-wins takeover: new `ATTACH_OR_OPEN` kicks the prior client (which sees a detach). Avoids "session busy" dead-ends after a client crash. |
| Malformed frame / proto mismatch | Bad frame → close that connection (= detach); reattach recovers. `HELLO` carries `proto_version`; mismatch → reject. |
| Resize while detached | Winsize holds last value; reattach sends real `RESIZE` → daemon updates + SIGWINCH corrects any TUI that queried the stale size. |
| Giant single sequence (OSC 52 dump) | Chunk grows past the 128 KB soft cap until ground state. |

**Security:** the socket lives in `$XDG_RUNTIME_DIR/jfterm/` (user-private,
`0700`), socket `0600`. Single-user; filesystem perms suffice — no in-band auth.

## Testing strategy

Risk is concentrated in pure, loop-agnostic logic. Build that test-first; reserve
integration tests for the I/O loop and sockets.

**Unit — pure logic (Rust `cargo test`):**

- `ChunkRing`: ground-state cut at the 128 KB soft watermark; oversized chunk
  absorbs a giant sequence; purge-on-clear drops prior chunks;
  `replay = first.state_prologue + concat(data)`; `want_chunks` capping keeps
  modes correct but trims top scrollback.
- `StickyState` / parser: synthesized prologue re-creates SGR / DEC modes / scroll
  region / charset / OSC 7 / title; sequences split across feed boundaries don't
  break ground-state detection; the action classifier drops
  OSC 52 / 9 / 777 / BEL / DSR / DA / cursor-report from the ring while passing
  them live.
- `StatusCache`: latest running/progress tracked; `STATUS` snapshot reflects
  them; the `tcgetpgrp` fallback drives `running` until the first OSC 133 marker,
  which then disables that session's poll.

**Correctness oracle — `vt100` (Rust, dev/test only):** feed an original byte
stream into `vt100` → grid A; feed our replay (prologue + sanitized data from the
purge boundary) into a fresh `vt100` → grid B; **assert A == B**. Proves replay
fidelity without a real terminal — the single highest-leverage test for the buffer
design.

**Integration — real daemon, real shells** (temp `$XDG_RUNTIME_DIR`, throwaway
socket, `bash --norc`):

- Lifecycle: `OPEN` drains into the ring before any attach; `ATTACH` replays;
  `CLOSE{SIGHUP,0}` reaps without escalation while `CLOSE{SIGTERM,grace}` escalates
  to SIGKILL when the child ignores SIGTERM; socket drop detaches without killing;
  shell-exit-while-detached retains a `dead` session whose reattach replays final
  output + `EXIT`.
- Protocol: TLV encode/decode round-trip; malformed frame closes the connection;
  `proto_version` mismatch rejected; `ATTACH_OR_OPEN` attaches-vs-opens.
- Concurrency: backpressure drops a stalled client without disturbing the shell;
  spawn race resolves to one daemon; second attach takes over the first.

**Manual acceptance (the actual promise):** close JFTerm → edit code → reopen →
terminals intact; `vim`/`htop` repaint cleanly; clipboard *not* clobbered on
reattach; a server that crashed while detached still shows its final output.

## Out of scope (v2+)

- Multiple simultaneous viewers of one session (tmux-style mirroring).
- In-process `PtyProxy` fallback when the daemon is unavailable.
- Cross-machine / SSH attach.
- Sixel/graphics replay (passed live if VTE supports it; not stored in the ring).
- Persisting sessions across reboot (PTYs die with the daemon; reconciliation
  re-runs `launched_command` for command tabs).
