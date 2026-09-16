"""Intégration SerialLink + RtuMaster sur pseudo-terminal (Linux uniquement)."""

import threading

import pytest

from modbusai.modbus.master import RtuMaster
from modbusai.modbus.records import ExchangeStatus, FunctionCode, Request
from modbusai.transport.records import LinkState, SerialSettings, TransmitNotAllowed, TransportError
from modbusai.transport.serial_link import SerialLink

# Sous Windows, ``pty`` et ``termios`` n'existent pas : tout le module est ignoré
# à la collecte, avant d'importer l'esclave simulé.
pytest.importorskip("pty", reason="pseudo-terminal Linux requis")
from tests.fake_slave import FakeSlave  # noqa: E402


@pytest.fixture
def slave():
    with FakeSlave(slave_id=1, delay_ms=20) as s:
        yield s


@pytest.fixture
def link(slave):
    settings = SerialSettings(slave.port, baudrate=19200, response_timeout_ms=300)
    lk = SerialLink(settings)
    lk.open()
    assert lk.state is LinkState.OPEN
    yield lk
    lk.close()
    assert lk.state is LinkState.CLOSED


def test_read_holding_ok(slave, link):
    rec = RtuMaster(link).execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 2, 3))
    assert rec.status is ExchangeStatus.OK, rec.error_message
    assert rec.values == (20, 30, 40)
    assert rec.rx_frame is not None and rec.rx_frame.chunks
    assert 15 < rec.response_time_ms < 150  # 20 ms de délai esclave + latence pty
    assert rec.transaction_time_ms > rec.response_time_ms
    assert link.counters.frames_tx == 1 and link.counters.frames_rx == 1


def test_read_coils_and_writes(slave, link):
    m = RtuMaster(link)
    rec = m.execute(Request(1, FunctionCode.READ_COILS, 0, 5))
    assert rec.values == (0, 1, 0, 1, 0)
    assert m.execute(Request(1, FunctionCode.WRITE_SINGLE_REGISTER, 3, values=(1234,))).ok
    assert m.execute(Request(1, FunctionCode.WRITE_MULTIPLE_REGISTERS, 4, values=(7, 8))).ok
    assert m.execute(Request(1, FunctionCode.WRITE_SINGLE_COIL, 0, values=(1,))).ok
    assert m.execute(Request(1, FunctionCode.WRITE_MULTIPLE_COILS, 1, values=(0, 0, 1))).ok
    assert slave.holding[3] == 1234 and slave.holding[4] == 7 and slave.holding[5] == 8
    assert slave.coils[0] == 1 and slave.coils[1] == 0 and slave.coils[3] == 1
    rec = m.execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 3, 3))
    assert rec.values == (1234, 7, 8)


def test_timeout(slave, link):
    slave.mode = "silent"
    rec = RtuMaster(link).execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1))
    assert rec.status is ExchangeStatus.TIMEOUT
    assert rec.rx_frame is None


def test_crc_error_and_truncated(slave, link):
    slave.mode = "bad_crc"
    rec = RtuMaster(link).execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1))
    assert rec.status is ExchangeStatus.CRC_ERROR
    assert rec.rx_frame is not None and len(rec.rx_frame) == 7
    slave.mode = "truncated"
    rec = RtuMaster(link).execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1))
    assert rec.status is ExchangeStatus.CRC_ERROR
    assert len(rec.rx_frame) == 4


def test_modbus_exception(slave, link):
    rec = RtuMaster(link).execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 100, 1))
    assert rec.status is ExchangeStatus.MODBUS_EXCEPTION
    assert rec.exception_code == 2
    assert "Adresse" in rec.error_message


def test_wrong_slave_is_timeout(slave, link):
    rec = RtuMaster(link).execute(Request(7, FunctionCode.READ_HOLDING_REGISTERS, 0, 1))
    assert rec.status is ExchangeStatus.TIMEOUT


def test_passive_link_refuses_tx(slave):
    lk = SerialLink(SerialSettings(slave.port), allow_tx=False)
    lk.open()
    try:
        with pytest.raises(TransmitNotAllowed):
            lk.send(b"\x01\x03\x00\x00\x00\x01\x84\x0a")
    finally:
        lk.close()


def test_read_loop_sees_bus_traffic(slave, link):
    """read_loop (base du futur sniffer) voit passer une trame écrite par l'esclave."""
    import os

    stop = threading.Event()
    frames = []

    def listen():
        for f in link.read_loop(stop):
            frames.append(f)
            stop.set()

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    os.write(slave._master_fd, b"\x01\x03\x02\x00\x2a\x39\x8d")
    t.join(timeout=2)
    stop.set()
    assert frames and frames[0].data == b"\x01\x03\x02\x00\x2a\x39\x8d"


def test_open_missing_port():
    lk = SerialLink(SerialSettings("/dev/does-not-exist"))
    with pytest.raises(TransportError):
        lk.open()
    assert lk.state is LinkState.ERROR
    assert lk.last_error


def test_send_on_closed_link():
    lk = SerialLink(SerialSettings("/dev/does-not-exist"))
    with pytest.raises(TransportError):
        lk.send(b"\x01")
