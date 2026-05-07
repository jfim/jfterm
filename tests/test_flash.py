from jfterm.flash import unwrap_flash_title, wrap_flash_command
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


def test_unwrap_restores_original_when_title_matches_wrapped():
    fc = FlashCommand(name="X", command="mix phx.server")
    wrapped = wrap_flash_command(fc)
    assert unwrap_flash_title(wrapped, "mix phx.server") == "mix phx.server"


def test_unwrap_restores_original_from_brace_prefix():
    assert unwrap_flash_title("{ mix phx.server; };", "mix phx.server") == "mix phx.server"
    assert unwrap_flash_title("{ mix phx.server; }", "mix phx.server") == "mix phx.server"


def test_unwrap_handles_requoted_tail():
    # Bash may emit the wrapper tail with different quoting than we built.
    title = (
        "{ mix phx.server; }; __ec=$?; if [ $__ec -eq 0 ]; then exit; else echo Command failed; fi"
    )
    assert unwrap_flash_title(title, "mix phx.server") == "mix phx.server"


def test_unwrap_passes_through_unrelated_titles():
    assert unwrap_flash_title("user@host: ~", "mix phx.server") == "user@host: ~"
    assert unwrap_flash_title("", "mix phx.server") == ""
