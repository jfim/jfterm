import json
import os
from pathlib import Path

from jfterm.models import Project, Workspace


_KNOWN_FIELDS = {"id", "name", "directory", "expanded"}


def load_projects(ws: Workspace, path: Path) -> None:
    if not path.exists():
        return
    data = json.loads(path.read_text())
    for entry in data.get("projects", []):
        p = Project(
            id=entry["id"],
            name=entry["name"],
            directory=entry["directory"],
            expanded=entry.get("expanded", True),
        )
        # Stash unknown fields for forward compatibility.
        p._extra = {k: v for k, v in entry.items() if k not in _KNOWN_FIELDS}
        ws.projects.append(p)
    ws.unsorted.expanded = data.get("unsorted_expanded", True)


def save_projects(ws: Workspace, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "directory": p.directory,
                "expanded": p.expanded,
                **getattr(p, "_extra", {}),
            }
            for p in ws.projects
        ],
        "unsorted_expanded": ws.unsorted.expanded,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def default_path() -> Path:
    """Path to ~/.config/jfterm/projects.json (XDG_CONFIG_HOME aware)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "jfterm" / "projects.json"
