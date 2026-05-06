import os
from pathlib import Path

from gi.repository import GLib, Vte


class JFTermTerminal(Vte.Terminal):
    """A VTE terminal that has spawned a shell. Exposes shell_pid and pty_fd."""

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self.shell_pid: int | None = None
        self.pty_fd: int | None = None

        shell = os.environ.get("SHELL") or "/bin/bash"
        cwd = cwd or str(Path.home())

        self.spawn_async(
            Vte.PtyFlags.DEFAULT,
            cwd,
            [shell, "-l"],
            None,
            GLib.SpawnFlags.DEFAULT,
            None, None,
            -1,
            None,
            self._on_spawned,
            None,
        )

    def _on_spawned(self, terminal, pid, error, user_data) -> None:
        if error is not None:
            raise RuntimeError(f"failed to spawn shell: {error.message}")
        self.shell_pid = pid
        pty = self.get_pty()
        if pty is not None:
            self.pty_fd = pty.get_fd()
