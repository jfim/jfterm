import json

from jfterm import muxer_proto as mp


def test_frame_type_values_are_stable():
    assert mp.PROTO_VERSION == 1
    assert mp.FrameType.HELLO == 1
    assert mp.FrameType.HELLO_OK == 2
    assert mp.FrameType.LIST == 3
    assert mp.FrameType.SESSIONS == 4
    assert mp.FrameType.ATTACH_OR_OPEN == 5
    assert mp.FrameType.INPUT == 6
    assert mp.FrameType.RESIZE == 7
    assert mp.FrameType.CLOSE == 8
    assert mp.FrameType.DATA == 9
    assert mp.FrameType.STATUS == 10
    assert mp.FrameType.EXIT == 11


def test_encode_frame_raw_bytes():
    frame = mp.encode_frame(mp.FrameType.DATA, b"hi")
    assert frame == bytes([9, 0, 0, 0, 2]) + b"hi"


def test_encode_json_frame_roundtrips_shape():
    frame = mp.encode_json_frame(mp.FrameType.RESIZE, {"cols": 80, "rows": 24})
    ftype = frame[0]
    (length,) = mp.struct.Struct(">I").unpack(frame[1:5])
    payload = frame[5:]
    assert ftype == mp.FrameType.RESIZE
    assert length == len(payload)
    assert json.loads(payload) == {"cols": 80, "rows": 24}
