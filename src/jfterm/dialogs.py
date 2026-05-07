from __future__ import annotations

from pathlib import Path
from typing import Callable

from gi.repository import Adw, Gdk, GObject, Gtk

from jfterm.models import StartupCommand


class _RowRef(GObject.Object):
    """Carrier so a startup-command row can travel through GValue DnD."""

    def __init__(self, row: Gtk.Widget) -> None:
        super().__init__()
        self.row = row


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
    # Each entry is (row container, Gtk.Entry for command, Gtk.SpinButton for delay).
    command_rows: list[tuple[Gtk.Box, Gtk.Entry, Gtk.SpinButton]] = []

    def _move_row(src_row: Gtk.Box, dst_row: Gtk.Box) -> None:
        if src_row is dst_row:
            return
        src_idx = next(
            (i for i, t in enumerate(command_rows) if t[0] is src_row), None
        )
        dst_idx = next(
            (i for i, t in enumerate(command_rows) if t[0] is dst_row), None
        )
        if src_idx is None or dst_idx is None:
            return
        item = command_rows.pop(src_idx)
        new_dst = next(
            i for i, t in enumerate(command_rows) if t[0] is dst_row
        )
        command_rows.insert(new_dst, item)
        # Sync the GTK box order to match command_rows.
        for r, _, _ in command_rows:
            commands_box.remove(r)
        for r, _, _ in command_rows:
            commands_box.append(r)

    def _add_command_row(initial_text: str = "", initial_delay: int = 0) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        handle = Gtk.Image.new_from_icon_name("open-menu-symbolic")
        handle.add_css_class("dim-label")
        handle.set_tooltip_text("Drag to reorder")
        handle.set_cursor(Gdk.Cursor.new_from_name("grab", None))

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

        def _on_delete(_b, r=row):
            commands_box.remove(r)
            for i, t in enumerate(command_rows):
                if t[0] is r:
                    command_rows.pop(i)
                    break

        delete.connect("clicked", _on_delete)

        # Drag source on the handle; carries a _RowRef pointing at this row.
        src = Gtk.DragSource()
        src.set_actions(Gdk.DragAction.MOVE)

        def _prepare(_s, _x, _y, r=row):
            v = GObject.Value()
            v.init(_RowRef.__gtype__)
            v.set_object(_RowRef(r))
            return Gdk.ContentProvider.new_for_value(v)

        def _drag_begin(s, _drag, r=row):
            s.set_icon(Gtk.WidgetPaintable.new(r), 0, 0)

        src.connect("prepare", _prepare)
        src.connect("drag-begin", _drag_begin)
        handle.add_controller(src)

        # Drop target on the row: dropping here moves the source to this row.
        target = Gtk.DropTarget.new(_RowRef.__gtype__, Gdk.DragAction.MOVE)

        def _on_drop(_t, value, _x, _y, dst=row):
            src_row = value.row if isinstance(value, _RowRef) else None
            if src_row is None:
                return False
            _move_row(src_row, dst)
            return True

        target.connect("drop", _on_drop)
        row.add_controller(target)

        row.append(handle)
        row.append(entry)
        row.append(delay)
        row.append(delete)
        commands_box.append(row)
        command_rows.append((row, entry, delay))

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
            for _row, entry, delay_w in command_rows
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
