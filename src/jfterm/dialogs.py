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
    on_save: Callable[[str, str, list[StartupCommand], bool, list[FlashCommand]], None],
    on_disband: Callable[[], None] | None = None,
    on_archive: Callable[[], None] | None = None,
    n_open_tabs: int = 0,
) -> None:
    dlg = Adw.Window(transient_for=parent, modal=True, title=title, default_width=640)

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
    cmd_header_label.set_margin_start(8)
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
    flash_name_header.set_margin_start(8)
    flash_cmd_header = Gtk.Label(label="Command", xalign=0)
    flash_cmd_header.add_css_class("dim-label")
    flash_cmd_header.set_hexpand(True)
    flash_cmd_header.set_margin_start(8)
    flash_keep_header = Gtk.Label(label="Keep open", xalign=0)
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
    flash_rows: list[tuple[Gtk.Box, Gtk.Entry, Gtk.Entry, Gtk.CheckButton, Gtk.CheckButton]] = []

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

    if on_archive is not None:
        archive_btn = Gtk.Button(label="Archive project")

        def _do_archive():
            on_archive()
            dlg.close()

        def _on_archive_clicked(_b):
            if n_open_tabs <= 0:
                _do_archive()
                return
            confirm = Adw.MessageDialog(
                transient_for=dlg,
                modal=True,
                heading=f"Archive {initial_name or 'project'}?",
                body=(f"This will close {n_open_tabs} tab{'s' if n_open_tabs != 1 else ''}."),
            )
            confirm.add_response("cancel", "Cancel")
            confirm.add_response("archive", "Archive")
            confirm.set_response_appearance("archive", Adw.ResponseAppearance.DESTRUCTIVE)
            confirm.set_default_response("cancel")
            confirm.set_close_response("cancel")

            def _on_response(_d, response):
                if response == "archive":
                    _do_archive()

            confirm.connect("response", _on_response)
            confirm.present()

        archive_btn.connect("clicked", _on_archive_clicked)
        actions.append(archive_btn)

    actions.append(cancel_btn)
    actions.append(save_btn)

    project_group = Adw.PreferencesGroup(title="Project")
    project_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    project_inner.append(Gtk.Label(label="Name", xalign=0))
    project_inner.append(name_entry)
    project_inner.append(Gtk.Label(label="Directory", xalign=0))
    project_inner.append(dir_row)
    project_group.add(project_inner)

    startup_group = Adw.PreferencesGroup(
        title="Startup commands",
        description="Run when launching this project — one tab per command.",
    )
    startup_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    startup_inner.append(commands_header)
    startup_inner.append(commands_box)
    startup_inner.append(add_cmd_btn)
    startup_inner.append(spawn_blank_check)
    startup_group.add(startup_inner)

    flash_group = Adw.PreferencesGroup(
        title="Flash commands",
        description="Quick one-shot commands available from the project's flash menu.",
    )
    flash_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    flash_inner.append(flash_header)
    flash_inner.append(flash_box)
    flash_inner.append(add_flash_btn)
    flash_group.add(flash_inner)

    for w in (project_group, startup_group, flash_group, actions):
        box.append(w)

    dlg.set_content(box)
    dlg.present()


def show_new_web_tab_dialog(
    parent: Gtk.Window,
    on_confirm: Callable[[str], None],
) -> None:
    """Prompt for a URL. Calls `on_confirm(trimmed_url)` if the user submits
    a value matching ^https?:// (case-insensitive)."""
    from jfterm.url_routing import is_web_url

    dialog = Adw.AlertDialog(heading="New web tab")
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("ok", "Open")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response("cancel")

    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    entry = Gtk.Entry()
    entry.set_placeholder_text("https://")
    entry.set_hexpand(True)
    error_label = Gtk.Label()
    error_label.add_css_class("error")
    error_label.set_xalign(0)
    error_label.set_visible(False)
    body.append(entry)
    body.append(error_label)
    dialog.set_extra_child(body)

    def _on_response(_d: Adw.AlertDialog, response: str) -> None:
        if response != "ok":
            return
        url = entry.get_text().strip()
        if not is_web_url(url):
            error_label.set_text("URL must start with http:// or https://")
            error_label.set_visible(True)
            dialog.present(parent)
            return
        on_confirm(url)

    dialog.connect("response", _on_response)

    def _on_activate(_e: Gtk.Entry) -> None:
        url = entry.get_text().strip()
        if not is_web_url(url):
            error_label.set_text("URL must start with http:// or https://")
            error_label.set_visible(True)
            return
        dialog.close()
        on_confirm(url)

    entry.connect("activate", _on_activate)
    dialog.present(parent)
    entry.grab_focus_without_selecting()
