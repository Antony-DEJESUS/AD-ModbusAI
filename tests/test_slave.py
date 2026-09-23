import random

from modbusai import __version__
from modbusai.modbus.crc import append_crc, check_crc
from modbusai.modbus.pdu import build_adu, parse_response
from modbusai.modbus.records import FunctionCode as FC
from modbusai.modbus.records import Request
from modbusai.modbus.slave import DataStore, SlaveConfig, SlaveHandler, Table


def make():
    store = DataStore()
    store.set(Table.HOLDING_REGISTERS, 0, [10, 20, 30])
    store.set(Table.INPUT_REGISTERS, 5, [250])
    store.set(Table.COILS, 0, [1, 0, 1])
    store.set(Table.DISCRETE_INPUTS, 0, [0, 1])
    return store, SlaveHandler(store, SlaveConfig(slave_ids={1, 7}), rng=random.Random(0))


def roundtrip(handler, req):
    res = handler.handle(build_adu(req))
    assert res.response is not None, res
    return parse_response(req, res.response)


def test_reads():
    _, h = make()
    assert roundtrip(h, Request(1, FC.READ_HOLDING_REGISTERS, 0, 3)) == (10, 20, 30)
    assert roundtrip(h, Request(7, FC.READ_INPUT_REGISTERS, 5, 1)) == (250,)
    assert roundtrip(h, Request(1, FC.READ_COILS, 0, 3)) == (1, 0, 1)
    assert roundtrip(h, Request(1, FC.READ_DISCRETE_INPUTS, 0, 2)) == (0, 1)
    assert h.counters.responses == 4


def test_writes_update_store():
    store, h = make()
    assert roundtrip(h, Request(1, FC.WRITE_SINGLE_REGISTER, 1, values=(999,))) == ()
    assert roundtrip(h, Request(1, FC.WRITE_MULTIPLE_REGISTERS, 2, values=(5, 6))) == ()
    assert roundtrip(h, Request(1, FC.WRITE_SINGLE_COIL, 1, values=(1,))) == ()
    assert roundtrip(h, Request(1, FC.WRITE_MULTIPLE_COILS, 2, values=(0, 1, 1))) == ()
    assert store.get(Table.HOLDING_REGISTERS, 0, 4) == [10, 999, 5, 6]
    assert store.get(Table.COILS, 0, 5) == [1, 1, 0, 1, 1]
    assert h.counters.writes == 4
    assert store.version > 0


def test_exceptions_and_ignored():
    _, h = make()
    # hors table
    res = h.handle(append_crc(bytes.fromhex("0103FFFF0002")))
    assert res.kind == "exception" and res.response[1] == 0x83 and res.response[2] == 0x02
    # fonction inconnue
    res = h.handle(append_crc(bytes([1, 0x64, 0, 0])))
    assert res.kind == "exception" and res.response[2] == 0x01
    # autre adresse : silence
    res = h.handle(build_adu(Request(3, FC.READ_HOLDING_REGISTERS, 0, 1)))
    assert res.kind == "ignorée" and res.response is None
    # CRC faux : silence
    bad = bytearray(build_adu(Request(1, FC.READ_HOLDING_REGISTERS, 0, 1)))
    bad[-1] ^= 0xFF
    assert h.handle(bytes(bad)).kind == "invalide"
    # écho d'une réponse (grammaire de requête non respectée) : silence, pas d'exception
    assert h.handle(append_crc(bytes.fromhex("0103020000"))).kind == "ignorée"
    # broadcast : écrit sans répondre
    store = h.store
    res = h.handle(build_adu(Request(0, FC.WRITE_SINGLE_REGISTER, 0, values=(42,))))
    assert res.kind == "broadcast" and res.response is None
    assert store.get(Table.HOLDING_REGISTERS, 0) == [42]


def test_read_only_and_limits():
    store = DataStore()
    cfg = SlaveConfig(slave_ids={1}, read_only=True, limits={Table.HOLDING_REGISTERS: 100})
    h = SlaveHandler(store, cfg)
    res = h.handle(build_adu(Request(1, FC.WRITE_SINGLE_REGISTER, 0, values=(1,))))
    assert res.kind == "exception" and res.response[2] == 0x04
    res = h.handle(build_adu(Request(1, FC.READ_HOLDING_REGISTERS, 99, 2)))
    assert res.kind == "exception" and res.response[2] == 0x02
    assert h.handle(build_adu(Request(1, FC.READ_HOLDING_REGISTERS, 98, 2))).kind == "réponse"


def test_fault_injection():
    store = DataStore()
    h = SlaveHandler(store, SlaveConfig(slave_ids={1}, drop_ratio=0.5, corrupt_ratio=0.5), rng=random.Random(1))
    kinds = [h.handle(build_adu(Request(1, FC.READ_HOLDING_REGISTERS, 0, 1))).kind for _ in range(200)]
    assert 60 < kinds.count("perdue") < 140
    assert kinds.count("corrompue") > 20 and kinds.count("réponse") > 20
    corrupted = next(
        r
        for r in (h.handle(build_adu(Request(1, FC.READ_HOLDING_REGISTERS, 0, 1))) for _ in range(50))
        if r.kind == "corrompue"
    )
    assert not check_crc(corrupted.response)


def test_identification():
    _, h = make()
    from modbusai.analysis.identification import decode_device_id, decode_report_slave_id

    body = roundtrip(h, Request(1, FC.READ_DEVICE_ID, 1, 0))
    ident = decode_device_id(bytes(body))
    assert ident.vendor == "ModbusAI" and ident.revision == __version__
    rid = roundtrip(h, Request(1, FC.REPORT_SLAVE_ID, 0))
    assert "en marche" in decode_report_slave_id(bytes(rid))


def test_increment_animation():
    store = DataStore()
    store.increment(Table.HOLDING_REGISTERS, 0, 3, step=10)
    store.increment(Table.HOLDING_REGISTERS, 0, 3, step=10)
    assert store.get(Table.HOLDING_REGISTERS, 0, 4) == [20, 20, 20, 0]
    store.increment(Table.COILS, 0, 2)
    assert store.get(Table.COILS, 0, 3) == [1, 1, 0]
