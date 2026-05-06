from gi.repository import Adw, Gtk


class JFTermWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="JFTerm")
        self.set_default_size(1100, 700)

        header = Adw.HeaderBar()
        content = Gtk.Label(label="JFTerm — empty")
        content.set_vexpand(True)
        content.set_hexpand(True)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(content)
        self.set_content(toolbar)
