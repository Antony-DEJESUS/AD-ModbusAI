import pytest

from modbusai.modbus.crc import append_crc, check_crc, crc16


def test_known_vector():
    assert crc16(bytes.fromhex("010300000001")) == 0x0A84
    assert append_crc(bytes.fromhex("010300000001")) == bytes.fromhex("010300000001840A")


def test_check_crc():
    assert check_crc(bytes.fromhex("010300000001840A"))
    assert not check_crc(bytes.fromhex("010300000001840B"))
    assert not check_crc(b"\x01\x03")


@pytest.mark.parametrize(
    "payload",
    [b"", b"\x00", bytes(range(256)), bytes.fromhex("1110000500020400010002"), b"\xff" * 300],
)
def test_against_pymodbus_oracle(payload):
    rtu = pytest.importorskip("pymodbus.framer.rtu")
    # pymodbus renvoie le CRC dans l'ordre des octets sur le fil (poids faible d'abord)
    assert append_crc(payload)[-2:] == rtu.FramerRTU.compute_CRC(payload).to_bytes(2, "big")
