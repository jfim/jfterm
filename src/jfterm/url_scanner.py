from __future__ import annotations

import re

# ANSI CSI sequences (e.g. \x1b[1;36m). We strip these before matching so
# URLs printed by dev servers with color/underline styling still match.
_ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]")
_URL_RE = re.compile(rb"https?://[^\s\x00-\x1f]+(?=[\s\x00-\x1f])")
# Trailing punctuation that's almost never part of an actual URL but often
# appears next to one in prose ("Visit http://x/."). Stripped from the tail.
_TRAILING_TRIM = b").,;:!?]>\"'"


_LOOPBACK_HOST = {
    "0.0.0.0": "127.0.0.1",
    "[::]": "[::1]",
}


def _rewrite_unspecified_host(url: str) -> str:
    """Rewrite 0.0.0.0 / [::] in the host part to loopback. Browsers
    refuse to navigate to unspecified bind addresses (Chrome's Private
    Network Access blocks 0.0.0.0; WebKit similarly rejects it), but
    servers commonly print them. Path/query/fragment are untouched.
    """
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    host = parts.hostname
    if host is None:
        return url
    bracketed_host = f"[{host}]" if ":" in host else host
    replacement = _LOOPBACK_HOST.get(bracketed_host) or _LOOPBACK_HOST.get(host)
    if replacement is None:
        return url
    # Rebuild netloc preserving userinfo and port.
    new_host = replacement
    userinfo = ""
    if parts.username is not None:
        userinfo = parts.username
        if parts.password is not None:
            userinfo += f":{parts.password}"
        userinfo += "@"
    port_part = f":{parts.port}" if parts.port is not None else ""
    new_netloc = f"{userinfo}{new_host}{port_part}"
    return urlunsplit((parts.scheme, new_netloc, parts.path, parts.query, parts.fragment))


class UrlScanner:
    """Buffers bytes from a terminal output stream and exposes the first
    http(s) URL it observes.

    Designed for the linked-flash `auto` mode: we cannot know in advance
    when a server will print its URL, and the URL may be split across
    several chunks delivered to `data-ready`. The buffer is capped so a
    long-running tail does not grow without bound; once a URL is found it
    is latched and `first_url()` returns it forever.
    """

    def __init__(self, max_buffer: int = 64 * 1024) -> None:
        self._buf = bytearray()
        self._url: str | None = None
        self._max_buffer = max_buffer

    def feed(self, data: bytes) -> None:
        if self._url is not None:
            return
        self._buf.extend(data)
        if len(self._buf) > self._max_buffer:
            # Keep only the tail; the in-flight prefix of a URL would be
            # at the END of the buffer, not the beginning.
            del self._buf[: len(self._buf) - self._max_buffer]
        clean = _ANSI_RE.sub(b"", bytes(self._buf))
        m = _URL_RE.search(clean)
        if not m:
            return
        url_bytes = m.group(0).rstrip(_TRAILING_TRIM)
        try:
            decoded = url_bytes.decode("utf-8")
        except UnicodeDecodeError:
            decoded = url_bytes.decode("utf-8", errors="replace")
        self._url = _rewrite_unspecified_host(decoded)

    def first_url(self) -> str | None:
        return self._url
