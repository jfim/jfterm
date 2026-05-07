# Desktop Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make jfterm installable as a first-class user-local desktop application via `just install` — pinnable to the dock with proper icon grouping, launched without `uv run`.

**Architecture:** Ship four artifacts in the repo (icon SVG, `.desktop` file, launcher shim, justfile recipes). On install, create a `--system-site-packages` venv at `~/.local/share/jfterm/venv`, install jfterm into it, and place the launcher + desktop entry + icon under the appropriate XDG user directories.

**Tech Stack:** GTK4/PyGObject (existing), uv (venv + install), just (recipes), POSIX shell (launcher shim), SVG (icon), freedesktop `.desktop` entry.

**Spec:** [docs/superpowers/specs/2026-05-06-desktop-packaging-design.md](../specs/2026-05-06-desktop-packaging-design.md)

---

## File Structure

New files:

```
data/dev.jfim.jfterm.desktop                 # freedesktop application entry
data/icons/dev.jfim.jfterm.svg               # 128×128 G2 icon (slate + JF white + >_ green)
packaging/jfterm.sh                          # 2-line launcher shim → venv python -m jfterm
```

Modified files:

```
justfile                                     # add `install` and `uninstall` recipes
```

No tests are added: the artifacts are static files and shell glue. Verification is end-to-end (`just install` → confirm paths, launch app, `just uninstall` → confirm cleanup).

---

## Task 1: Add the application icon

**Files:**
- Create: `data/icons/dev.jfim.jfterm.svg`

- [ ] **Step 1: Create the SVG file**

Create `data/icons/dev.jfim.jfterm.svg` with this exact content:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
  <rect width="128" height="128" rx="22" fill="#1a1a24"/>
  <text x="64" y="82" text-anchor="middle"
        font-family="ui-monospace, 'JetBrains Mono', 'DejaVu Sans Mono', 'Fira Code', monospace"
        font-weight="700" font-size="44" fill="#c9d1d9">JF<tspan fill="#7ee787">&gt;_</tspan></text>
</svg>
```

- [ ] **Step 2: Visually verify the icon**

Run: `xdg-open data/icons/dev.jfim.jfterm.svg` (or open the file in any image viewer).

Expected: A rounded slate-dark square showing `JF>_` centered. `JF` is light gray, `>_` is terminal-green. No clipping, no font fallback boxes.

If the system has neither JetBrains Mono nor DejaVu Sans Mono, the generic `monospace` family at the end of the list ensures it still renders — verify the glyphs are not missing.

- [ ] **Step 3: Commit**

```bash
git add data/icons/dev.jfim.jfterm.svg
git commit -m "feat(packaging): add application icon"
```

---

## Task 2: Add the desktop entry

**Files:**
- Create: `data/dev.jfim.jfterm.desktop`

- [ ] **Step 1: Create the desktop entry**

Create `data/dev.jfim.jfterm.desktop` with this exact content:

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

- [ ] **Step 2: Validate the entry with `desktop-file-validate`**

Run: `desktop-file-validate data/dev.jfim.jfterm.desktop`

Expected: No output (validator is silent on success).

If `desktop-file-validate` is not installed, install it via `sudo apt install desktop-file-utils` or skip — the file conforms to the spec and will be re-validated by `update-desktop-database` at install time.

- [ ] **Step 3: Commit**

```bash
git add data/dev.jfim.jfterm.desktop
git commit -m "feat(packaging): add desktop entry"
```

---

## Task 3: Add the launcher shim

**Files:**
- Create: `packaging/jfterm.sh`

- [ ] **Step 1: Create the shim**

Create `packaging/jfterm.sh` with this exact content:

```sh
#!/bin/sh
exec "$HOME/.local/share/jfterm/venv/bin/python" -m jfterm "$@"
```

- [ ] **Step 2: Make it executable in the repo**

Run: `chmod +x packaging/jfterm.sh`

This way `git` records the executable bit; `install -Dm755` in the install recipe will set it on the installed copy regardless, but tracking it in the repo lets developers run `./packaging/jfterm.sh` against an existing install for testing.

- [ ] **Step 3: Verify shellcheck cleanliness (if available)**

Run: `shellcheck packaging/jfterm.sh`

Expected: No output. (Skip this step if `shellcheck` is not installed.)

- [ ] **Step 4: Commit**

```bash
git add packaging/jfterm.sh
git commit -m "feat(packaging): add launcher shim"
```

---

## Task 4: Add `just install` and `just uninstall` recipes

**Files:**
- Modify: `justfile`

- [ ] **Step 1: Read the current justfile**

Read `justfile` to confirm the section ordering before editing.

- [ ] **Step 2: Append the install/uninstall recipes**

Append these recipes to the end of `justfile`:

```just

# --- Desktop install (user-local) ---

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

Notes:
- `install_dir`, `bin_dir`, etc. are top-level just variables; they must appear before any recipe that uses them. If `justfile` already has variables, place these alongside them; if not, the position before the new recipes is fine because just resolves variables globally.
- The `-` prefix on `update-desktop-database` and `gtk-update-icon-cache` makes the recipe tolerant of those tools being absent (some minimal installs).

- [ ] **Step 3: Verify `just --list` shows the new recipes**

Run: `just --list`

Expected output includes lines like:
```
    install                 # Install jfterm as a desktop application (user-local).
    uninstall               # Remove the desktop install.
```

If `just` reports a parse error, re-check indentation (recipe bodies must use a single tab or 4 spaces consistently — match the rest of the file).

- [ ] **Step 4: Commit**

```bash
git add justfile
git commit -m "feat(packaging): add install/uninstall recipes"
```

---

## Task 5: End-to-end install verification

This task does **not** modify the repo. It verifies the installation works on the developer's machine and exists as a sanity gate before declaring the feature done. Skip the dock-pinning steps if not running on a GNOME desktop.

- [ ] **Step 1: Run a clean install**

Run: `just install`

Expected: No errors. Final line: `jfterm installed. Launch from your application menu or run: jfterm`

- [ ] **Step 2: Verify all four installed paths exist**

Run:
```bash
ls -la \
  "$HOME/.local/bin/jfterm" \
  "$HOME/.local/share/applications/dev.jfim.jfterm.desktop" \
  "$HOME/.local/share/icons/hicolor/scalable/apps/dev.jfim.jfterm.svg" \
  "$HOME/.local/share/jfterm/venv/bin/python"
```

Expected: All four paths listed without "No such file or directory". `~/.local/bin/jfterm` should have mode `-rwxr-xr-x`.

- [ ] **Step 3: Launch from the shim and confirm the window opens**

Run: `jfterm &` (must be in a fresh shell so PATH includes `~/.local/bin`; `hash -r` if needed).

Expected: A jfterm window opens. Close it.

If `jfterm: command not found`, `~/.local/bin` is not on PATH for this user. This is a user-environment issue, not a packaging bug — note it but the install is still correct.

- [ ] **Step 4: Verify the launcher appears in the application menu (GNOME)**

Press the Super key, type "jfterm". Expected: a launcher with the new G2 icon appears.

- [ ] **Step 5: Verify icon grouping**

Launch jfterm from the application menu. The taskbar/dock entry should display the same icon (not a generic Python or "?" icon). Right-click → Pin to Dash. Close the window. Click the pinned icon. Expected: jfterm relaunches.

If the taskbar shows a different/generic icon, check that the `StartupWMClass` in the installed `.desktop` file matches the GTK `application_id` (`dev.jfim.jfterm`) — this is the exact match required for GNOME to associate the launcher with the running window.

- [ ] **Step 6: Run the uninstall**

Run: `just uninstall`

Expected: Final line `jfterm uninstalled.`

- [ ] **Step 7: Verify all four paths are gone**

Run:
```bash
ls "$HOME/.local/bin/jfterm" \
   "$HOME/.local/share/applications/dev.jfim.jfterm.desktop" \
   "$HOME/.local/share/icons/hicolor/scalable/apps/dev.jfim.jfterm.svg" \
   "$HOME/.local/share/jfterm" 2>&1
```

Expected: Four "No such file or directory" lines.

- [ ] **Step 8: Re-run install to confirm idempotence**

Run: `just install` twice. Expected: second run succeeds without errors (uv reuses the existing venv, `install -D` overwrites the targets, cache refresh tools rerun).

- [ ] **Step 9: Final cleanup decision**

Either leave jfterm installed (it's the user's machine, this is the intended end state) or run `just uninstall` once more. No commit — this task only verifies.

---

## Self-Review

- **Spec coverage:** Icon (Task 1), `.desktop` file (Task 2), launcher shim (Task 3), justfile recipes with both install paths and tool-tolerance (Task 4), all six acceptance criteria from the spec (Task 5). Future-Flatpak and risk sections in the spec are informational, no implementation needed.
- **Placeholders:** None. Every code block is final content.
- **Type/name consistency:** App-id `dev.jfim.jfterm` is identical across icon filename, desktop filename, `Icon=` field, and `StartupWMClass=`. Install paths in justfile match the launcher shim's hardcoded `~/.local/share/jfterm/venv/bin/python`.
