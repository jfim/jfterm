from jfterm.flash import wrap_flash_command
from jfterm.models import FlashCommand


def test_wrap_keep_open_returns_command_unchanged():
    fc = FlashCommand(name="X", command="echo hi", keep_open_on_success=True)
    assert wrap_flash_command(fc) == "echo hi"


def test_wrap_close_on_success_wraps_with_exit_logic():
    fc = FlashCommand(name="X", command="echo hi")
    out = wrap_flash_command(fc)
    assert out == (
        "{ echo hi; }; __ec=$?; if [ $__ec -eq 0 ]; then exit; "
        'else echo "Command failed (exit $__ec)"; fi'
    )


def test_wrap_handles_command_with_semicolons_and_and():
    fc = FlashCommand(name="X", command="a && b; c")
    out = wrap_flash_command(fc)
    assert out.startswith("{ a && b; c; }; ")
    assert "if [ $__ec -eq 0 ]; then exit;" in out
