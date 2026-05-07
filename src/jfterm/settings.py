from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppSettings:
    font_desc: str = ""  # Pango font string, e.g. "Monospace 11";
    # empty means "system default"
    palette_id: str = "system"
    mcp_enabled: bool = False
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 7820


def default_path() -> Path:
    """Path to ~/.config/jfterm/settings.json (XDG_CONFIG_HOME aware)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "jfterm" / "settings.json"


def load(path: Path) -> AppSettings:
    if not path.exists():
        return AppSettings()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"jfterm: ignoring malformed {path}: {e}", file=sys.stderr)
        return AppSettings()
    if not isinstance(data, dict):
        return AppSettings()
    defaults = AppSettings()
    try:
        port = int(data.get("mcp_port", defaults.mcp_port))
    except (TypeError, ValueError):
        port = defaults.mcp_port
    if not (1 <= port <= 65535):
        port = defaults.mcp_port
    return AppSettings(
        font_desc=str(data.get("font_desc", "")),
        palette_id=str(data.get("palette_id", "system")),
        mcp_enabled=bool(data.get("mcp_enabled", defaults.mcp_enabled)),
        mcp_host=str(data.get("mcp_host", defaults.mcp_host)),
        mcp_port=port,
    )


def save(settings: AppSettings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2))
