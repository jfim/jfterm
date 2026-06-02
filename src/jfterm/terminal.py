import contextlib
import os
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Vte", "3.91")

from gi.repository import Gdk, Gio, GObject, Gtk, Pango, Vte  # noqa: E402

from jfterm.palettes import get as get_palette  # noqa: E402
from jfterm.remote_pty_proxy import RemotePtyProxy  # noqa: E402
from jfterm.settings import AppSettings  # noqa: E402

if TYPE_CHECKING:
    from jfterm.muxer_client import MuxerClient


class JFTermTerminal(Vte.Terminal):
    """A VTE terminal driven by a RemotePtyProxy over a jftermd session.

    Emits:
      cwd-changed(str)            whenever VTE reports a new OSC 7 cwd
      running-changed(bool)       when foreground command starts/finishes
      title-changed(str)          when VTE's window title changes (OSC 0/2)
      progress-changed(int, int)  parsed OSC 9;4 (state, value)
    """

    __gsignals__ = {
        "cwd-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "running-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "title-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "progress-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        "output-data": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(
        self,
        muxer: "MuxerClient",
        session_id: str,
        *,
        cwd: str | None = None,
        argv: list[str] | None = None,
        send_after_spawn: str | None = None,
        adopt: bool = False,
        appearance: AppSettings | None = None,
    ) -> None:
        super().__init__()
        self._initial_cwd = cwd or str(Path.home())
        self.session_id = session_id

        self.connect("current-directory-uri-changed", self._on_cwd_uri_changed)
        self.connect("window-title-changed", self._on_title_changed)
        self.connect("commit", self._on_commit)
        self.connect("char-size-changed", self._on_char_size_changed)

        shell = os.environ.get("SHELL") or "/bin/bash"
        resolved_argv = argv if argv is not None else [shell, "-l"]
        sock = muxer.connect_session()
        cols = self.get_column_count() or 80
        rows = self.get_row_count() or 24
        try:
            self._proxy = RemotePtyProxy(
                sock,
                session_id=session_id,
                cwd=self._initial_cwd,
                argv=resolved_argv,
                cols=cols,
                rows=rows,
                send_after_open=None if adopt else send_after_spawn,
            )
        except Exception:
            sock.close()
            raise
        self._proxy.connect("data-ready", self._on_proxy_data)
        self._proxy.connect("progress-changed", self._on_proxy_progress)
        self._proxy.connect("running-changed", self._on_proxy_running_changed)
        self._proxy.connect("child-exited", self._on_proxy_child_exited)

        self._last_size: tuple[int, int] = (0, 0)

        self._install_context_menu()

        if appearance is not None:
            self.apply_appearance(appearance)

    @property
    def shell_pid(self) -> int | None:
        return self._proxy.shell_pid

    @property
    def pty_fd(self) -> int | None:
        return self._proxy.pty_fd

    def apply_appearance(self, settings: AppSettings) -> None:
        """Apply font + color-scheme settings. Idempotent."""
        # Font
        if settings.font_desc:
            self.set_font(Pango.FontDescription.from_string(settings.font_desc))
        else:
            self.set_font(None)

        # Palette
        palette = get_palette(settings.palette_id)
        if palette.id == "system" or not palette.colors:
            self.set_colors(None, None, [])
            self.set_color_cursor(None)
            return

        fg = Gdk.RGBA()
        fg.parse(palette.foreground)
        bg = Gdk.RGBA()
        bg.parse(palette.background)
        ansi = []
        for hex_str in palette.colors:
            rgba = Gdk.RGBA()
            rgba.parse(hex_str)
            ansi.append(rgba)
        self.set_colors(fg, bg, ansi)

        if palette.cursor is not None:
            cursor = Gdk.RGBA()
            cursor.parse(palette.cursor)
            self.set_color_cursor(cursor)
        else:
            self.set_color_cursor(None)

    # --- context menu (unchanged) ---

    def _install_context_menu(self) -> None:
        menu = Gio.Menu()
        menu.append("Copy", "term.copy")
        menu.append("Paste", "term.paste")
        self._popover = Gtk.PopoverMenu.new_from_model(menu)
        self._popover.set_parent(self)
        self._popover.set_has_arrow(False)

        actions = Gio.SimpleActionGroup()
        copy_action = Gio.SimpleAction.new("copy", None)
        copy_action.connect("activate", lambda *_: self._do_copy())
        actions.add_action(copy_action)
        paste_action = Gio.SimpleAction.new("paste", None)
        paste_action.connect("activate", lambda *_: self._do_paste())
        actions.add_action(paste_action)
        self._copy_action = copy_action
        self.insert_action_group("term", actions)

        click = Gtk.GestureClick()
        click.set_button(Gdk.BUTTON_SECONDARY)
        click.connect("pressed", self._on_right_click)
        self.add_controller(click)

    def _on_right_click(self, _gesture, _n_press, x: float, y: float) -> None:
        self._copy_action.set_enabled(self.get_has_selection())
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def _do_copy(self) -> None:
        if self.get_has_selection():
            self.copy_clipboard_format(Vte.Format.TEXT)

    def _do_paste(self) -> None:
        self.paste_clipboard()

    # --- VTE callbacks ---

    def _on_cwd_uri_changed(self, _t) -> None:
        uri = self.get_current_directory_uri()
        if not uri:
            return
        parsed = urlparse(uri)
        path = unquote(parsed.path)
        self.emit("cwd-changed", path)

    def _on_title_changed(self, _t) -> None:
        title = self.get_window_title() or ""
        self.emit("title-changed", title)

    def _on_commit(self, _t, text: str, _size: int) -> None:
        self._proxy.write(text.encode("utf-8"))

    def _on_char_size_changed(self, _t, _w, _h) -> None:
        self._sync_pty_size()

    def _sync_pty_size(self) -> None:
        cols = self.get_column_count()
        rows = self.get_row_count()
        size = (rows, cols)
        if size == self._last_size:
            return
        self._last_size = size
        self._proxy.resize(rows, cols)

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:  # type: ignore[override]
        Vte.Terminal.do_size_allocate(self, width, height, baseline)
        self._sync_pty_size()

    def do_dispose(self) -> None:  # type: ignore[override]
        if hasattr(self, "_proxy") and self._proxy is not None:
            self._proxy.close()
        Vte.Terminal.do_dispose(self)

    # --- proxy callbacks ---

    def _on_proxy_data(self, _p, data: bytes) -> None:
        self.feed(data)
        self.emit("output-data", data)

    def _on_proxy_progress(self, _p, state: int, value: int) -> None:
        self.emit("progress-changed", state, value)

    def _on_proxy_running_changed(self, _p, running: bool) -> None:
        self.emit("running-changed", running)

    def _on_proxy_child_exited(self, _p, status: int) -> None:
        # VTE has its own child-exited signal; we surface ours through the
        # same name so existing subscribers (e.g. tab close-on-exit logic)
        # keep working. If nothing currently subscribes, this is harmless.
        # `child-exited` is a built-in VTE signal with a fixed signature;
        # if our emit shape doesn't match, it raises TypeError — suppress it.
        with contextlib.suppress(TypeError):
            self.emit("child-exited", status)
