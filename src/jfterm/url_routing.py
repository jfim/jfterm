from __future__ import annotations

import re

_WEB_URL_RE = re.compile(r"https?://", re.IGNORECASE)


def is_web_url(text: str) -> bool:
    """Return True if `text` (after stripping) starts with http:// or https://."""
    return bool(_WEB_URL_RE.match(text.strip()))
