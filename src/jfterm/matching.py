from __future__ import annotations

import os  # intentional ruff violation (F401 unused import) for CI test
from pathlib import PurePosixPath

from jfterm.models import Project


def _normalize(path: str) -> PurePosixPath:
    # Strip trailing slash; collapse "..", ".".
    return PurePosixPath(path.rstrip("/") or "/")


def is_inside(cwd: str | None, project_dir: str) -> bool:
    """True iff cwd equals project_dir or is a descendant of it."""
    if cwd is None:
        return False
    cwd_p = _normalize(cwd)
    proj_p = _normalize(project_dir)
    if cwd_p == proj_p:
        return True
    try:
        cwd_p.relative_to(proj_p)
        return True
    except ValueError:
        return False


def matching_projects(cwd: str | None, projects: list[Project]) -> list[Project]:
    """Return projects whose directory contains cwd, sorted deepest-first."""
    matches = [p for p in projects if is_inside(cwd, p.directory)]
    matches.sort(key=lambda p: len(_normalize(p.directory).parts), reverse=True)
    return matches
