"""WebKit-backed web tab widget. Imports WebKit lazily so JFTerm runs
without `gir1.2-webkit-6.0` installed; callers must first check
is_available() before constructing a JFTermWebView."""

from __future__ import annotations

WEBKIT_PACKAGE = "gir1.2-webkit-6.0"

_probe_result: bool | None = None


def is_available() -> bool:
    """True iff WebKit 6.0 GObject bindings are importable.

    Cached after first call. The result is process-stable: there is no
    point retrying within the same JFTerm run.
    """
    global _probe_result
    if _probe_result is not None:
        return _probe_result
    try:
        import gi

        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit  # noqa: F401
    except (ImportError, ValueError):
        _probe_result = False
    else:
        _probe_result = True
    return _probe_result
