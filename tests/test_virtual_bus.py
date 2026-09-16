"""Maître, serveur esclave et espion sur un bus virtuel (Linux uniquement)."""

import threading
import time

import pytest

pytest.importorskip("pty", reason="pseudo-terminal Linux requis")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from modbusai.analysis.identification import decode_device_id  # noqa: E402
from modbusai.analysis.sniffer import PassiveDecoder  # noqa: E402
from modbusai.modbus.master import RtuMaster  # noqa: E402
from modbusai.modbus.records import ExchangeStatus, FunctionCode, Request  # noqa: E402
from modbusai.modbus.slave import DataStore, SlaveConfig, SlaveHandler, Table  # noqa: E402
from modbusai.transport.records import SerialSettings  # noqa: E402
from modbusai.transport.serial_link import SerialLink  # noqa: E402
from tests.virtual_bus import VirtualBus  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


class ThreadedSlave:
    """Serveur esclave dans un thread Python, même boucle que SlaveWorker.run."""

    def __init__(self, port: str, config: SlaveConfig, store: DataStore | None = None, gap_ms: float | None = None):
        self.store = store or DataStore()
        self.handler = SlaveHandler(self.store, config)
        settings = SerialSettings(port, response_timeout_ms=200, inter_frame_delay_ms=gap_ms)
        self.link = SerialLink(settings, allow_tx=True)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self.link.open()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)
        self.link.close()

    def _run(self):
        for frame in self.link.read_loop(self._stop):
            result = self.handler.handle(frame.data)
            if result.response is not None:
                if self.handler.config.response_delay_ms:
                    time.sleep(self.handler.config.response_delay_ms / 1000)
                self.link.send(result.response)


def test_master_reads_and_writes_slave_server(qapp):
    cfg = SlaveConfig(slave_ids={1, 5}, limits={Table.HOLDING_REGISTERS: 1000})
    with VirtualBus(2) as bus, ThreadedSlave(bus.ports[1], cfg) as slave:
        slave.store.set(Table.HOLDING_REGISTERS, 0, [11, 22, 33])
        slave.store.set(Table.COILS, 0, [1, 1, 0, 1])
        link = SerialLink(SerialSettings(bus.ports[0], response_timeout_ms=300))
        link.open()
        try:
            m = RtuMaster(link)
            rec = m.execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 3))
            assert rec.status is ExchangeStatus.OK and rec.values == (11, 22, 33)
            assert m.execute(Request(5, FunctionCode.READ_COILS, 0, 4)).values == (1, 1, 0, 1)
            assert m.execute(Request(1, FunctionCode.WRITE_MULTIPLE_REGISTERS, 1, values=(7, 8))).ok
            assert slave.store.get(Table.HOLDING_REGISTERS, 0, 3) == [11, 7, 8]
            exc = m.execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 999, 2))
            assert exc.status is ExchangeStatus.MODBUS_EXCEPTION and exc.exception_code == 2
            absent = m.execute(Request(9, FunctionCode.READ_HOLDING_REGISTERS, 0, 1), timeout_ms=150)
            assert absent.status is ExchangeStatus.TIMEOUT
            ident = m.execute(Request(1, FunctionCode.READ_DEVICE_ID, 1, 0))
            assert ident.ok and decode_device_id(bytes(ident.values)).vendor == "ModbusAI"
        finally:
            link.close()


def test_fault_injection_seen_by_master(qapp):
    cfg = SlaveConfig(slave_ids={1}, response_delay_ms=60, corrupt_ratio=1.0)
    with VirtualBus(2) as bus, ThreadedSlave(bus.ports[1], cfg):
        link = SerialLink(SerialSettings(bus.ports[0], response_timeout_ms=300))
        link.open()
        try:
            rec = RtuMaster(link).execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1))
            assert rec.status is ExchangeStatus.CRC_ERROR
            assert rec.response_time_ms is not None and rec.response_time_ms >= 55
        finally:
            link.close()


def test_sniffer_sees_master_slave_dialogue(qapp):
    with VirtualBus(3) as bus, ThreadedSlave(bus.ports[1], SlaveConfig(slave_ids={1})) as slave:
        slave.store.set(Table.HOLDING_REGISTERS, 0, [0x1234])
        spy = SerialLink(SerialSettings(bus.ports[2], response_timeout_ms=300), allow_tx=False)
        spy.open()
        decoder = PassiveDecoder(300)
        stop = threading.Event()
        frames = []

        def listen():
            for f in spy.read_loop(stop):
                frames.extend(decoder.feed(f))

        t = threading.Thread(target=listen, daemon=True)
        t.start()
        link = SerialLink(SerialSettings(bus.ports[0], response_timeout_ms=300))
        link.open()
        try:
            m = RtuMaster(link)
            for _ in range(3):
                assert m.execute(Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1)).ok
                time.sleep(0.05)
            m.execute(Request(4, FunctionCode.READ_HOLDING_REGISTERS, 0, 1), timeout_ms=120)  # sans réponse
            time.sleep(0.5)
        finally:
            stop.set()
            t.join(timeout=2)
            link.close()
            spy.close()
        decoder.flush(10**18)
        done = decoder.pop_completed()
        statuses = [tr.status for tr in done]
        assert statuses.count(ExchangeStatus.OK) == 3
        assert ExchangeStatus.TIMEOUT in statuses
        ok = next(tr for tr in done if tr.status is ExchangeStatus.OK)
        assert ok.response is not None and ok.response.frame.data[3:5] == b"\x12\x34"
        assert ok.response_time_ms is not None and 0 < ok.response_time_ms < 200
        assert decoder.counters.slaves_seen == {1, 4}
