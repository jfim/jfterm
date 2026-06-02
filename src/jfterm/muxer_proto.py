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
