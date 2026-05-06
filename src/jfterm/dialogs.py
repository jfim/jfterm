from __future__ import annotations

from pathlib import Path
from typing import Callable

from gi.repository import Adw, Gtk

from jfterm.models import StartupCommand


def show_project_dialog(
    parent: Gtk.Window,
    *,
    title: str,
    initial_name: str = "",
    initial_directory: str = "",
    initial_commands: list[StartupCommand] | None = None,
    on_save: Callable[[str, str, list[StartupCommand]], None],
    on_disband: Callable[[], None] | None = None,
) -> None:
    dlg = Adw.Window(
        transient_for=parent, modal=True, title=title, default_width=480
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

    # --- startup commands editor ---

    commands_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    # Each entry is (Gtk.Entry for command, Gtk.SpinButton for delay).
    command_rows: list[tuple[Gtk.Entry, Gtk.SpinButton]] = []

    def _add_command_row(initial_text: str = "", initial_delay: int = 0) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        entry = Gtk.Entry(
            placeholder_text="e.g. docker compose up postgres"
        )
        entry.set_text(initial_text)
        entry.set_hexpand(True)

        delay = Gtk.SpinButton.new_with_range(0, 600, 1)
        delay.set_value(initial_delay)
        delay.set_tooltip_text(
            "Seconds to wait after starting this command before the next "
            "(0 = launch the next one immediately)."
        )

        delete = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        delete.add_css_class("flat")
        delete.set_tooltip_text("Remove command")

        def _on_delete(_b, r=row, pair=(entry, delay)):
            commands_box.remove(r)
            command_rows.remove(pair)

        delete.connect("clicked", _on_delete)
        row.append(entry)
        row.append(delay)
        row.append(delete)
        commands_box.append(row)
        command_rows.append((entry, delay))

    for sc in initial_commands or []:
        _add_command_row(sc.command, sc.delay)

    add_cmd_btn = Gtk.Button(label="Add command")
    add_cmd_btn.add_css_class("flat")
    add_cmd_btn.connect("clicked", lambda _b: _add_command_row())

    # --- action buttons ---

    actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    actions.set_halign(Gtk.Align.END)

    save_btn = Gtk.Button(label="Save")
    save_btn.add_css_class("suggested-action")

    def _on_save_clicked(_b):
        name = name_entry.get_text().strip()
        directory = dir_entry.get_text().strip()
        if not name or not directory:
            return
        commands = [
            StartupCommand(command=text, delay=int(delay_w.get_value()))
            for entry, delay_w in command_rows
            if (text := entry.get_text().strip())
        ]
        on_save(name, directory, commands)
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
        Gtk.Label(label="Startup commands (one tab per command)", xalign=0),
        commands_box,
        add_cmd_btn,
        actions,
    ):
        box.append(w)

    dlg.set_content(box)
    dlg.present()
