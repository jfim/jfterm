# src/jfterm/preferences.py
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk, Pango  # noqa: E402

from jfterm.palettes import PALETTES  # noqa: E402
from jfterm.settings import AppSettings  # noqa: E402


class _MonospaceFilter(Gtk.Filter):
    """Gtk.Filter that keeps only monospace Pango font families."""

    def do_match(self, item) -> bool:
        if isinstance(item, Pango.FontFamily):
            return item.is_monospace()
        if isinstance(item, Pango.FontFace):
            family = item.get_family()
            return family is not None and family.is_monospace()
        return False

    def do_get_strictness(self) -> Gtk.FilterMatch:
        return Gtk.FilterMatch.SOME


class AppPreferencesDialog(Adw.PreferencesDialog):
    """Global appearance preferences. Emits `changed` with a fresh AppSettings."""

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.set_title("Preferences")
        self._settings = AppSettings(
            font_desc=settings.font_desc,
            palette_id=settings.palette_id,
            mcp_enabled=settings.mcp_enabled,
            mcp_host=settings.mcp_host,
            mcp_port=settings.mcp_port,
        )

        page = Adw.PreferencesPage()
        page.set_title("Appearance")
        page.set_icon_name("applications-graphics-symbolic")

        group = Adw.PreferencesGroup()
        group.set_title("Terminal")

        # --- Font row ---
        font_row = Adw.ActionRow()
        font_row.set_title("Font")
        font_row.set_subtitle("Monospace fonts only")

        font_dialog = Gtk.FontDialog()
        font_dialog.set_title("Pick a terminal font")
        font_dialog.set_filter(_MonospaceFilter())

        self._font_button = Gtk.FontDialogButton(dialog=font_dialog)
        self._font_button.set_use_font(True)
        self._font_button.set_valign(Gtk.Align.CENTER)
        if self._settings.font_desc:
            self._font_button.set_font_desc(
                Pango.FontDescription.from_string(self._settings.font_desc)
            )
        self._font_button.connect("notify::font-desc", self._on_font_changed)
        font_row.add_suffix(self._font_button)
        font_row.set_activatable_widget(self._font_button)
        group.add(font_row)

        # --- Palette row ---
        names = Gtk.StringList()
        for p in PALETTES:
            names.append(p.display_name)
        self._palette_row = Adw.ComboRow()
        self._palette_row.set_title("Color scheme")
        self._palette_row.set_model(names)
        # Select current palette
        current_index = next(
            (i for i, p in enumerate(PALETTES) if p.id == self._settings.palette_id),
            0,
        )
        self._palette_row.set_selected(current_index)
        self._palette_row.connect("notify::selected", self._on_palette_changed)
        group.add(self._palette_row)

        page.add(group)

        mcp_group = Adw.PreferencesGroup()
        mcp_group.set_title("MCP server")
        mcp_group.set_description(
            "Embedded HTTP server exposing JFTerm to MCP clients. "
            "Changes take effect on next launch."
        )

        self._mcp_enabled_row = Adw.SwitchRow()
        self._mcp_enabled_row.set_title("Enable MCP server")
        self._mcp_enabled_row.set_active(self._settings.mcp_enabled)
        self._mcp_enabled_row.connect("notify::active", self._on_mcp_enabled_changed)
        mcp_group.add(self._mcp_enabled_row)

        self._mcp_host_row = Adw.EntryRow()
        self._mcp_host_row.set_title("Host")
        self._mcp_host_row.set_text(self._settings.mcp_host)
        self._mcp_host_row.connect("changed", self._on_mcp_host_changed)
        mcp_group.add(self._mcp_host_row)

        self._mcp_port_row = Adw.SpinRow.new_with_range(1, 65535, 1)
        self._mcp_port_row.set_title("Port")
        self._mcp_port_row.set_value(self._settings.mcp_port)
        self._mcp_port_row.connect("notify::value", self._on_mcp_port_changed)
        mcp_group.add(self._mcp_port_row)

        page.add(mcp_group)
        self.add(page)

    # --- handlers ---

    def _on_font_changed(self, button: Gtk.FontDialogButton, _pspec) -> None:
        desc = button.get_font_desc()
        self._settings.font_desc = desc.to_string() if desc is not None else ""
        self.emit("changed", self._copy())

    def _on_palette_changed(self, row: Adw.ComboRow, _pspec) -> None:
        idx = row.get_selected()
        if 0 <= idx < len(PALETTES):
            self._settings.palette_id = PALETTES[idx].id
            self.emit("changed", self._copy())

    def _on_mcp_enabled_changed(self, row: Adw.SwitchRow, _pspec) -> None:
        self._settings.mcp_enabled = row.get_active()
        self.emit("changed", self._copy())

    def _on_mcp_host_changed(self, row: Adw.EntryRow) -> None:
        self._settings.mcp_host = row.get_text()
        self.emit("changed", self._copy())

    def _on_mcp_port_changed(self, row: Adw.SpinRow, _pspec) -> None:
        self._settings.mcp_port = int(row.get_value())
        self.emit("changed", self._copy())

    def _copy(self) -> AppSettings:
        return AppSettings(
            font_desc=self._settings.font_desc,
            palette_id=self._settings.palette_id,
            mcp_enabled=self._settings.mcp_enabled,
            mcp_host=self._settings.mcp_host,
            mcp_port=self._settings.mcp_port,
        )
