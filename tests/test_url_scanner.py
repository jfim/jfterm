from jfterm.url_scanner import UrlScanner


def test_scanner_starts_empty():
    s = UrlScanner()
    assert s.first_url() is None


def test_scanner_finds_url_in_one_chunk():
    s = UrlScanner()
    s.feed(b"Server running at http://localhost:4200/ ready\n")
    assert s.first_url() == "http://localhost:4200/"


def test_scanner_finds_first_url_only():
    s = UrlScanner()
    s.feed(b"start http://a.test/x then http://b.test/y end")
    assert s.first_url() == "http://a.test/x"


def test_scanner_handles_url_split_across_chunks():
    s = UrlScanner()
    s.feed(b"Listening on http://localh")
    assert s.first_url() is None
    s.feed(b"ost:8888/?token=abc\n")
    assert s.first_url() == "http://localhost:8888/?token=abc"


def test_scanner_supports_https():
    s = UrlScanner()
    s.feed(b"open https://localhost:9443/app\n")
    assert s.first_url() == "https://localhost:9443/app"


def test_scanner_strips_trailing_punctuation():
    s = UrlScanner()
    s.feed(b"Visit http://localhost:4200/.\n")
    assert s.first_url() == "http://localhost:4200/"


def test_scanner_strips_ansi_color_escapes():
    # Many dev servers wrap URLs in ANSI escapes (e.g. underline + color).
    s = UrlScanner()
    s.feed(b"\x1b[1mLocal:\x1b[0m  \x1b[36mhttp://localhost:5173/\x1b[0m\n")
    assert s.first_url() == "http://localhost:5173/"


def test_scanner_caps_buffer_to_avoid_unbounded_growth():
    s = UrlScanner(max_buffer=1024)
    # Feed garbage that will never match; buffer stays bounded.
    s.feed(b"x" * 10_000)
    s.feed(b"http://a.test/y\n")
    # Even after eviction, a clean match in the latest chunk is found.
    assert s.first_url() == "http://a.test/y"


def test_scanner_idempotent_after_match():
    s = UrlScanner()
    s.feed(b"http://a.test/1\n")
    assert s.first_url() == "http://a.test/1"
    # Subsequent feeds do not change the first match.
    s.feed(b"http://b.test/2\n")
    assert s.first_url() == "http://a.test/1"


def test_scanner_rewrites_0_0_0_0_to_loopback():
    s = UrlScanner()
    s.feed(b"Serving HTTP on 0.0.0.0 port 8765 (http://0.0.0.0:8765/)\n")
    assert s.first_url() == "http://127.0.0.1:8765/"


def test_scanner_rewrites_ipv6_unspecified_to_loopback():
    s = UrlScanner()
    s.feed(b"Listening on http://[::]:8080/app\n")
    assert s.first_url() == "http://[::1]:8080/app"


def test_scanner_does_not_rewrite_loopback_or_named_hosts():
    s = UrlScanner()
    s.feed(b"open http://localhost:5173/\n")
    assert s.first_url() == "http://localhost:5173/"


def test_scanner_does_not_rewrite_explicit_non_unspecified_ip():
    s = UrlScanner()
    s.feed(b"open http://192.168.1.5:8080/\n")
    assert s.first_url() == "http://192.168.1.5:8080/"


def test_scanner_does_not_rewrite_0_0_0_0_in_path_or_query():
    s = UrlScanner()
    s.feed(b"open http://example.test/?from=0.0.0.0 done\n")
    assert s.first_url() == "http://example.test/?from=0.0.0.0"


def test_scanner_preserves_userinfo_and_port_when_rewriting():
    s = UrlScanner()
    s.feed(b"open http://user:pw@0.0.0.0:9000/x done\n")
    assert s.first_url() == "http://user:pw@127.0.0.1:9000/x"
