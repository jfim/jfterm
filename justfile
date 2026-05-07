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
    uv run jfterm

# Sync dev dependencies.
sync:
    uv sync
