from __future__ import annotations

from jfterm.models import FlashCommand


def wrap_flash_command(fc: FlashCommand) -> str:
    """Build the shell string fed to the freshly spawned shell.

    With keep_open_on_success the command is returned as-is; the shell
    naturally remains after it finishes regardless of exit status.

    Otherwise the command is grouped and followed by exit-on-success /
    failure-message-and-stay logic. The brace group ensures embedded
    semicolons or && operators don't escape the wrapper.
    """
    if fc.keep_open_on_success:
        return fc.command
    return (
        "{ " + fc.command + "; }; __ec=$?; "
        "if [ $__ec -eq 0 ]; then exit; "
        'else echo "Command failed (exit $__ec)"; fi'
    )


def unwrap_flash_title(title: str, original: str) -> str:
    """Reverse `wrap_flash_command` for display purposes.

    The shell echoes the wrapped command line into the window title, which
    leaks the brace group and exit-code plumbing into the UI. If `title`
    matches the wrapped form of `original`, return `original` so callers
    can show the user what they actually typed.
    """
    if not title or not original:
        return title
    wrapped = wrap_flash_command(
        FlashCommand(name="", command=original, keep_open_on_success=False)
    )
    # Bash's DEBUG-trap title hooks may emit the full wrapped string, the
    # brace-group prefix only (`{ cmd; };`), or the brace group without the
    # trailing semicolon — accept all of them.
    candidates = {
        wrapped,
        "{ " + original + "; }",
        "{ " + original + "; };",
    }
    if title in candidates:
        return original
    return title
