from jfterm.launcher_items import (
    FlashAction,
    JumpAction,
    NewTabAction,
    StartupAction,
    build_items,
)
from jfterm.models import (
    FlashCommand,
    StartupCommand,
    TerminalTab,
    Workspace,
)


def test_build_items_empty_workspace_yields_nothing():
    ws = Workspace()
    assert build_items(ws) == []


def test_build_items_project_with_no_extras_emits_only_new_tab():
    ws = Workspace()
    ws.add_project(name="Alpha", directory="/tmp/a")
    items = build_items(ws)
    assert len(items) == 1
    assert items[0].display == "Alpha: New Shell Tab"
    assert isinstance(items[0].action, NewTabAction)


def test_build_items_emits_startup_row_only_when_startup_commands_present():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    p.startup_commands.append(StartupCommand(command="ls"))
    items = build_items(ws)
    displays = [i.display for i in items]
    assert "Alpha: Run Startup Commands" in displays
    assert any(isinstance(i.action, StartupAction) for i in items)


def test_build_items_emits_one_flash_row_per_flash_command():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    p.flash_commands.extend(
        [
            FlashCommand(name="Push", command="git push"),
            FlashCommand(name="Pull", command="git pull"),
        ]
    )
    items = build_items(ws)
    displays = [i.display for i in items]
    assert "Alpha: ⚡ Push" in displays
    assert "Alpha: ⚡ Pull" in displays
    flash_actions = [i.action for i in items if isinstance(i.action, FlashAction)]
    assert {a.flash.name for a in flash_actions} == {"Push", "Pull"}


def test_build_items_emits_jump_row_per_tab_in_project():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    t = TerminalTab(title="bash")
    p.add_tab(t)
    items = build_items(ws)
    displays = [i.display for i in items]
    assert "Alpha: ▦ bash" in displays


def test_build_items_uses_unsorted_label_for_unsorted_tabs():
    ws = Workspace()
    t = TerminalTab(title="scratch")
    ws.unsorted.add_tab(t)
    items = build_items(ws)
    assert len(items) == 1
    assert items[0].display == "Unsorted: ▦ scratch"
    assert isinstance(items[0].action, JumpAction)


def test_build_items_no_new_tab_or_startup_for_unsorted():
    ws = Workspace()
    ws.unsorted.add_tab(TerminalTab(title="x"))
    displays = [i.display for i in build_items(ws)]
    assert "Unsorted: New Shell Tab" not in displays
    assert "Unsorted: Run Startup Commands" not in displays


def test_build_items_skips_archived_projects():
    ws = Workspace()
    ws.add_project(name="Alive", directory="/tmp/a")
    z = ws.add_project(name="Zombie", directory="/tmp/z")
    z.archived = True
    z.flash_commands.append(FlashCommand(name="Push", command="git push"))
    displays = [i.display for i in build_items(ws)]
    assert any(d.startswith("Alive:") for d in displays)
    assert not any(d.startswith("Zombie:") for d in displays)


def test_build_items_untitled_tab_falls_back():
    ws = Workspace()
    p = ws.add_project(name="Alpha", directory="/tmp/a")
    p.add_tab(TerminalTab(title=""))
    displays = [i.display for i in build_items(ws)]
    assert "Alpha: ▦ (untitled)" in displays
