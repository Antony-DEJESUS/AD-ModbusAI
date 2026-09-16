import pytest

from modbusai.modbus.crc import append_crc
from modbusai.modbus.exceptions import BadResponse, CrcError, ModbusException
from modbusai.modbus.pdu import build_adu, build_pdu, expected_response_length, parse_response
from modbusai.modbus.records import FunctionCode as FC
from modbusai.modbus.records import Request


@pytest.mark.parametrize(
    ("req", "adu_hex"),
    [
        (Request(1, FC.READ_COILS, 0x13, 0x13), "01 01 00 13 00 13 8C 02"),
        (Request(1, FC.READ_DISCRETE_INPUTS, 0xC4, 0x16), "01 02 00 C4 00 16 B8 39"),
        (Request(1, FC.READ_HOLDING_REGISTERS, 0, 1), "01 03 00 00 00 01 84 0A"),
        (Request(17, FC.READ_INPUT_REGISTERS, 8, 1), "11 04 00 08 00 01 B2 98"),
        (Request(1, FC.WRITE_SINGLE_COIL, 0xAC, values=(1,)), "01 05 00 AC FF 00 4C 1B"),
        (Request(1, FC.WRITE_SINGLE_REGISTER, 1, values=(3,)), "01 06 00 01 00 03 98 0B"),
        (Request(3, FC.WRITE_MULTIPLE_COILS, 5, values=(1, 0, 1)), "03 0F 00 05 00 03 01 05 4E 5B"),
        (Request(3, FC.WRITE_MULTIPLE_REGISTERS, 5, values=(1, 2)), "03 10 00 05 00 02 04 00 01 00 02 87 86"),
    ],
)
def test_build_adu(req, adu_hex):
    expected = bytes.fromhex(adu_hex.replace(" ", ""))
    adu = build_adu(req)
    # Le CRC est vérifié séparément : on compare le corps et on vérifie la cohérence du CRC.
    assert adu[:-2] == expected[:-2]
    assert adu == append_crc(expected[:-2])


def test_build_matches_pymodbus_oracle():
    rm = pytest.importorskip("pymodbus.pdu.register_message")
    bm = pytest.importorskip("pymodbus.pdu.bit_message")
    cases = [
        (
            Request(1, FC.READ_HOLDING_REGISTERS, 10, 4),
            rm.ReadHoldingRegistersRequest(address=10, count=4, dev_id=1),
        ),
        (
            Request(3, FC.WRITE_MULTIPLE_REGISTERS, 5, values=(1, 2)),
            rm.WriteMultipleRegistersRequest(address=5, registers=[1, 2], dev_id=3),
        ),
        (
            Request(3, FC.WRITE_MULTIPLE_COILS, 5, values=(1, 0, 1)),
            bm.WriteMultipleCoilsRequest(address=5, bits=[True, False, True], dev_id=3),
        ),
        (
            Request(1, FC.WRITE_SINGLE_COIL, 7, values=(1,)),
            bm.WriteSingleCoilRequest(address=7, bits=[True], dev_id=1),
        ),
    ]
    for req, oracle in cases:
        assert build_pdu(req) == bytes([oracle.function_code]) + oracle.encode()


def test_expected_lengths():
    assert expected_response_length(Request(1, FC.READ_COILS, 0, 19)) == 8
    assert expected_response_length(Request(1, FC.READ_HOLDING_REGISTERS, 0, 3)) == 11
    assert expected_response_length(Request(1, FC.WRITE_SINGLE_REGISTER, 0, values=(1,))) == 8


def test_parse_read_registers():
    req = Request(1, FC.READ_HOLDING_REGISTERS, 0, 2)
    resp = append_crc(bytes.fromhex("0103040001FFFF"))
    assert parse_response(req, resp) == (1, 0xFFFF)


def test_parse_read_bits():
    req = Request(1, FC.READ_COILS, 0, 10)
    resp = append_crc(bytes.fromhex("010102CD01"))  # CD = 1100 1101 -> bits 0..7 : 1,0,1,1,0,0,1,1
    assert parse_response(req, resp) == (1, 0, 1, 1, 0, 0, 1, 1, 1, 0)


def test_parse_write_ack():
    req = Request(1, FC.WRITE_SINGLE_REGISTER, 1, values=(3,))
    assert parse_response(req, append_crc(bytes.fromhex("010600010003"))) == ()
    req15 = Request(3, FC.WRITE_MULTIPLE_COILS, 5, values=(1, 0, 1))
    assert parse_response(req15, append_crc(bytes.fromhex("030F00050003"))) == ()
    with pytest.raises(BadResponse):
        parse_response(req, append_crc(bytes.fromhex("010600010004")))


def test_parse_exception():
    req = Request(1, FC.READ_HOLDING_REGISTERS, 0, 1)
    with pytest.raises(ModbusException) as exc:
        parse_response(req, append_crc(bytes.fromhex("018302")))
    assert exc.value.code == 2
    assert "Adresse" in str(exc.value)


def test_parse_crc_error_and_truncated():
    req = Request(1, FC.READ_HOLDING_REGISTERS, 0, 1)
    good = append_crc(bytes.fromhex("0103020000"))
    with pytest.raises(CrcError):
        parse_response(req, good[:-1] + b"\x00")
    with pytest.raises(CrcError):
        parse_response(req, good[:3])


def test_parse_bad_response():
    req = Request(1, FC.READ_HOLDING_REGISTERS, 0, 1)
    with pytest.raises(BadResponse, match="esclave 2"):
        parse_response(req, append_crc(bytes.fromhex("0203020000")))
    with pytest.raises(BadResponse, match="fonction"):
        parse_response(req, append_crc(bytes.fromhex("0104020000")))
    with pytest.raises(BadResponse, match="Longueur"):
        parse_response(req, append_crc(bytes.fromhex("01030400000000")))


@pytest.mark.parametrize(
    "req",
    [
        Request(248, FC.READ_COILS, 0, 1),
        Request(1, FC.READ_HOLDING_REGISTERS, 0, 126),
        Request(1, FC.READ_HOLDING_REGISTERS, 65535, 2),
        Request(1, FC.WRITE_SINGLE_REGISTER, 0, values=(70000,)),
        Request(1, FC.WRITE_MULTIPLE_REGISTERS, 0, values=()),
    ],
)
def test_validate_rejects(req):
    with pytest.raises(ValueError):
        build_adu(req)


def test_identification_functions():
    req = Request(1, FC.READ_DEVICE_ID, 1, 0)
    assert build_pdu(req) == bytes.fromhex("2B0E0100")
    assert expected_response_length(req) is None
    # Réponse basique : MEI, code lecture, conformité, plus de suit, prochain objet, nb objets, objets
    body = bytes.fromhex("0E 01 01 00 00 02 00 06") + b"Vendor" + bytes.fromhex("01 02") + b"PC"
    resp = append_crc(bytes([1, 0x2B]) + body)
    assert bytes(parse_response(req, resp)) == body
    with pytest.raises(BadResponse):
        parse_response(req, append_crc(bytes.fromhex("012B0D0101000000")))

    req17 = Request(1, FC.REPORT_SLAVE_ID, 0)
    assert build_pdu(req17) == b"\x11"
    resp17 = append_crc(bytes.fromhex("0111 03 42 FF 07".replace(" ", "")))
    assert parse_response(req17, resp17) == (0x42, 0xFF, 0x07)
    with pytest.raises(BadResponse):
        parse_response(req17, append_crc(bytes.fromhex("0111054200")))
    with pytest.raises(ValueError):
        build_pdu(Request(1, FC.READ_DEVICE_ID, 5, 0))
