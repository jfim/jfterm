from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from gi.repository import Adw, Gdk, GObject, Gtk

from jfterm.models import FlashCommand, StartupCommand


class _RowRef(GObject.Object):
    """Carrier so a startup-command row can travel through GValue DnD."""

    def __init__(self, row: Gtk.Widget) -> None:
        super().__init__()
        self.row = row


class _FlashRowRef(GObject.Object):
    """Carrier so a flash-command row can travel through GValue DnD.

    Distinct from _RowRef so dragging a startup row can't drop into the
    flash list (different GType).
    """

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
    initial_spawn_blank_after_startup: bool = False,
    initial_flash_commands: list[FlashCommand] | None = None,
    on_save: Callable[
        [str, str, list[StartupCommand], bool, list[FlashCommand]], None
    ],
    on_disband: Callable[[], None] | None = None,
) -> None:
    dlg = Adw.Window(transient_for=parent, modal=True, title=title, default_width=480)

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

    commands_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    handle_spacer = Gtk.Image.new_from_icon_name("open-menu-symbolic")
    handle_spacer.set_opacity(0)
    cmd_header_label = Gtk.Label(label="Command", xalign=0)
    cmd_header_label.add_css_class("dim-label")
    cmd_header_label.set_hexpand(True)
    delay_header_label = Gtk.Label(label="Delay (secs)", xalign=0)
    delay_header_label.add_css_class("dim-label")
    delay_header_label.set_width_chars(12)
    delete_spacer = Gtk.Image.new_from_icon_name("user-trash-symbolic")
    delete_spacer.set_opacity(0)
    commands_header.append(handle_spacer)
    commands_header.append(cmd_header_label)
    commands_header.append(delay_header_label)
    commands_header.append(delete_spacer)

    commands_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    # Each entry is (row container, Gtk.Entry for command, Gtk.SpinButton for delay).
    command_rows: list[tuple[Gtk.Box, Gtk.Entry, Gtk.SpinButton]] = []

    def _move_row(src_row: Gtk.Box, dst_row: Gtk.Box) -> None:
        if src_row is dst_row:
            return
        src_idx = next((i for i, t in enumerate(command_rows) if t[0] is src_row), None)
        dst_idx = next((i for i, t in enumerate(command_rows) if t[0] is dst_row), None)
        if src_idx is None or dst_idx is None:
            return
        item = command_rows.pop(src_idx)
        new_dst = next(i for i, t in enumerate(command_rows) if t[0] is dst_row)
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

        entry = Gtk.Entry(placeholder_text="e.g. docker compose up postgres")
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

    if not command_rows:
        _add_command_row()

    add_cmd_btn = Gtk.Button(label="Add command")
    add_cmd_btn.add_css_class("flat")
    add_cmd_btn.connect("clicked", lambda _b: _add_command_row())

    # --- flash commands editor ---

    flash_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    flash_handle_spacer = Gtk.Image.new_from_icon_name("open-menu-symbolic")
    flash_handle_spacer.set_opacity(0)
    flash_name_header = Gtk.Label(label="Name", xalign=0)
    flash_name_header.add_css_class("dim-label")
    flash_name_header.set_width_chars(14)
    flash_cmd_header = Gtk.Label(label="Command", xalign=0)
    flash_cmd_header.add_css_class("dim-label")
    flash_cmd_header.set_hexpand(True)
    flash_keep_header = Gtk.Label(label="Keep open\non exit 0", xalign=0)
    flash_keep_header.add_css_class("dim-label")
    flash_focus_header = Gtk.Label(label="Focus", xalign=0)
    flash_focus_header.add_css_class("dim-label")
    flash_delete_spacer = Gtk.Image.new_from_icon_name("user-trash-symbolic")
    flash_delete_spacer.set_opacity(0)
    for w in (
        flash_handle_spacer,
        flash_name_header,
        flash_cmd_header,
        flash_keep_header,
        flash_focus_header,
        flash_delete_spacer,
    ):
        flash_header.append(w)

    flash_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    flash_rows: list[
        tuple[Gtk.Box, Gtk.Entry, Gtk.Entry, Gtk.CheckButton, Gtk.CheckButton]
    ] = []

    def _move_flash_row(src_row: Gtk.Box, dst_row: Gtk.Box) -> None:
        if src_row is dst_row:
            return
        src_idx = next((i for i, t in enumerate(flash_rows) if t[0] is src_row), None)
        dst_idx = next((i for i, t in enumerate(flash_rows) if t[0] is dst_row), None)
        if src_idx is None or dst_idx is None:
            return
        item = flash_rows.pop(src_idx)
        new_dst = next(i for i, t in enumerate(flash_rows) if t[0] is dst_row)
        flash_rows.insert(new_dst, item)
        for r, *_ in flash_rows:
            flash_box.remove(r)
        for r, *_ in flash_rows:
            flash_box.append(r)

    def _add_flash_row(
        initial_name: str = "",
        initial_command: str = "",
        initial_keep_open: bool = False,
        initial_focus: bool = True,
    ) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        handle = Gtk.Image.new_from_icon_name("open-menu-symbolic")
        handle.add_css_class("dim-label")
        handle.set_tooltip_text("Drag to reorder")
        handle.set_cursor(Gdk.Cursor.new_from_name("grab", None))

        name_entry = Gtk.Entry(placeholder_text="e.g. Git push")
        name_entry.set_text(initial_name)
        name_entry.set_width_chars(14)

        cmd_entry = Gtk.Entry(placeholder_text="e.g. git push")
        cmd_entry.set_text(initial_command)
        cmd_entry.set_hexpand(True)

        keep_check = Gtk.CheckButton()
        keep_check.set_active(initial_keep_open)
        keep_check.set_tooltip_text("Don't auto-close the tab when the command exits 0")

        focus_check = Gtk.CheckButton()
        focus_check.set_active(initial_focus)
        focus_check.set_tooltip_text("Switch to the tab when launching the command")

        delete = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        delete.add_css_class("flat")
        delete.set_tooltip_text("Remove flash command")

        def _on_delete(_b, r=row):
            flash_box.remove(r)
            for i, t in enumerate(flash_rows):
                if t[0] is r:
                    flash_rows.pop(i)
                    break

        delete.connect("clicked", _on_delete)

        src = Gtk.DragSource()
        src.set_actions(Gdk.DragAction.MOVE)

        def _prepare(_s, _x, _y, r=row):
            v = GObject.Value()
            v.init(_FlashRowRef.__gtype__)
            v.set_object(_FlashRowRef(r))
            return Gdk.ContentProvider.new_for_value(v)

        def _drag_begin(s, _drag, r=row):
            s.set_icon(Gtk.WidgetPaintable.new(r), 0, 0)

        src.connect("prepare", _prepare)
        src.connect("drag-begin", _drag_begin)
        handle.add_controller(src)

        target = Gtk.DropTarget.new(_FlashRowRef.__gtype__, Gdk.DragAction.MOVE)

        def _on_drop(_t, value, _x, _y, dst=row):
            src_row = value.row if isinstance(value, _FlashRowRef) else None
            if src_row is None:
                return False
            _move_flash_row(src_row, dst)
            return True

        target.connect("drop", _on_drop)
        row.add_controller(target)

        for w in (handle, name_entry, cmd_entry, keep_check, focus_check, delete):
            row.append(w)
        flash_box.append(row)
        flash_rows.append((row, name_entry, cmd_entry, keep_check, focus_check))

    for fc in initial_flash_commands or []:
        _add_flash_row(fc.name, fc.command, fc.keep_open_on_success, fc.focus_on_launch)

    add_flash_btn = Gtk.Button(label="Add flash command")
    add_flash_btn.add_css_class("flat")
    add_flash_btn.connect("clicked", lambda _b: _add_flash_row())

    spawn_blank_check = Gtk.CheckButton(label="Spawn blank terminal after startup")
    spawn_blank_check.set_active(initial_spawn_blank_after_startup)

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
        flash = [
            FlashCommand(
                name=fname,
                command=fcmd,
                keep_open_on_success=keep_w.get_active(),
                focus_on_launch=focus_w.get_active(),
            )
            for _row, name_w, cmd_w, keep_w, focus_w in flash_rows
            if (fname := name_w.get_text().strip()) and (fcmd := cmd_w.get_text().strip())
        ]
        on_save(name, directory, commands, spawn_blank_check.get_active(), flash)
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
        commands_header,
        commands_box,
        add_cmd_btn,
        Gtk.Label(label="Flash commands", xalign=0),
        flash_header,
        flash_box,
        add_flash_btn,
        spawn_blank_check,
        actions,
    ):
        box.append(w)

    dlg.set_content(box)
    dlg.present()
