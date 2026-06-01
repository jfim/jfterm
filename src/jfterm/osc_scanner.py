from dataclasses import dataclass

_MAX_CARRY = 256
_OSC_INTRO = b"\x1b]"
_ST = b"\x1b\\"
_BEL = b"\x07"


@dataclass(frozen=True)
class ProgressEvent:
    state: int
    value: int


@dataclass(frozen=True)
class PromptEvent:
    """OSC 133 marker. kind is one of 'A'|'B'|'C'|'D'.
    exit_status is set only for 'D' when the shell provides one, else None."""

    kind: str
    exit_status: int | None = None


Event = ProgressEvent | PromptEvent


class OscScanner:
    """Scan a byte stream for OSC 9;4 progress sequences and OSC 133 prompt markers.

    OSC 9;4 sequences are stripped from the output (not forwarded to VTE).
    OSC 133 sequences are passed through to VTE unchanged (it uses them for
    prompt markers), but also emit PromptEvents for in-process handling.
    All other bytes (plain text, other OSCs, CSI, etc.) are passed through
    unchanged. The hot path is bytes.find() — no per-byte Python loop.
    """

    def __init__(self) -> None:
        self._carry = b""

    def feed(self, chunk: bytes) -> tuple[bytes, list[Event]]:
        data = self._carry + chunk
        self._carry = b""
        out = bytearray()
        events: list[Event] = []

        i = 0
        n = len(data)
        while i < n:
            j = data.find(_OSC_INTRO, i)
            if j == -1:
                # Check if the data ends with a lone \x1b that could be the
                # start of an OSC introducer (\x1b]). If so, stash it as carry.
                tail = data[i:]
                if tail.endswith(b"\x1b"):
                    out += tail[:-1]
                    self._carry = b"\x1b"
                else:
                    out += tail
                break
            # Forward bytes before the OSC introducer.
            out += data[i:j]
            # Find the terminator (ST or BEL) starting after the introducer.
            term_st = data.find(_ST, j + 2)
            term_bel = data.find(_BEL, j + 2)
            term, term_len = _earliest(term_st, len(_ST), term_bel, len(_BEL))
            if term == -1:
                # No terminator yet. If we've already accumulated more than
                # the cap without finding one, this is malformed: flush the
                # opening bytes and continue past them.
                if n - j > _MAX_CARRY:
                    out += data[j : j + 2]
                    i = j + 2
                    continue
                # Otherwise stash the partial sequence as carry and stop.
                self._carry = data[j:]
                break
            body = data[j + 2 : term]
            progress_ev = _try_parse_progress(body)
            if progress_ev is not None:
                events.append(progress_ev)
                # Drop the entire OSC 9;4 sequence (introducer + body + term).
            else:
                prompt_ev = _try_parse_prompt(body)
                if prompt_ev is not None:
                    events.append(prompt_ev)
                # Pass OSC through unchanged (both known 133 and unknown OSCs).
                out += data[j : term + term_len]
            i = term + term_len

        return bytes(out), events


def _earliest(a: int, a_len: int, b: int, b_len: int) -> tuple[int, int]:
    if a == -1:
        return (b, b_len) if b != -1 else (-1, 0)
    if b == -1:
        return (a, a_len)
    if a < b:
        return (a, a_len)
    return (b, b_len)


def _try_parse_progress(body: bytes) -> ProgressEvent | None:
    # Body looks like: 9;4;<state>[;<value>]
    if not body.startswith(b"9;4"):
        return None
    parts = body.split(b";")
    # parts[0] == b"9", parts[1] == b"4"
    if len(parts) < 3:
        return None
    try:
        state = int(parts[2])
    except ValueError:
        return None
    if state not in (0, 1, 2, 3, 4):
        return None
    value = 0
    if len(parts) >= 4 and parts[3]:
        try:
            value = int(parts[3])
        except ValueError:
            value = 0
    return ProgressEvent(state=state, value=value)


def _try_parse_prompt(body: bytes) -> PromptEvent | None:
    # Body looks like: 133;<kind>[;<exit_status>]
    if not body.startswith(b"133;"):
        return None
    rest = body[4:]  # everything after "133;"
    parts = rest.split(b";", 1)
    if not parts or not parts[0]:
        return None
    kind_bytes = parts[0]
    if len(kind_bytes) != 1 or kind_bytes not in (b"A", b"B", b"C", b"D"):
        return None
    kind = kind_bytes.decode()
    exit_status: int | None = None
    if kind == "D" and len(parts) == 2 and parts[1]:
        try:
            exit_status = int(parts[1])
        except ValueError:
            exit_status = None
    return PromptEvent(kind=kind, exit_status=exit_status)
