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
