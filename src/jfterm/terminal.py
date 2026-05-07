import contextlib
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Vte", "3.91")

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Vte  # noqa: E402


class JFTermTerminal(Vte.Terminal):
    """A VTE terminal that has spawned a shell.

    Emits:
      cwd-changed(str)      whenever VTE reports a new OSC 7 cwd
      running-changed(bool) when foreground command starts/finishes
      title-changed(str)    when VTE's window title changes (OSC 0/2)
    """

    __gsignals__ = {
        "cwd-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "running-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "title-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(
        self,
        cwd: str | None = None,
        send_after_spawn: str | None = None,
    ) -> None:
        super().__init__()
        self.shell_pid: int | None = None
        self.pty_fd: int | None = None
        self._initial_cwd = cwd or str(Path.home())
        self._osc133_seen = False
        # Feed this string (with a trailing newline) into the pty as soon as
        # the shell has spawned. The shell will buffer it until ready and
        # execute as if the user typed it.
        self._send_after_spawn = send_after_spawn

        self.connect("current-directory-uri-changed", self._on_cwd_uri_changed)
        self.connect("window-title-changed", self._on_title_changed)

        # OSC 133 path A: connect whichever shell-integration signals VTE
        # exposes on this version. If neither is available, the tcgetpgrp
        # polling fallback below stays in charge.
        for sig, handler in (
            ("shell-preexec", self._on_shell_preexec),
            ("shell-precmd", self._on_shell_precmd),
        ):
            with contextlib.suppress(TypeError, ValueError):
                self.connect(sig, handler)

        shell = os.environ.get("SHELL") or "/bin/bash"
        self.spawn_async(
            Vte.PtyFlags.DEFAULT,
            self._initial_cwd,
            [shell, "-l"],
            None,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            -1,
            None,
            self._on_spawned,
            None,
        )

        # Polling fallback. Cancels itself once an OSC 133 marker is seen.
        self._poll_source: int | None = GLib.timeout_add(250, self._poll_tcgetpgrp)

        self._install_context_menu()

    # --- context menu ---

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

    def _on_spawned(self, _term, pid, error, _user_data) -> None:
        if error is not None:
            raise RuntimeError(f"failed to spawn shell: {error.message}")
        self.shell_pid = pid
        pty = self.get_pty()
        if pty is not None:
            self.pty_fd = pty.get_fd()
        if self._send_after_spawn is not None:
            self.feed_child((self._send_after_spawn + "\n").encode())
            self._send_after_spawn = None

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

    def _on_shell_preexec(self, _t) -> None:
        self._osc133_seen = True
        self.emit("running-changed", True)

    def _on_shell_precmd(self, _t) -> None:
        self._osc133_seen = True
        self.emit("running-changed", False)

    # --- polling fallback ---

    def _poll_tcgetpgrp(self) -> bool:
        if self._osc133_seen:
            self._poll_source = None
            return False  # remove the source
        if self.pty_fd is None or self.shell_pid is None:
            return True
        try:
            fg = os.tcgetpgrp(self.pty_fd)
        except OSError:
            return True
        running = fg != self.shell_pid
        self.emit("running-changed", running)
        return True
