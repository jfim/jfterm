import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from jfterm.models import FlashCommand, Project, StartupCommand, Workspace

log = logging.getLogger(__name__)

_KNOWN_FIELDS = {
    "id",
    "name",
    "directory",
    "expanded",
    "archived",
    "startup_commands",
    "spawn_blank_after_startup",
    "flash_commands",
}


def _load_commands(raw: list) -> list[StartupCommand]:
    """Accept both legacy list[str] and new list[{command, delay}]."""
    out: list[StartupCommand] = []
    for item in raw:
        if isinstance(item, str):
            out.append(StartupCommand(command=item, delay=0))
        elif isinstance(item, dict):
            out.append(
                StartupCommand(
                    command=str(item.get("command", "")),
                    delay=int(item.get("delay", 0)),
                )
            )
    return out


def _load_flash_commands(raw: list) -> list[FlashCommand]:
    out: list[FlashCommand] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            FlashCommand(
                name=str(item.get("name", "")),
                command=str(item.get("command", "")),
                keep_open_on_success=bool(item.get("keep_open_on_success", False)),
                focus_on_launch=bool(item.get("focus_on_launch", True)),
            )
        )
    return out


def load_projects(ws: Workspace, path: Path) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"jfterm: ignoring malformed {path}: {e}", file=sys.stderr)
        return
    for entry in data.get("projects", []):
        if not all(k in entry for k in ("id", "name", "directory")):
            log.warning("Skipping malformed project entry missing required keys: %r", entry)
            continue
        p = Project(
            id=entry["id"],
            name=entry["name"],
            directory=entry["directory"],
            expanded=entry.get("expanded", True),
            archived=bool(entry.get("archived", False)),
            startup_commands=_load_commands(entry.get("startup_commands", [])),
            spawn_blank_after_startup=bool(entry.get("spawn_blank_after_startup", False)),
            flash_commands=_load_flash_commands(entry.get("flash_commands", [])),
        )
        # Stash unknown fields for forward compatibility.
        p._extra = {k: v for k, v in entry.items() if k not in _KNOWN_FIELDS}
        ws.projects.append(p)
    ws.unsorted.expanded = data.get("unsorted_expanded", True)
    ws.sidebar_width = int(data.get("sidebar_width", ws.sidebar_width))
    ws.archived_expanded = bool(data.get("archived_expanded", False))


def build_payload(ws: Workspace) -> dict:
    """Build a JSON-serializable snapshot of the workspace.

    This must be called on the thread that owns ``ws`` (the GTK main thread).
    The returned dict contains only plain Python types and is safe to pass to a
    worker thread for encoding and writing.
    """
    return {
        "version": 1,
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "directory": p.directory,
                "expanded": p.expanded,
                "archived": p.archived,
                "startup_commands": [
                    {"command": c.command, "delay": c.delay} for c in p.startup_commands
                ],
                "spawn_blank_after_startup": p.spawn_blank_after_startup,
                "flash_commands": [
                    {
                        "name": fc.name,
                        "command": fc.command,
                        "keep_open_on_success": fc.keep_open_on_success,
                        "focus_on_launch": fc.focus_on_launch,
                    }
                    for fc in p.flash_commands
                ],
                **getattr(p, "_extra", {}),
            }
            for p in ws.projects
        ],
        "unsorted_expanded": ws.unsorted.expanded,
        "archived_expanded": ws.archived_expanded,
        "sidebar_width": ws.sidebar_width,
    }


def write_payload(payload: dict, path: Path) -> None:
    """Encode ``payload`` as JSON and atomically write it to ``path``.

    Safe to call from any thread — touches no GTK state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as tmp:
        tmp.write(json.dumps(payload, indent=2))
    os.replace(tmp.name, path)


def save_projects(ws: Workspace, path: Path) -> None:
    write_payload(build_payload(ws), path)


def default_path() -> Path:
    """Path to ~/.config/jfterm/projects.json (XDG_CONFIG_HOME aware)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "jfterm" / "projects.json"
