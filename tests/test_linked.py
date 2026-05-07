import pytest

from jfterm.linked import LinkedSpec, parse_linked


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Not linked
        ("echo hi", None),
        ("https://example.com", None),
        ("", None),
        ("   ", None),
        ("linked:", None),  # nothing after prefix
        ("linkedfoo: x y", None),  # prefix must be exactly "linked: "
        # Auto mode
        ("linked: auto jupyter notebook", LinkedSpec(url=None, command="jupyter notebook")),
        ("linked:   auto   jupyter notebook", LinkedSpec(url=None, command="jupyter notebook")),
        ("linked: AUTO jupyter notebook", LinkedSpec(url=None, command="jupyter notebook")),
        # Explicit URL
        (
            "linked: http://localhost:4200 quarto preview",
            LinkedSpec(url="http://localhost:4200", command="quarto preview"),
        ),
        (
            "linked: https://localhost:8888 jupyter notebook --no-browser",
            LinkedSpec(url="https://localhost:8888", command="jupyter notebook --no-browser"),
        ),
        # Command preserved verbatim including shell metacharacters
        (
            "linked: auto a && b; c",
            LinkedSpec(url=None, command="a && b; c"),
        ),
        # Missing command after url is invalid
        ("linked: auto", None),
        ("linked: http://localhost:4200", None),
        # Unrecognized first token (not auto, not http(s)) is invalid
        ("linked: ftp://x cmd", None),
        ("linked: localhost:4200 cmd", None),
    ],
)
def test_parse_linked(text: str, expected: LinkedSpec | None) -> None:
    assert parse_linked(text) == expected
