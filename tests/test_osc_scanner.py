from jfterm.osc_scanner import OscScanner, ProgressEvent


def test_passthrough_plain_text():
    scanner = OscScanner()
    out, events = scanner.feed(b"hello world")
    assert out == b"hello world"
    assert events == []


def test_passthrough_other_osc_unchanged():
    scanner = OscScanner()
    # OSC 7 (cwd) should NOT be touched.
    data = b"prefix\x1b]7;file:///tmp\x1b\\suffix"
    out, events = scanner.feed(data)
    assert out == data
    assert events == []


def test_parses_state_1_with_value_st_terminator():
    scanner = OscScanner()
    out, events = scanner.feed(b"before\x1b]9;4;1;42\x1b\\after")
    assert out == b"beforeafter"
    assert events == [ProgressEvent(state=1, value=42)]


def test_parses_state_1_with_value_bel_terminator():
    scanner = OscScanner()
    out, events = scanner.feed(b"\x1b]9;4;1;75\x07")
    assert out == b""
    assert events == [ProgressEvent(state=1, value=75)]


def test_parses_state_0_clear():
    scanner = OscScanner()
    out, events = scanner.feed(b"\x1b]9;4;0\x1b\\")
    assert out == b""
    assert events == [ProgressEvent(state=0, value=0)]


def test_parses_state_2_error_no_value():
    scanner = OscScanner()
    out, events = scanner.feed(b"\x1b]9;4;2;0\x1b\\")
    assert out == b""
    assert events == [ProgressEvent(state=2, value=0)]


def test_parses_state_3_indeterminate():
    scanner = OscScanner()
    out, events = scanner.feed(b"\x1b]9;4;3\x1b\\")
    assert out == b""
    assert events == [ProgressEvent(state=3, value=0)]


def test_parses_state_4_paused():
    scanner = OscScanner()
    out, events = scanner.feed(b"\x1b]9;4;4;50\x1b\\")
    assert out == b""
    assert events == [ProgressEvent(state=4, value=50)]


def test_multiple_sequences_in_one_chunk():
    scanner = OscScanner()
    out, events = scanner.feed(b"a\x1b]9;4;1;10\x1b\\b\x1b]9;4;1;90\x1b\\c")
    assert out == b"abc"
    assert events == [
        ProgressEvent(state=1, value=10),
        ProgressEvent(state=1, value=90),
    ]


def test_unknown_osc_passes_through_unchanged():
    scanner = OscScanner()
    raw = b"\x1b]133;A\x1b\\"
    out, events = scanner.feed(raw)
    assert out == raw
    assert events == []


def test_split_at_every_byte_boundary():
    full = b"x\x1b]9;4;1;42\x1b\\y"
    for split in range(1, len(full)):
        scanner = OscScanner()
        out1, ev1 = scanner.feed(full[:split])
        out2, ev2 = scanner.feed(full[split:])
        assert out1 + out2 == b"xy", f"split={split}"
        assert ev1 + ev2 == [ProgressEvent(state=1, value=42)], f"split={split}"


def test_split_between_st_bytes():
    # Boundary lands exactly between \x1b and \\ of the ST terminator.
    scanner = OscScanner()
    out1, ev1 = scanner.feed(b"\x1b]9;4;1;5\x1b")
    out2, ev2 = scanner.feed(b"\\tail")
    assert out1 + out2 == b"tail"
    assert ev1 + ev2 == [ProgressEvent(state=1, value=5)]


def test_carry_preserved_across_no_op_feed():
    scanner = OscScanner()
    out1, ev1 = scanner.feed(b"\x1b]9;4;1;5")
    assert out1 == b""
    assert ev1 == []
    out2, ev2 = scanner.feed(b"")
    assert out2 == b""
    assert ev2 == []
    out3, ev3 = scanner.feed(b"\x1b\\done")
    assert out3 == b"done"
    assert ev3 == [ProgressEvent(state=1, value=5)]


def test_runaway_sequence_flushes_introducer_and_recovers():
    scanner = OscScanner()
    # 300 bytes of garbage after \x1b] with no terminator.
    junk = b"X" * 300
    out1, ev1 = scanner.feed(b"\x1b]" + junk)
    # The introducer should be flushed as data; junk continues being scanned.
    assert b"\x1b]" in out1
    assert ev1 == []
    # Now feed a proper sequence; carry must be empty so it parses cleanly.
    out2, ev2 = scanner.feed(b"\x1b]9;4;1;5\x1b\\")
    assert out2 == b""
    assert ev2 == [ProgressEvent(state=1, value=5)]
