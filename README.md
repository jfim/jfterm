# JFTerm

A terminal for GNOME that uses tabs and per-project groupings. Uses VTE for the
actual terminal.

See [docs/superpowers/specs/2026-05-06-jfterm-v1-design.md](docs/superpowers/specs/2026-05-06-jfterm-v1-design.md)
for the full design and [docs/superpowers/plans/2026-05-06-jfterm-v1.md](docs/superpowers/plans/2026-05-06-jfterm-v1.md)
for the implementation plan.

## Running

Requires Python 3.12+ and `uv`, plus the GTK 4 / libadwaita / VTE 3.91 system
libraries. On Ubuntu 24.04:

    sudo apt install \
        gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-vte-3.91 \
        libvte-2.91-gtk4-0 \
        python3-gi python3-cairo

The project relies on the apt-installed PyGObject + VTE bindings (building
`pygobject` from source needs `libgirepository-2.0-dev` and is slow). The
venv must be created with `--system-site-packages` so it can import the
system `gi`. **Run this once before the first `uv run`** — a plain `uv sync`
auto-creates a venv *without* that flag, which then fails with
`ModuleNotFoundError: No module named 'gi'`:

    uv venv --system-site-packages --python /usr/bin/python3
    uv sync

Then:

    uv run python -m jfterm

If you delete `.venv`, repeat the `uv venv …` step before `uv sync`.

For the prompt-running indicator (blue dot) to be most accurate, configure your
shell to emit OSC 7 (cwd) and OSC 133 (prompt/command markers). The design doc
has a bash snippet that does this. Without OSC 133 the indicator falls back to
polling `tcgetpgrp` every 250 ms, which still works but with slightly higher
latency.

## Development

    uv run pytest -v

Pure-logic modules (models, persistence, matching) are covered by tests.
GUI behavior is verified manually.
