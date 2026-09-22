"""Modbus TCP : enveloppe MBAP, liaison TCP, serveur esclave TCP, maître généralisé."""

import threading
import time

import pytest

from modbusai.analysis.identification import decode_device_id
from modbusai.modbus.master import ModbusMaster, TcpFraming
from modbusai.modbus.mbap import build_mbap, frame_length, parse_mbap
from modbusai.modbus.records import ExchangeStatus, FunctionCode, Request
from modbusai.modbus.slave import DataStore, SlaveConfig, SlaveHandler, Table
from modbusai.modbus.tcp_slave import make_tcp_frame_handler
from modbusai.transport.records import LinkState, TcpSettings, TransmitNotAllowed, TransportError
from modbusai.transport.tcp_link import TcpLink
from modbusai.transport.tcp_server import TcpServer


def test_mbap_roundtrip_and_errors():
    frame = build_mbap(0x1234, 17, bytes.fromhex("0300000001"))
    assert frame == bytes.fromhex("1234 0000 0006 11 0300000001".replace(" ", ""))
    assert frame_length(frame[:6]) == 12
    m = parse_mbap(frame)
    assert (m.transaction_id, m.unit_id, m.pdu) == (0x1234, 17, bytes.fromhex("0300000001"))
    with pytest.raises(ValueError):
        parse_mbap(frame[:-1])
    with pytest.raises(ValueError):
        parse_mbap(bytes.fromhex("1234 0001 0006 11 0300000001".replace(" ", "")))
    assert frame_length(b"\x00\x00\x00\x00\x00\x01") is None
    with pytest.raises(ValueError):
        build_mbap(0, 1, b"")


def test_tcp_framing_transaction_check():
    f = TcpFraming()
    req = Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1)
    tx = f.encode(req)
    tid = int.from_bytes(tx[0:2], "big")
    good = build_mbap(tid, 1, bytes.fromhex("0302002A"))
    assert f.decode(req, good) == (42,)
    from modbusai.modbus.exceptions import BadResponse, ModbusException

    with pytest.raises(BadResponse):
        f.decode(req, build_mbap(tid + 1, 1, bytes.fromhex("0302002A")))
    with pytest.raises(ModbusException):
        f.decode(req, build_mbap(tid, 1, bytes.fromhex("8302")))


class TcpSlaveThread:
    def __init__(self, config: SlaveConfig, delay_ms: float = 0.0):
        self.store = DataStore()
        self.handler = SlaveHandler(self.store, config)
        self.handled = []
        self.server = TcpServer(
            "127.0.0.1",
            0,
            make_tcp_frame_handler(self.handler, lambda r, c: self.handled.append(r)),
            response_delay_ms=delay_ms,
        )
        self._stop = threading.Event()
        self._thread = threading.Thread(target=lambda: self.server.serve(self._stop), daemon=True)

    def __enter__(self):
        self.server.open()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)
        self.server.close()

    @property
    def settings(self) -> TcpSettings:
        return TcpSettings("127.0.0.1", self.server.bound_port, response_timeout_ms=500, connect_timeout_ms=1000)


def test_master_over_tcp():
    with TcpSlaveThread(SlaveConfig(slave_ids={1, 5}, limits={Table.HOLDING_REGISTERS: 1000})) as slave:
        slave.store.set(Table.HOLDING_REGISTERS, 0, [11, 22, 33])
        link = TcpLink(slave.settings)
        link.open()
        assert link.state is LinkState.OPEN
        try:
            m = ModbusMaster(link)
            assert isinstance(m.framing, TcpFraming)
            rec = m.execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 3))
            assert rec.status is ExchangeStatus.OK, rec.error_message
            assert rec.values == (11, 22, 33)
            assert rec.response_time_ms is not None and rec.response_time_ms < 200
            assert rec.tx_frame.data[6] == 1 and len(rec.rx_frame) == 6 + 3 + 6
            assert m.execute(Request(5, FunctionCode.WRITE_MULTIPLE_REGISTERS, 1, values=(7, 8))).ok
            assert slave.store.get(Table.HOLDING_REGISTERS, 0, 3) == [11, 7, 8]
            exc = m.execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 999, 2))
            assert exc.status is ExchangeStatus.MODBUS_EXCEPTION and exc.exception_code == 2
            absent = m.execute(Request(9, FunctionCode.READ_HOLDING_REGISTERS, 0, 1), timeout_ms=150)
            assert absent.status is ExchangeStatus.TIMEOUT
            ident = m.execute(Request(1, FunctionCode.READ_DEVICE_ID, 1, 0))
            assert ident.ok and decode_device_id(bytes(ident.values)).vendor == "ModbusAI"
            assert slave.server.counters.connections == 1 and slave.server.counters.frames_rx == 5
            kinds = [h.kind for h in slave.handled]
            assert kinds == ["réponse", "réponse", "exception", "ignorée", "réponse"]
        finally:
            link.close()
        assert link.state is LinkState.CLOSED


def test_tcp_fault_injection_and_delay():
    cfg = SlaveConfig(slave_ids={1}, corrupt_ratio=1.0)
    with TcpSlaveThread(cfg, delay_ms=60) as slave:
        link = TcpLink(slave.settings)
        link.open()
        try:
            rec = ModbusMaster(link).execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1))
            assert rec.status is ExchangeStatus.BAD_RESPONSE  # pas de CRC en TCP : enveloppe incohérente
            assert rec.response_time_ms is not None and rec.response_time_ms >= 55
        finally:
            link.close()


def test_tcp_connection_refused_and_closed_by_peer():
    lk = TcpLink(TcpSettings("127.0.0.1", 1, connect_timeout_ms=500))
    with pytest.raises(TransportError):
        lk.open()
    assert lk.state is LinkState.ERROR
    with TcpSlaveThread(SlaveConfig(slave_ids={1})) as slave:
        link = TcpLink(slave.settings)
        link.open()
        m = ModbusMaster(link)
        assert m.execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1)).ok
        slave.server.close()  # coupe la connexion côté serveur
        time.sleep(0.1)
        rec = m.execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1))
        assert rec.status in (ExchangeStatus.TRANSPORT_ERROR, ExchangeStatus.TIMEOUT)
        link.close()


def test_tcp_passive_refuses_tx():
    with TcpSlaveThread(SlaveConfig(slave_ids={1})) as slave:
        link = TcpLink(slave.settings, allow_tx=False)
        link.open()
        with pytest.raises(TransmitNotAllowed):
            link.send(b"\x00")
        link.close()


def test_two_clients_served():
    with TcpSlaveThread(SlaveConfig(slave_ids={1})) as slave:
        a, b = TcpLink(slave.settings), TcpLink(slave.settings)
        a.open()
        b.open()
        try:
            assert ModbusMaster(a).execute(Request(1, FunctionCode.WRITE_SINGLE_REGISTER, 0, values=(5,))).ok
            rec = ModbusMaster(b).execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1))
            assert rec.values == (5,)
            assert slave.server.counters.active == 2
        finally:
            a.close()
            b.close()
        time.sleep(0.1)
        assert slave.server.counters.active == 0


def test_server_reports_connected_masters():
    """Le serveur esclave doit dire combien de maîtres sont connectés et lesquels."""
    seen: list[tuple[str, ...]] = []
    with TcpSlaveThread(SlaveConfig(slave_ids={1})) as slave:
        slave.server.on_clients = seen.append
        first = TcpLink(slave.settings)
        first.open()
        second = TcpLink(slave.settings)
        second.open()
        # Délai large : la boucle sort dès que la condition tient, l'attente ne
        # coûte donc rien quand tout va bien, et le test ne casse pas sous charge.
        deadline = time.monotonic() + 10
        while len(slave.server.clients) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(slave.server.clients) == 2
        assert all(name.startswith("127.0.0.1:") for name in slave.server.clients)
        assert slave.server.counters.active == 2
        first.close()
        deadline = time.monotonic() + 10
        while len(slave.server.clients) > 1 and time.monotonic() < deadline:
            # une socket fermée n'est vue qu'à la prochaine lecture
            ModbusMaster(second).execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1))
            time.sleep(0.05)
        assert len(slave.server.clients) == 1
        second.close()
    assert seen and seen[-1] == ()  # la fermeture du serveur vide la liste
