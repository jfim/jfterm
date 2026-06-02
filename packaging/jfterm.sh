#!/bin/sh
# Ensure the user-local bin dir (where `just install` puts jftermd) is on PATH,
# so the app can spawn the muxer daemon even when launched from the desktop
# menu, where the session PATH may not include it.
PATH="$HOME/.local/bin:$PATH"
export PATH
exec "$HOME/.local/share/jfterm/venv/bin/python" -m jfterm "$@"
