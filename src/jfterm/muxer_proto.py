"""TLV wire protocol shared between JFTerm (client) and jftermd (daemon).

This module is the canonical Python mirror of the muxer repo's PROTOCOL-v1.md.
Frame: [u8 type][u32 length big-endian][value … length bytes].
Hot-path frames (DATA, INPUT) carry raw terminal bytes; control frames carry
a JSON object encoded as UTF-8 bytes.
"""

from __future__ import annotations

import enum
import json
import struct

PROTO_VERSION = 1

_HEADER = struct.Struct(">BI")  # 1-byte type, 4-byte big-endian length


class FrameType(enum.IntEnum):
    HELLO = 1
    HELLO_OK = 2
    LIST = 3
    SESSIONS = 4
    ATTACH_OR_OPEN = 5
    INPUT = 6
    RESIZE = 7
    CLOSE = 8
    DATA = 9
    STATUS = 10
    EXIT = 11


def encode_frame(ftype: int, value: bytes) -> bytes:
    """One TLV frame: header + raw value bytes."""
    return _HEADER.pack(int(ftype), len(value)) + value


def encode_json_frame(ftype: int, obj: object) -> bytes:
    """A control frame whose value is a compact UTF-8 JSON object."""
    return encode_frame(ftype, json.dumps(obj).encode("utf-8"))


MAX_FRAME_LEN = 16 * 1024 * 1024  # 16 MiB hard cap per PROTOCOL-v1 §2


class ProtocolError(Exception):
    """A wire-format violation; the connection must be closed."""


class FrameDecoder:
    """Accumulates bytes and yields complete (type, value) frames.

    Tolerant of arbitrary chunk boundaries: a frame split across feed() calls
    (even inside the 5-byte header) is buffered until complete. A declared
    length above MAX_FRAME_LEN raises ProtocolError (caller closes the socket).
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self._buf.extend(data)
        out: list[tuple[int, bytes]] = []
        while True:
            if len(self._buf) < _HEADER.size:
                break
            ftype, length = _HEADER.unpack_from(self._buf, 0)
            if length > MAX_FRAME_LEN:
                raise ProtocolError(f"frame length {length} exceeds {MAX_FRAME_LEN}")
            end = _HEADER.size + length
            if len(self._buf) < end:
                break
            value = bytes(self._buf[_HEADER.size : end])
            del self._buf[:end]
            out.append((ftype, value))
        return out
