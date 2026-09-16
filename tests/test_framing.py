from datetime import datetime

from modbusai.transport.framing import RtuFramer
from modbusai.transport.records import ByteChunk, Direction

MS = 1_000_000


def test_single_frame_from_multiple_chunks():
    f = RtuFramer(gap_ns=5 * MS)
    assert f.feed(ByteChunk(b"\x01\x03", 0)) == []
    assert f.feed(ByteChunk(b"\x02\x00\x00", 2 * MS)) == []
    assert f.flush(4 * MS) is None  # silence pas encore acquis
    frame = f.flush(9 * MS)
    assert frame is not None
    assert frame.data == b"\x01\x03\x02\x00\x00"
    assert frame.direction is Direction.RX
    assert frame.t_first_ns == 0 and frame.t_last_ns == 2 * MS
    assert frame.duration_ms == 2.0
    assert len(frame.chunks) == 2
    assert frame.silence_before_ns is None
    assert isinstance(frame.wall_time, datetime)
    assert not f.has_pending


def test_gap_splits_frames_and_records_silence():
    f = RtuFramer(gap_ns=5 * MS)
    f.feed(ByteChunk(b"\x01\x03\x00\x00\x00\x01\x84\x0a", 0))
    closed = f.feed(ByteChunk(b"\x01\x03\x02\x00\x00\xb8\x44", 20 * MS))
    assert len(closed) == 1
    assert closed[0].hex == "01 03 00 00 00 01 84 0A"
    second = f.flush()
    assert second is not None
    assert second.data.startswith(b"\x01\x03\x02")
    assert second.silence_before_ns == 20 * MS


def test_empty_chunk_ignored_and_reset():
    f = RtuFramer(gap_ns=5 * MS)
    assert f.feed(ByteChunk(b"", 0)) == []
    assert not f.has_pending
    f.feed(ByteChunk(b"\x01", 0))
    f.reset()
    assert f.flush() is None
