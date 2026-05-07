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
