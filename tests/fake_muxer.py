"""A fake jftermd peer for tests, built on socket.socketpair().

Hand `client_sock` to RemotePtyProxy/MuxerClient; drive the daemon side with
this helper: push DATA/STATUS/EXIT to the client and read the INPUT/RESIZE/
CLOSE/ATTACH_OR_OPEN frames the client sent.
"""

from __future__ import annotations

import json
import socket

from jfterm import muxer_proto as mp


class FakeMuxer:
    def __init__(self) -> None:
        self.client_sock, self.daemon_sock = socket.socketpair(socket.AF_UNIX)
        self.daemon_sock.setblocking(False)
        self._dec = mp.FrameDecoder()

    def push(self, ftype: int, value: bytes) -> None:
        self.daemon_sock.sendall(mp.encode_frame(ftype, value))

    def push_json(self, ftype: int, obj: object) -> None:
        self.daemon_sock.sendall(mp.encode_json_frame(ftype, obj))

    def read_frames(self) -> list[tuple[int, bytes]]:
        out: list[tuple[int, bytes]] = []
        while True:
            try:
                chunk = self.daemon_sock.recv(65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            out.extend(self._dec.feed(chunk))
        return out

    def read_json_frames(self) -> list[tuple[int, object]]:
        return [(t, json.loads(v) if v else None) for t, v in self.read_frames()]

    def close(self) -> None:
        self.client_sock.close()
        self.daemon_sock.close()
