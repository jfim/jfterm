# Desktop packaging — local install

**Status:** Approved
**Date:** 2026-05-06
**Scope:** Make jfterm installable as a first-class desktop application on the user's own Linux machine — pinnable to the dock, properly icon-grouped, launched without `uv run`.

## Goal

After running `just install`, jfterm should:

- Appear in the GNOME application launcher / Activities overview as "jfterm" with the project's icon.
- Be pinnable to the dock; pinned icon launches the app and groups with the running window.
- Launch fast (no per-launch dependency sync).
- Run from a stable install path that doesn't depend on the source checkout location.

`just uninstall` reverses everything cleanly.

## Out of scope

- PyPI distribution.
- Flatpak / `.deb` / AUR packaging.
- System-wide install (`/usr/local`). Local user install only.
- Running on non-Linux platforms.

A future Flatpak path is acknowledged (see *Future* below) so the artifacts we add now are reusable, but no Flatpak work happens in this spec.

## Background: why not the obvious approaches

Two paths were ruled out during brainstorming:

**Pinning `uv run python -m jfterm` directly.** GNOME pins applications registered via `.desktop` files, not arbitrary commands. Even with a hack, the launcher would show a generic Python icon, fail to group with the running GTK window (no `StartupWMClass`), and incur a dep-sync delay on every launch.

**`uv tool install`.** Clean in principle, but jfterm depends on PyGObject, which on this Ubuntu system has no Linux wheels on PyPI for current versions. `uv tool install` would trigger a meson build from source, requiring `libgirepository1.0-dev` and friends that aren't installed. Even if the headers were present, every reinstall would do a 1–2 minute source build. `uv tool install` also has no `--system-site-packages` flag, so it can't reuse the system `python3-gi`.

The chosen approach uses a system-site-packages venv at a stable location, plus a small launcher shim — same mechanism that already works for the dev environment.

## Architecture

```
~/.local/share/jfterm/venv/         # isolated venv with --system-site-packages
~/.local/bin/jfterm                 # 2-line shell shim → venv python -m jfterm
~/.local/share/applications/dev.jfim.jfterm.desktop
~/.local/share/icons/hicolor/scalable/apps/dev.jfim.jfterm.svg
```

**Why these locations:** all four are XDG-standard user-local paths. No `sudo` required. `update-desktop-database` and `gtk-update-icon-cache` know to scan them.

**Why a system-site-packages venv:** lets the venv's `import gi` resolve to the system `python3-gi` package, which is the only practical source of PyGObject on this distro. The venv still isolates jfterm's own dependencies from system Python.

**Why a shell shim instead of `Exec=` pointing directly at venv python:** lets us put `jfterm` on PATH for terminal use too, keeps the `.desktop` `Exec=` short and stable, and makes the install relocatable in the future without editing the `.desktop` file.

## Files added to the repo

```
data/
  dev.jfim.jfterm.desktop           # desktop entry, committed
  icons/
    dev.jfim.jfterm.svg             # the G2 icon (slate #1a1a24 + JF white + >_ green)
packaging/
  jfterm.sh                         # launcher shim, installed to ~/.local/bin/jfterm
```

`justfile` gains `install` and `uninstall` recipes.

### Icon (`data/icons/dev.jfim.jfterm.svg`)

128×128 viewBox, single SVG, no embedded fonts (uses generic `monospace` family so it renders in any GTK environment). Components:

- Rounded square plate, fill `#1a1a24`, corner radius 22.
- Centered text `JF>_` in a monospace family, weight 700, size 44.
- `JF` in `#c9d1d9` (soft white), `>_` in `#7ee787` (terminal green).

This is the G2 design selected during brainstorming.

### Desktop entry (`data/dev.jfim.jfterm.desktop`)

```ini
[Desktop Entry]
Type=Application
Name=jfterm
GenericName=Terminal
Comment=Terminal with project-grouped tabs
Exec=jfterm
Icon=dev.jfim.jfterm
Terminal=false
Categories=System;TerminalEmulator;
StartupWMClass=dev.jfim.jfterm
StartupNotify=true
Keywords=shell;prompt;command;commandline;cmd;
```

`StartupWMClass=dev.jfim.jfterm` matches the GTK application id, which is what makes the running window group correctly under the pinned launcher icon.

### Launcher shim (`packaging/jfterm.sh`)

```sh
#!/bin/sh
exec "$HOME/.local/share/jfterm/venv/bin/python" -m jfterm "$@"
```

Two lines. No source-checkout dependency. Forwards arguments and signals via `exec`.

### `justfile` recipes

```just
install_dir   := `echo "$HOME/.local/share/jfterm"`
bin_dir       := `echo "$HOME/.local/bin"`
apps_dir      := `echo "$HOME/.local/share/applications"`
icon_dir      := `echo "$HOME/.local/share/icons/hicolor/scalable/apps"`

# Install jfterm as a desktop application (user-local).
install:
    uv venv --system-site-packages --python 3.12 "{{install_dir}}/venv"
    uv pip install --python "{{install_dir}}/venv/bin/python" .
    install -Dm755 packaging/jfterm.sh "{{bin_dir}}/jfterm"
    install -Dm644 data/dev.jfim.jfterm.desktop "{{apps_dir}}/dev.jfim.jfterm.desktop"
    install -Dm644 data/icons/dev.jfim.jfterm.svg "{{icon_dir}}/dev.jfim.jfterm.svg"
    -update-desktop-database "{{apps_dir}}"
    -gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor"
    @echo "jfterm installed. Launch from your application menu or run: jfterm"

# Remove the desktop install.
uninstall:
    rm -f "{{bin_dir}}/jfterm"
    rm -f "{{apps_dir}}/dev.jfim.jfterm.desktop"
    rm -f "{{icon_dir}}/dev.jfim.jfterm.svg"
    rm -rf "{{install_dir}}"
    -update-desktop-database "{{apps_dir}}"
    -gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor"
    @echo "jfterm uninstalled."
```

`install` is idempotent: re-running upgrades the venv (uv handles existing-venv reuse), overwrites the desktop file and icon, and refreshes the caches. `update-desktop-database` and `gtk-update-icon-cache` are prefixed with `-` so install still succeeds on systems where they're missing.

## Acceptance criteria

After `just install` on a clean machine (with GNOME and `python3-gi`):

1. `jfterm` on PATH launches the app from any directory.
2. The application appears in the GNOME launcher with the new icon and name "jfterm".
3. Launching from the dashboard opens a window whose taskbar entry shares the launcher icon (no duplicate "generic Python" entry).
4. Pinning the running window to the dock and clicking the pinned icon later launches a fresh instance.
5. Startup time from click to visible window is comparable to `uv run jfterm` minus the dep-sync overhead.
6. `just uninstall` removes all four installed paths and the launcher disappears from the application menu after a session restart (or `update-desktop-database` run, which the recipe does).

## Risks and notes

- **System `python3-gi` version.** `--system-site-packages` ties the venv to whatever PyGObject is on the system. If a system upgrade ships an incompatible `gi`, the install would break until the user re-runs `just install` (which would still pick up the new system version). This matches today's dev workflow, so no regression.
- **`update-desktop-database` / `gtk-update-icon-cache` absent.** Some minimal installs lack these tools. The recipe tolerates their absence; the user may need to log out/in for the entry to appear in those cases.
- **Different `python3` versions.** `uv venv --python 3.12` is a hard pin. If the system Python is newer (3.13+) and `python3-gi` only ships for that, the venv creation may need adjusting. Defer until it actually breaks.
- **Multiple checkouts running `install`.** Each `just install` overwrites the previous one — there's only one global install location. This is intentional.

## Future: Flatpak

When the project is ready for wider distribution, Flatpak is the right path (PyPI is a poor fit because of the PyGObject build issue described above). The artifacts added in this spec — the `.desktop` file and the SVG icon — are the same ones a Flatpak manifest references, so this work feeds directly into that path. No design decisions in this spec block or complicate a future Flatpak.
