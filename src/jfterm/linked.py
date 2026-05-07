from __future__ import annotations

import re
from dataclasses import dataclass

_PREFIX_RE = re.compile(r"^\s*linked:\s+(.*)$", re.IGNORECASE | re.DOTALL)
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


@dataclass(frozen=True)
class LinkedSpec:
    """A parsed `linked: <url|auto> <command>` string.

    `url is None` means auto-detect from the process's stdout. Otherwise
    `url` is the absolute http(s) URL to load immediately.
    `command` is the raw shell command, with all metacharacters preserved.
    """

    url: str | None
    command: str


def parse_linked(text: str) -> LinkedSpec | None:
    """Return a LinkedSpec if `text` matches `linked: <url|auto> <cmd>`, else None.

    The first whitespace-delimited token after `linked: ` must be either
    the literal `auto` (case-insensitive) or an absolute http(s) URL.
    Everything after that token is the raw command. Returns None for any
    string that does not match this shape.
    """
    m = _PREFIX_RE.match(text)
    if not m:
        return None
    rest = m.group(1).strip()
    if not rest:
        return None
    parts = rest.split(None, 1)
    if len(parts) != 2:
        return None
    head, command = parts[0], parts[1].strip()
    if not command:
        return None
    if head.lower() == "auto":
        return LinkedSpec(url=None, command=command)
    if _URL_RE.match(head):
        return LinkedSpec(url=head, command=command)
    return None
