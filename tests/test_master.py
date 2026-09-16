"""RtuMaster avec une liaison simulée : vérifie que chaque issue donne un enregistrement."""

from datetime import datetime

import pytest

from modbusai.modbus.crc import append_crc
from modbusai.modbus.master import RtuMaster
from modbusai.modbus.records import ExchangeStatus, FunctionCode, Request
from modbusai.transport.records import Direction, RawFrame, SerialSettings, TransportError

MS = 1_000_000


class FakeLink:
    def __init__(self, response: bytes | None, *, delay_ms: float = 3.0, fail_send: bool = False):
        self.settings = SerialSettings("COM9", response_timeout_ms=250)
        self.response = response
        self.delay_ns = int(delay_ms * MS)
        self.fail_send = fail_send
        self.sent: list[bytes] = []
        self._t = 1_000 * MS

    def send(self, data: bytes) -> RawFrame:
        if self.fail_send:
            raise TransportError("port disparu")
        self.sent.append(data)
        t0 = self._t
        self._t += 4 * MS
        return RawFrame(Direction.TX, data, t0, self._t, datetime.now())

    def receive(self, timeout_ms: float) -> RawFrame | None:
        if self.response is None:
            return None
        t0 = self._t + self.delay_ns
        return RawFrame(Direction.RX, self.response, t0, t0 + 6 * MS, datetime.now())


REQ = Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 2)


def test_ok():
    rec = RtuMaster(FakeLink(append_crc(bytes.fromhex("0103040001000A")))).execute(REQ)
    assert rec.status is ExchangeStatus.OK
    assert rec.values == (1, 10)
    assert rec.response_time_ms == pytest.approx(3.0)
    assert rec.transaction_time_ms == pytest.approx(13.0)
    assert rec.seq == 1 and rec.slave_id == 1 and rec.function is FunctionCode.READ_HOLDING_REGISTERS
    assert rec.tx_frame.hex == "01 03 00 00 00 02 C4 0B"


def test_timeout():
    rec = RtuMaster(FakeLink(None)).execute(REQ)
    assert rec.status is ExchangeStatus.TIMEOUT
    assert rec.rx_frame is None and rec.response_time_ms is None
    assert "250" in rec.error_message


def test_crc_error():
    bad = bytearray(append_crc(bytes.fromhex("0103040001000A")))
    bad[-1] ^= 0xFF
    rec = RtuMaster(FakeLink(bytes(bad))).execute(REQ)
    assert rec.status is ExchangeStatus.CRC_ERROR
    assert rec.rx_frame is not None


def test_modbus_exception():
    rec = RtuMaster(FakeLink(append_crc(bytes.fromhex("018302")))).execute(REQ)
    assert rec.status is ExchangeStatus.MODBUS_EXCEPTION
    assert rec.exception_code == 2


def test_bad_response():
    rec = RtuMaster(FakeLink(append_crc(bytes.fromhex("0203040001000A")))).execute(REQ)
    assert rec.status is ExchangeStatus.BAD_RESPONSE


def test_transport_error_still_records():
    rec = RtuMaster(FakeLink(None, fail_send=True)).execute(REQ)
    assert rec.status is ExchangeStatus.TRANSPORT_ERROR
    assert rec.tx_frame.data == append_crc(bytes.fromhex("010300000002"))


def test_sequence_increments():
    m = RtuMaster(FakeLink(None))
    assert m.execute(REQ).seq == 1
    assert m.execute(REQ).seq == 2
    assert m.seq == 2
    # Après reconnexion, la numérotation continue
    assert RtuMaster(FakeLink(None), seq_start=m.seq).execute(REQ).seq == 3


def test_invalid_request_raises():
    with pytest.raises(ValueError):
        RtuMaster(FakeLink(None)).execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 200))
