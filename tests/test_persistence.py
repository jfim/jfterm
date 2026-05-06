import json
from pathlib import Path

from jfterm.models import Workspace
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
    path.write_text(json.dumps({
        "version": 1,
        "projects": [
            {"id": "abc", "name": "A", "directory": "/tmp/a",
             "expanded": True, "future_field": {"x": 1}}
        ],
    }))
    ws = Workspace()
    load_projects(ws, path)
    save_projects(ws, path)

    data = json.loads(path.read_text())
    assert data["projects"][0]["future_field"] == {"x": 1}
