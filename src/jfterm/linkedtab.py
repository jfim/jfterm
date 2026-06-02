# src/jfterm/linkedtab.py
"""Composite view for `linked:` flash tabs: a vertical Gtk.Paned with a
JFTermWebView on top and a JFTermTerminal on the bottom.

Imports WebKit lazily via `webtab.is_available()`; callers must check
`is_available()` before constructing a JFTermLinkedView. WebKit and VTE
are both required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gi.repository import Gtk

from jfterm.terminal import JFTermTerminal
from jfterm.webtab import JFTermWebView, is_available  # re-export

if TYPE_CHECKING:
    from jfterm.muxer_client import MuxerClient

# Width (in pixels) the webview pane shrinks to when the process exits
# non-zero. Small enough to be effectively hidden, large enough that the
# Gtk.Paned divider is still visible and drag-grabbable so the user can
# pull the (now-broken) browser back into view if they want to.
COLLAPSED_WEBVIEW_PX = 4


class JFTermLinkedView(Gtk.Paned):
    """Vertical Paned: webview top, terminal bottom. Default split is
    roughly 80% webview / 20% terminal; the divider is user-draggable.
    """

    def __init__(
        self,
        muxer: MuxerClient,
        session_id: str,
        *,
        cwd: str | None,
        send_after_spawn: str | None,
        appearance: Any,
        initial_url: str | None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        # initial_url=None means "auto-detect"; show a blank placeholder.
        url_to_load = initial_url if initial_url is not None else "about:blank"
        self.web_view = JFTermWebView(url=url_to_load)
        self.web_view.set_vexpand(True)
        self.web_view.set_hexpand(True)

        self.terminal = JFTermTerminal(
            muxer,
            session_id,
            cwd=cwd,
            send_after_spawn=send_after_spawn,
            appearance=appearance,
        )
        self.terminal.set_vexpand(True)
        self.terminal.set_hexpand(True)

        self.set_start_child(self.web_view)
        self.set_end_child(self.terminal)
        self.set_resize_start_child(True)
        self.set_resize_end_child(True)
        self.set_shrink_start_child(True)
        self.set_shrink_end_child(True)

        # Default 80/20 split is applied once the widget gets its size.
        # Until then a Paned defaults to giving the start child all the
        # space, which is fine; we adjust on first allocation.
        self._initial_split_applied = False
        self.connect("notify::max-position", self._maybe_apply_default_split)

    def _maybe_apply_default_split(self, *_: Any) -> None:
        if self._initial_split_applied:
            return
        max_pos = self.get_property("max-position")
        if max_pos <= 0:
            return
        self.set_position(int(max_pos * 0.8))
        self._initial_split_applied = True

    def set_url(self, url: str) -> None:
        """Load `url` in the webview. Used both at startup (explicit URL)
        and from auto-mode when the scanner picks one up."""
        # JFTermWebView exposes load via its internal _web; reuse the
        # entry-activate behavior by loading via the public webkit method.
        self.web_view._web.load_uri(url)

    def collapse_webview(self) -> None:
        """Shrink the webview to a hairline so the terminal fills the
        tab. Called when the process exits non-zero so the failure
        output is what the user sees, while leaving the Paned divider
        grabbable."""
        self.set_position(COLLAPSED_WEBVIEW_PX)

    def grab_focus(self) -> bool:  # type: ignore[override]
        return self.terminal.grab_focus()


__all__ = ["COLLAPSED_WEBVIEW_PX", "JFTermLinkedView", "is_available"]
