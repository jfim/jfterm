"""Shared persistent WebKit.NetworkSession for all web tabs.

Lazy-imports WebKit so JFTerm starts even if `gir1.2-webkit-6.0` is not
installed — the failure is surfaced when a web tab is actually requested
(see webtab.is_available()).
"""

from __future__ import annotations

import os
from typing import Any

_session: Any = None


def _data_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "jfterm", "webkit")


def _cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "jfterm", "webkit")


def get_session() -> Any:
    """Return the shared WebKit.NetworkSession, constructing it on first use."""
    global _session
    if _session is not None:
        return _session

    import gi

    gi.require_version("WebKit", "6.0")
    from gi.repository import WebKit

    data = _data_dir()
    cache = _cache_dir()
    os.makedirs(data, exist_ok=True)
    os.makedirs(cache, exist_ok=True)

    _session = WebKit.NetworkSession.new(data, cache)
    return _session
