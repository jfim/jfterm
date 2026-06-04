# Run `just` with no args to see all recipes.
# Install just: https://github.com/casey/just (cargo install just / apt install just)

default:
    @just --list

# Run every check CI runs.
check: lint fmt-check typecheck test

# Lint with ruff.
lint:
    uv run ruff check .

# Auto-fix lint issues.
lint-fix:
    uv run ruff check --fix .

# Reformat the codebase.
fmt:
    uv run ruff format .

# Verify formatting without writing changes.
fmt-check:
    uv run ruff format --check .

# Static type-check with pyright.
typecheck:
    uv run pyright

# Run the test suite.
test *args:
    uv run pytest {{args}}

# Launch the app.
run:
    uv run python -m jfterm

# Create the dev virtualenv (with system site packages for gi/PyGObject).
venv:
    uv venv --system-site-packages --python-preference only-system
    uv sync

# Sync dev dependencies.
sync:
    uv sync

# --- Desktop install (user-local) ---

install_dir   := `echo "$HOME/.local/share/jfterm"`
bin_dir       := `echo "$HOME/.local/bin"`
apps_dir      := `echo "$HOME/.local/share/applications"`
icon_dir      := `echo "$HOME/.local/share/icons/hicolor/scalable/apps"`
prefix_dir    := `echo "$HOME/.local"`

# Git remote for the jftermd muxer daemon (override with JFTERM_MUXER_REPO).
muxer_repo    := env_var_or_default("JFTERM_MUXER_REPO", "https://github.com/jfim/jfterm-muxer")

# Build and install the jftermd muxer daemon to ~/.local/bin (cargo required).
install-muxer:
    @command -v cargo >/dev/null 2>&1 || { echo "error: 'cargo' not found on PATH. Install Rust (https://rustup.rs) or add ~/.cargo/bin to PATH, then re-run."; exit 1; }
    cargo install jftermd --git "{{muxer_repo}}" --locked --force --root "{{prefix_dir}}"
    @echo "jftermd installed to {{bin_dir}}/jftermd"

# Install jfterm as a desktop application (user-local), incl. the jftermd daemon.
install: install-muxer
    uv venv --system-site-packages --python-preference only-system "{{install_dir}}/venv"
    uv pip install --reinstall --python "{{install_dir}}/venv/bin/python" .
    install -Dm755 packaging/jfterm.sh "{{bin_dir}}/jfterm"
    install -Dm644 data/dev.jfim.jfterm.desktop "{{apps_dir}}/dev.jfim.jfterm.desktop"
    install -Dm644 data/icons/dev.jfim.jfterm.svg "{{icon_dir}}/dev.jfim.jfterm.svg"
    -update-desktop-database "{{apps_dir}}"
    -gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor"
    @echo "jfterm installed. Launch from your application menu or run: jfterm"

# Remove the desktop install.
uninstall:
    rm -f "{{bin_dir}}/jfterm"
    rm -f "{{bin_dir}}/jftermd"
    rm -f "{{apps_dir}}/dev.jfim.jfterm.desktop"
    rm -f "{{icon_dir}}/dev.jfim.jfterm.svg"
    rm -rf "{{install_dir}}"
    -update-desktop-database "{{apps_dir}}"
    -gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor"
    @echo "jfterm uninstalled."
