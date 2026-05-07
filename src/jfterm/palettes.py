from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    id: str
    display_name: str
    background: str
    foreground: str
    cursor: str | None
    colors: tuple[str, ...]  # exactly 16 hex strings (ANSI 0..15), or empty for "system"


_SYSTEM = Palette(
    id="system",
    display_name="System default",
    background="",
    foreground="",
    cursor=None,
    colors=(),
)

# Tango — GNOME Terminal's classic palette.
_TANGO = Palette(
    id="tango",
    display_name="Tango",
    background="#000000",
    foreground="#ffffff",
    cursor=None,
    colors=(
        "#000000",
        "#cc0000",
        "#4e9a06",
        "#c4a000",
        "#3465a4",
        "#75507b",
        "#06989a",
        "#d3d7cf",
        "#555753",
        "#ef2929",
        "#8ae234",
        "#fce94f",
        "#729fcf",
        "#ad7fa8",
        "#34e2e2",
        "#eeeeec",
    ),
)

# Solarized — Ethan Schoonover's palette.
_SOLARIZED_DARK = Palette(
    id="solarized-dark",
    display_name="Solarized Dark",
    background="#002b36",
    foreground="#839496",
    cursor="#93a1a1",
    colors=(
        "#073642",
        "#dc322f",
        "#859900",
        "#b58900",
        "#268bd2",
        "#d33682",
        "#2aa198",
        "#eee8d5",
        "#002b36",
        "#cb4b16",
        "#586e75",
        "#657b83",
        "#839496",
        "#6c71c4",
        "#93a1a1",
        "#fdf6e3",
    ),
)

_SOLARIZED_LIGHT = Palette(
    id="solarized-light",
    display_name="Solarized Light",
    background="#fdf6e3",
    foreground="#657b83",
    cursor="#586e75",
    colors=(
        "#073642",
        "#dc322f",
        "#859900",
        "#b58900",
        "#268bd2",
        "#d33682",
        "#2aa198",
        "#eee8d5",
        "#002b36",
        "#cb4b16",
        "#586e75",
        "#657b83",
        "#839496",
        "#6c71c4",
        "#93a1a1",
        "#fdf6e3",
    ),
)

# Gruvbox Dark (medium) — Pavel Pertsev's palette.
_GRUVBOX_DARK = Palette(
    id="gruvbox-dark",
    display_name="Gruvbox Dark",
    background="#282828",
    foreground="#ebdbb2",
    cursor="#ebdbb2",
    colors=(
        "#282828",
        "#cc241d",
        "#98971a",
        "#d79921",
        "#458588",
        "#b16286",
        "#689d6a",
        "#a89984",
        "#928374",
        "#fb4934",
        "#b8bb26",
        "#fabd2f",
        "#83a598",
        "#d3869b",
        "#8ec07c",
        "#ebdbb2",
    ),
)

# Nord — Arctic, north-bluish color palette by Sven Greb.
_NORD = Palette(
    id="nord",
    display_name="Nord",
    background="#2e3440",
    foreground="#d8dee9",
    cursor="#d8dee9",
    colors=(
        "#3b4252",
        "#bf616a",
        "#a3be8c",
        "#ebcb8b",
        "#81a1c1",
        "#b48ead",
        "#88c0d0",
        "#e5e9f0",
        "#4c566a",
        "#bf616a",
        "#a3be8c",
        "#ebcb8b",
        "#81a1c1",
        "#b48ead",
        "#8fbcbb",
        "#eceff4",
    ),
)

# Dracula — Zeno Rocha's palette.
_DRACULA = Palette(
    id="dracula",
    display_name="Dracula",
    background="#282a36",
    foreground="#f8f8f2",
    cursor="#f8f8f2",
    colors=(
        "#21222c",
        "#ff5555",
        "#50fa7b",
        "#f1fa8c",
        "#bd93f9",
        "#ff79c6",
        "#8be9fd",
        "#f8f8f2",
        "#6272a4",
        "#ff6e6e",
        "#69ff94",
        "#ffffa5",
        "#d6acff",
        "#ff92df",
        "#a4ffff",
        "#ffffff",
    ),
)

PALETTES: tuple[Palette, ...] = (
    _SYSTEM,
    _TANGO,
    _SOLARIZED_DARK,
    _SOLARIZED_LIGHT,
    _GRUVBOX_DARK,
    _NORD,
    _DRACULA,
)


def get(palette_id: str) -> Palette:
    for p in PALETTES:
        if p.id == palette_id:
            return p
    return _SYSTEM
