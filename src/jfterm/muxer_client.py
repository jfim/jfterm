from __future__ import annotations

import os
import socket
from pathlib import Path

from jfterm import muxer_proto as mp


def socket_path() -> Path:
    """$XDG_RUNTIME_DIR/jfterm/muxer.sock, or /tmp/jfterm-$UID/ as a fallback."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path(f"/tmp/jfterm-{os.getuid()}")
    return base / "jfterm" / "muxer.sock"
