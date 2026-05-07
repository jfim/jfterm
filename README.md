# JFTerm

A terminal for people juggling multiple projects — per-project tab groups and
one-click access to each project's setup.

![JFTerm main window](images/main-window.png)

![Project preferences dialog](images/project-preferences.png)

## Features

- Per-project tab groups in a sidebar, plus an Unsorted bucket for ad-hoc tabs.
- One-click launch of a project's configured startup commands, with
  per-command delays, drag-and-drop reordering, and skipping of commands
  already running in the project.
- Flash commands: a per-project menu of one-off commands you can fire into
  a new tab from the sidebar.
- Restart button on tabs spawned from a startup command — kills the shell
  and re-runs the original command in place.
- Status dot per tab showing whether the shell is busy and whether the cwd
  matches the tab's project.
- Drag-and-drop to move tabs between projects.
- Built on GTK 4 / libadwaita with VTE 3.91 for the terminal itself.

## Running

System libraries (Ubuntu 24.04 — adjust package names for other distros):

    sudo apt install \
        gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-vte-3.91 \
        libvte-2.91-gtk4-0 \
        python3-gi python3-cairo

Then either install it as a desktop application (recommended — adds an
application-menu launcher that pins cleanly to the dock):

    just install

…or just launch from a source checkout:

    just run

`just install` puts a launcher shim at `~/.local/bin/jfterm`, a `.desktop`
file under `~/.local/share/applications/`, the icon under
`~/.local/share/icons/hicolor/scalable/apps/`, and an isolated venv at
`~/.local/share/jfterm/venv`. `just uninstall` reverses everything.

## Shell integration (OSC 7 + OSC 133)

JFTerm tracks each tab's cwd and "is a command running?" state from your
shell's escape sequences:

- **OSC 7** — current working directory. Drives the status-dot fill state
  and the deepest-match logic in the dot-click "Move to" menu.
- **OSC 133** — prompt and command boundaries. Drives the running-state
  color of the dot (blue while a command runs, grey at the prompt).

Without OSC 133, the dot falls back to polling `tcgetpgrp` every 250 ms,
which still works but with slightly higher latency. Without OSC 7, the
fill state stays out of sync with `cd`.

Add this to your `~/.bashrc` (or `~/.bash_profile`) to emit both:

    # JFTerm shell integration: OSC 7 (cwd) and OSC 133 (prompt/command markers).
    __jfterm_osc() {
        local exit_status=$?
        # OSC 133;D — previous command finished, with its exit status.
        printf '\033]133;D;%s\033\\' "$exit_status"
        # OSC 7 — current working directory as a file:// URI.
        printf '\033]7;file://%s%s\033\\' "$HOSTNAME" "$PWD"
    }
    PROMPT_COMMAND="__jfterm_osc${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
    # OSC 133;A at prompt start, ;B at prompt end. \[ \] keep line-wrapping correct.
    PS1='\[\e]133;A\e\\\]'"$PS1"'\[\e]133;B\e\\\]'
    # OSC 133;C — emitted after Enter, just before the command runs.
    PS0='\e]133;C\e\\'

Open a new terminal tab after editing, or `source ~/.bashrc`.

Zsh and fish ship their own equivalents (zsh: `precmd`/`preexec` hooks,
fish: `fish_prompt`/`fish_preexec`); the same four markers (`A` prompt
start, `B` prompt end, `C` command start, `D` command end with exit code)
plus OSC 7 are what JFTerm consumes.

## Development

Common dev tasks are wrapped as [`just`](https://github.com/casey/just)
recipes — run `just` with no args to list them. The most useful ones:

    just check       # everything CI runs: lint, fmt-check, typecheck, test
    just test        # pytest (extra args forwarded, e.g. `just test -v`)
    just lint        # uv run ruff check .
    just lint-fix    # uv run ruff check --fix .
    just fmt         # uv run ruff format .
    just typecheck   # uv run pyright
    just run         # launch the app

If you don't want to install `just`, the recipes are thin wrappers around
`uv run …` and can be invoked directly (e.g. `uv run pytest`,
`uv run ruff check .`).

Anything that runs through `uv run` needs the venv to inherit system
site-packages so it can import `gi` — building `pygobject` from source
needs `libgirepository-2.0-dev` and is slow. **Run this once before the
first `uv run`** — a plain `uv sync` auto-creates a venv *without* that
flag, which then fails with `ModuleNotFoundError: No module named 'gi'`:

    uv venv --system-site-packages --python /usr/bin/python3
    uv sync

If you delete `.venv`, repeat the `uv venv …` step before `uv sync`.

Pure-logic modules (models, persistence, matching) are covered by tests.
GUI behavior is verified manually.

## License

MIT — see [LICENSE](LICENSE).
