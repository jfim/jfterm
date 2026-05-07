import pytest

from jfterm.url_routing import is_web_url


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://example.com", True),
        ("http://example.com", True),
        ("HTTPS://example.com", True),
        ("HTTP://EXAMPLE.COM", True),
        ("  https://example.com  ", True),
        ("\thttp://localhost:4000\n", True),
        ("https://", True),
        ("httpsfoo://x", False),
        ("ftp://example.com", False),
        ("file:///etc/passwd", False),
        ("localhost:4000", False),
        ("", False),
        ("   ", False),
        ("npm run dev", False),
        ("echo https://example.com", False),
    ],
)
def test_is_web_url(text: str, expected: bool) -> None:
    assert is_web_url(text) is expected
