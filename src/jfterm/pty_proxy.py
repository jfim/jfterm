import contextlib
import fcntl
import os
import pty
import struct
import termios

import gi

gi.require_version("Vte", "3.91")
from gi.repository import GLib, GObject  # noqa: E402

from jfterm.osc_scanner import OscScanner  # noqa: E402


class PtyProxy(GObject.Object):
    """Owns a pty pair and a shell child, sniffs OSC 9;4 from the output.

    Signals:
      data-ready(bytes)         clean output bytes to feed into VTE
      progress-changed(int,int) parsed OSC 9;4 (state, value)
      child-exited(int)         shell exit status (mirrors VTE's signal)
    """

    __gsignals__ = {
        "data-ready": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "progress-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        "child-exited": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    READ_CHUNK = 65536

    def __init__(self, cwd: str, argv: list[str]) -> None:
        super().__init__()
        self._scanner = OscScanner()
        self._master_fd: int | None = None
        self._child_pid: int | None = None
        self._fd_watch: int | None = None
        self._child_watch: int | None = None
        self._spawn(cwd, argv)

    @property
    def shell_pid(self) -> int | None:
        return self._child_pid

    @property
    def pty_fd(self) -> int | None:
        return self._master_fd

    def _spawn(self, cwd: str, argv: list[str]) -> None:
        pid, master_fd = pty.fork()
        if pid == 0:
            # Child: chdir, exec the shell. If exec fails, _exit so we don't
            # run any parent-side teardown.
            with contextlib.suppress(OSError):
                os.chdir(cwd)
            try:
                os.execvp(argv[0], argv)
            except OSError:
                os._exit(127)
        # Parent.
        self._master_fd = master_fd
        self._child_pid = pid
        # Non-blocking reads so the GLib watcher can drain in one call.
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self._fd_watch = GLib.unix_fd_add_full(
            GLib.PRIORITY_DEFAULT,
            master_fd,
            GLib.IOCondition.IN | GLib.IOCondition.HUP,
            self._on_readable,
        )
        self._child_watch = GLib.child_watch_add(GLib.PRIORITY_DEFAULT, pid, self._on_child_exited)

    def _on_readable(self, fd: int, condition: GLib.IOCondition) -> bool:
        if condition & GLib.IOCondition.HUP and not (condition & GLib.IOCondition.IN):
            self._fd_watch = None
            return False
        try:
            chunk = os.read(fd, self.READ_CHUNK)
        except BlockingIOError:
            return True
        except OSError:
            self._fd_watch = None
            return False
        if not chunk:
            self._fd_watch = None
            return False
        clean, events = self._scanner.feed(chunk)
        if clean:
            self.emit("data-ready", clean)
        for ev in events:
            self.emit("progress-changed", ev.state, ev.value)
        return True

    def _on_child_exited(self, _: int, status: int) -> None:
        self._child_watch = None
        self._child_pid = None
        self.emit("child-exited", status)

    def write(self, data: bytes) -> None:
        if self._master_fd is None:
            return
        with contextlib.suppress(OSError):
            os.write(self._master_fd, data)

    def resize(self, rows: int, cols: int) -> None:
        if self._master_fd is None or rows <= 0 or cols <= 0:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        with contextlib.suppress(OSError):
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    def close(self) -> None:
        if self._fd_watch is not None:
            GLib.source_remove(self._fd_watch)
            self._fd_watch = None
        if self._child_watch is not None:
            GLib.source_remove(self._child_watch)
            self._child_watch = None
        if self._master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._master_fd)
            self._master_fd = None
