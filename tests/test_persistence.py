import json
from pathlib import Path

from jfterm.models import FlashCommand, Workspace
from jfterm.persistence import load_projects, save_projects


def test_save_then_load_roundtrips_projects(tmp_path: Path):
    ws = Workspace()
    a = ws.add_project(name="A", directory="/tmp/a")
    a.expanded = False
    ws.add_project(name="B", directory="/tmp/b")

    path = tmp_path / "projects.json"
    save_projects(ws, path)
    ws2 = Workspace()
    load_projects(ws2, path)

    assert [(p.name, p.directory, p.expanded) for p in ws2.projects] == [
        ("A", "/tmp/a", False),
        ("B", "/tmp/b", True),
    ]
    # IDs round-trip too
    assert [p.id for p in ws2.projects] == [p.id for p in ws.projects]


def test_load_missing_file_is_noop(tmp_path: Path):
    ws = Workspace()
    load_projects(ws, tmp_path / "does-not-exist.json")
    assert ws.projects == []


def test_save_creates_parent_directories(tmp_path: Path):
    ws = Workspace()
    ws.add_project(name="A", directory="/tmp/a")
    path = tmp_path / "nested" / "dir" / "projects.json"
    save_projects(ws, path)
    assert path.exists()


def test_unknown_fields_are_preserved(tmp_path: Path):
    """Forward-compat: future versions may add fields; we should not drop them."""
    path = tmp_path / "projects.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "projects": [
                    {
                        "id": "abc",
                        "name": "A",
                        "directory": "/tmp/a",
                        "expanded": True,
                        "future_field": {"x": 1},
                    }
                ],
            }
        )
    )
    ws = Workspace()
    load_projects(ws, path)
    save_projects(ws, path)

    data = json.loads(path.read_text())
    assert data["projects"][0]["future_field"] == {"x": 1}


def test_flash_commands_roundtrip(tmp_path: Path):
    ws = Workspace()
    p = ws.add_project(name="A", directory="/tmp/a")
    p.flash_commands = [
        FlashCommand(name="Push", command="git push"),
        FlashCommand(
            name="Check",
            command="just check",
            keep_open_on_success=True,
            focus_on_launch=False,
        ),
    ]

    path = tmp_path / "projects.json"
    save_projects(ws, path)
    ws2 = Workspace()
    load_projects(ws2, path)

    fcs = ws2.projects[0].flash_commands
    assert [(f.name, f.command, f.keep_open_on_success, f.focus_on_launch) for f in fcs] == [
        ("Push", "git push", False, True),
        ("Check", "just check", True, False),
    ]


def test_load_missing_flash_commands_defaults_to_empty(tmp_path: Path):
    path = tmp_path / "projects.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "projects": [
                    {"id": "x", "name": "A", "directory": "/tmp/a", "expanded": True}
                ],
            }
        )
    )
    ws = Workspace()
    load_projects(ws, path)
    assert ws.projects[0].flash_commands == []
