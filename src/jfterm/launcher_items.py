from __future__ import annotations

from dataclasses import dataclass

from jfterm.models import FlashCommand, Project, Tab, Workspace


@dataclass(frozen=True)
class FlashAction:
    project: Project
    flash: FlashCommand


@dataclass(frozen=True)
class NewTabAction:
    project: Project


@dataclass(frozen=True)
class StartupAction:
    project: Project


@dataclass(frozen=True)
class JumpAction:
    tab: Tab


Action = FlashAction | NewTabAction | StartupAction | JumpAction


@dataclass(frozen=True)
class LauncherItem:
    display: str
    action: Action


def _tab_title(t: Tab) -> str:
    return t.title or "(untitled)"


def build_items(ws: Workspace) -> list[LauncherItem]:
    items: list[LauncherItem] = []
    for p in ws.projects:
        if p.archived:
            continue
        items.append(LauncherItem(f"{p.name}: New Shell Tab", NewTabAction(p)))
        if p.startup_commands:
            items.append(
                LauncherItem(f"{p.name}: Run Startup Commands", StartupAction(p))
            )
        for fc in p.flash_commands:
            items.append(LauncherItem(f"{p.name}: ⚡ {fc.name}", FlashAction(p, fc)))
        for t in p.tabs:
            items.append(LauncherItem(f"{p.name}: ▦ {_tab_title(t)}", JumpAction(t)))
    for t in ws.unsorted.tabs:
        items.append(LauncherItem(f"Unsorted: ▦ {_tab_title(t)}", JumpAction(t)))
    return items
