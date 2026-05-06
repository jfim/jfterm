from __future__ import annotations

from pathlib import Path
from typing import Callable

from gi.repository import Adw, Gtk


def show_project_dialog(
    parent: Gtk.Window,
    *,
    title: str,
    initial_name: str = "",
    initial_directory: str = "",
    on_save: Callable[[str, str], None],
    on_disband: Callable[[], None] | None = None,
) -> None:
    dlg = Adw.Window(
        transient_for=parent, modal=True, title=title, default_width=420
    )

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_start(16)
    box.set_margin_end(16)
    box.set_margin_top(12)
    box.set_margin_bottom(12)

    name_entry = Gtk.Entry(placeholder_text="Project name")
    name_entry.set_text(initial_name)

    dir_entry = Gtk.Entry(placeholder_text="Directory")
    dir_entry.set_text(initial_directory)

    pick_btn = Gtk.Button(label="Choose…")

    def _on_pick(_b):
        chooser = Gtk.FileDialog(title="Choose project directory")

        def _cb(d, res):
            try:
                folder = d.select_folder_finish(res)
            except Exception:
                return
            if folder is None:
                return
            path = folder.get_path()
            dir_entry.set_text(path)
            if not name_entry.get_text():
                name_entry.set_text(Path(path).name)

        chooser.select_folder(parent, None, _cb)

    pick_btn.connect("clicked", _on_pick)

    dir_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    dir_entry.set_hexpand(True)
    dir_row.append(dir_entry)
    dir_row.append(pick_btn)

    actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    actions.set_halign(Gtk.Align.END)

    save_btn = Gtk.Button(label="Save")
    save_btn.add_css_class("suggested-action")

    def _on_save_clicked(_b):
        name = name_entry.get_text().strip()
        directory = dir_entry.get_text().strip()
        if not name or not directory:
            return
        on_save(name, directory)
        dlg.close()

    save_btn.connect("clicked", _on_save_clicked)

    cancel_btn = Gtk.Button(label="Cancel")
    cancel_btn.connect("clicked", lambda _b: dlg.close())

    if on_disband is not None:
        disband_btn = Gtk.Button(label="Delete project")
        disband_btn.add_css_class("destructive-action")

        def _on_disband_clicked(_b):
            on_disband()
            dlg.close()

        disband_btn.connect("clicked", _on_disband_clicked)
        actions.append(disband_btn)

    actions.append(cancel_btn)
    actions.append(save_btn)

    for w in (
        Gtk.Label(label="Name", xalign=0),
        name_entry,
        Gtk.Label(label="Directory", xalign=0),
        dir_row,
        actions,
    ):
        box.append(w)

    dlg.set_content(box)
    dlg.present()
