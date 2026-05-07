"""WebKit-backed web tab widget. Imports WebKit lazily so JFTerm runs
without `gir1.2-webkit-6.0` installed; callers must first check
is_available() before constructing a JFTermWebView."""

from __future__ import annotations

from typing import Any

from gi.repository import GObject, Gtk

from jfterm.webkit_session import get_session

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


class JFTermWebView(Gtk.Box):
    """Vertical box: toolbar (back/forward/reload + URL entry) above a WebView.

    Emits:
      - `title-changed(str)` — page title changed.
      - `url-changed(str)` — current URI changed.
    """

    __gsignals__ = {
        "title-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "url-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, *, url: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        if not is_available():
            raise RuntimeError(
                f"WebKit 6.0 not available; install {WEBKIT_PACKAGE}",
            )

        import gi

        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        toolbar.set_margin_start(4)
        toolbar.set_margin_end(4)
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(4)

        self._back = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self._back.add_css_class("flat")
        self._back.set_tooltip_text("Back")
        self._back.set_sensitive(False)
        self._back.connect("clicked", lambda _b: self._web.go_back())

        self._forward = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self._forward.add_css_class("flat")
        self._forward.set_tooltip_text("Forward")
        self._forward.set_sensitive(False)
        self._forward.connect("clicked", lambda _b: self._web.go_forward())

        self._reload = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self._reload.add_css_class("flat")
        self._reload.set_tooltip_text("Reload")
        self._reload.connect("clicked", lambda _b: self._web.reload())

        self._entry = Gtk.Entry()
        self._entry.set_hexpand(True)
        self._entry.set_text(url)
        self._entry.connect("activate", self._on_entry_activate)

        for w in (self._back, self._forward, self._reload, self._entry):
            toolbar.append(w)
        self.append(toolbar)

        # network-session is a construct-only property in WebKitGTK 6.0.
        self._web = WebKit.WebView(network_session=get_session())
        self._web.set_vexpand(True)
        self._web.set_hexpand(True)

        settings = self._web.get_settings()
        settings.set_enable_developer_extras(True)

        self._web.connect("notify::title", self._on_title_notify)
        self._web.connect("notify::uri", self._on_uri_notify)
        self._web.connect("notify::estimated-load-progress", self._on_progress_notify)

        self.append(self._web)

        # Ctrl+L focuses the URL entry.
        ctl = Gtk.ShortcutController()
        ctl.set_scope(Gtk.ShortcutScope.LOCAL)
        ctl.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<Control>l"),
                Gtk.CallbackAction.new(self._focus_entry),
            )
        )
        self.add_controller(ctl)

        self._web.load_uri(url)

    def _on_title_notify(self, *_: Any) -> None:
        title = self._web.get_title() or ""
        self.emit("title-changed", title)

    def _on_uri_notify(self, *_: Any) -> None:
        uri = self._web.get_uri() or ""
        self._entry.set_text(uri)
        self._back.set_sensitive(self._web.can_go_back())
        self._forward.set_sensitive(self._web.can_go_forward())
        self.emit("url-changed", uri)

    def _on_progress_notify(self, *_: Any) -> None:
        self._back.set_sensitive(self._web.can_go_back())
        self._forward.set_sensitive(self._web.can_go_forward())

    def _on_entry_activate(self, entry: Gtk.Entry) -> None:
        text = entry.get_text().strip()
        if not text:
            return
        if "://" not in text:
            text = "https://" + text
        self._web.load_uri(text)

    def _focus_entry(self, *_: Any) -> bool:
        self._entry.grab_focus()
        self._entry.select_region(0, -1)
        return True

    def grab_focus(self) -> bool:  # type: ignore[override]
        return self._web.grab_focus()
