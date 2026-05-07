"""Bearer token used to authenticate MCP clients to the embedded server.

The token lives in `~/.config/jfterm/mcp-token` (XDG_CONFIG_HOME aware) with
mode 0600. It is generated on first run and stable across launches; the
preferences UI offers a rotate button for users who want to invalidate the
current token (e.g. after granting a client and later revoking it).

Storing a static token in a same-UID-readable file does not defend against
attackers who already have user-level access — they could read the token
file, ptrace jfterm, or sniff loopback. The token mainly defeats accidental
exposure (logs, screenshots) and cross-origin browser attacks, and gates
remote MCP proxies that need an explicit secret.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from pathlib import Path


def default_path() -> Path:
    """Path to ~/.config/jfterm/mcp-token (XDG_CONFIG_HOME aware)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "jfterm" / "mcp-token"


def load_or_create(path: Path) -> str:
    """Return the stored token, generating one if the file does not exist.

    The file is always written with mode 0600. If an existing file has
    looser permissions, they are tightened on read.
    """
    if path.exists():
        token = path.read_text().strip()
        if token:
            _enforce_perms(path)
            return token
    return _generate(path)


def regenerate(path: Path) -> str:
    """Force-write a new token, replacing any existing one."""
    return _generate(path)


def _generate(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    # Write atomically with restrictive perms from the start: open the fd
    # ourselves so the file never exists with default perms.
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (token + "\n").encode())
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return token


def _enforce_perms(path: Path) -> None:
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return
    if mode != 0o600:
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
