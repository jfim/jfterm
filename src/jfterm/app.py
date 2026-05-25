import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Vte", "3.91")
gi.require_version("Graphene", "1.0")

from gi.repository import Adw, Gio  # noqa: E402

from jfterm.watchdog import install_watchdog  # noqa: E402
from jfterm.window import JFTermWindow  # noqa: E402


class JFTermApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="dev.jfim.jfterm",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self) -> None:  # type: ignore[override]
        win = self.props.active_window or JFTermWindow(self)
        win.present()


def main() -> int:
    install_watchdog()
    return JFTermApp().run(None)
