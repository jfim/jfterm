import re

from jfterm.palettes import PALETTES, get

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_get_system_returns_system_palette():
    p = get("system")
    assert p.id == "system"
    assert p.colors == ()


def test_get_unknown_id_falls_back_to_system():
    p = get("does-not-exist")
    assert p.id == "system"


def test_palettes_contains_system_first():
    assert PALETTES[0].id == "system"


def test_palettes_have_unique_ids():
    ids = [p.id for p in PALETTES]
    assert len(ids) == len(set(ids))


def test_non_system_palettes_have_16_colors():
    for p in PALETTES:
        if p.id == "system":
            continue
        assert len(p.colors) == 16, f"{p.id} has {len(p.colors)} colors"


def test_all_color_strings_are_valid_hex():
    for p in PALETTES:
        if p.id == "system":
            continue
        assert HEX.match(p.foreground), f"{p.id} foreground: {p.foreground}"
        assert HEX.match(p.background), f"{p.id} background: {p.background}"
        if p.cursor is not None:
            assert HEX.match(p.cursor), f"{p.id} cursor: {p.cursor}"
        for i, c in enumerate(p.colors):
            assert HEX.match(c), f"{p.id} colors[{i}]: {c}"


def test_expected_palettes_are_present():
    ids = {p.id for p in PALETTES}
    assert {
        "system",
        "tango",
        "solarized-dark",
        "solarized-light",
        "gruvbox-dark",
        "nord",
        "dracula",
    } <= ids
