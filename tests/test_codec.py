import pytest

from modbusai.modbus.codec import (
    DisplayMode,
    DisplayOptions,
    Radix,
    WordOrder,
    format_bits,
    format_registers,
    parse_bits,
    parse_rows,
    regs_to_u32,
    u32_to_regs,
)


@pytest.mark.parametrize("order", list(WordOrder))
def test_u32_roundtrip(order):
    for value in (0, 1, 0x12345678, 0xFFFFFFFF, 0x0000FFFF):
        hi, lo = u32_to_regs(value, order)
        assert regs_to_u32(hi, lo, order) == value


def test_word_orders_on_known_value():
    # 0x12345678 : A=12 B=34 C=56 D=78
    assert u32_to_regs(0x12345678, WordOrder.ABCD) == (0x1234, 0x5678)
    assert u32_to_regs(0x12345678, WordOrder.CDAB) == (0x5678, 0x1234)
    assert u32_to_regs(0x12345678, WordOrder.BADC) == (0x3412, 0x7856)
    assert u32_to_regs(0x12345678, WordOrder.DCBA) == (0x7856, 0x3412)


def test_word16_formats():
    regs = [0xFFFF, 0x0010]
    dec_signed = format_registers(regs, 0, DisplayOptions())
    assert [r.text for r in dec_signed] == ["-1", "16"]
    assert [r.label for r in dec_signed] == ["0", "1"]
    dec_unsigned = format_registers(regs, 100, DisplayOptions(signed=False))
    assert [r.text for r in dec_unsigned] == ["65535", "16"]
    assert dec_unsigned[0].label == "100"
    assert [r.text for r in format_registers(regs, 0, DisplayOptions(radix=Radix.HEX))] == ["FFFF", "0010"]
    assert format_registers([5], 0, DisplayOptions(radix=Radix.BIN))[0].text == "0000 0000 0000 0101"


def test_bits_and_bytes_modes():
    rows = format_registers([0x0105], 0, DisplayOptions(mode=DisplayMode.BITS))
    assert rows[0].text == "0000 0001 0000 0101"
    rows = format_registers([0x01FF], 0, DisplayOptions(mode=DisplayMode.BYTE8))
    assert [(r.label, r.text) for r in rows] == [("0 H", "1"), ("0 L", "-1")]
    rows = format_registers([0x01FF], 0, DisplayOptions(mode=DisplayMode.BYTE8, byte_swap=True, signed=False))
    assert [r.text for r in rows] == ["255", "1"]


def test_word32_and_float():
    regs = [0x4048, 0xF5C3]  # 3.14 en float32 big-endian
    rows = format_registers(regs, 10, DisplayOptions(mode=DisplayMode.FLOAT32))
    assert rows[0].label == "10-11"
    assert rows[0].text == "3.14"
    swapped = format_registers([0xF5C3, 0x4048], 10, DisplayOptions(mode=DisplayMode.FLOAT32, word_swap=True))
    assert swapped[0].text == rows[0].text
    rows = format_registers([0xFFFF, 0xFFFE], 0, DisplayOptions(mode=DisplayMode.WORD32))
    assert rows[0].text == "-2"
    rows = format_registers([0xFFFF, 0xFFFE], 0, DisplayOptions(mode=DisplayMode.WORD32, signed=False, radix=Radix.HEX))
    assert rows[0].text == "FFFFFFFE"
    # registre orphelin affiché seul en 16 bits
    rows = format_registers([1, 2, 3], 0, DisplayOptions(mode=DisplayMode.WORD32))
    assert [r.label for r in rows] == ["0-1", "2"]


def test_parse_rows_roundtrip_all_modes():
    regs = [0x4048, 0xF5C3, 0x8001, 0x0002]
    for mode in DisplayMode:
        for radix in Radix:
            for signed in (True, False):
                for bs in (False, True):
                    for ws in (False, True):
                        opts = DisplayOptions(mode, radix, signed, bs, ws)
                        rows = format_registers(regs, 0, opts)
                        back = parse_rows([r.text for r in rows], len(regs), opts)
                        assert back == regs, (mode, radix, signed, bs, ws)


def test_parse_rows_errors():
    with pytest.raises(ValueError, match="attendue"):
        parse_rows(["1", "2"], 1, DisplayOptions())
    with pytest.raises(ValueError, match="hors plage"):
        parse_rows(["70000"], 1, DisplayOptions(signed=False))
    with pytest.raises(ValueError, match="négative"):
        parse_rows(["-1"], 1, DisplayOptions(signed=False))
    assert parse_rows(["-1"], 1, DisplayOptions()) == [0xFFFF]
    assert parse_rows(["0xAbCd"], 1, DisplayOptions(radix=Radix.HEX)) == [0xABCD]
    assert parse_rows(["1,5"], 2, DisplayOptions(mode=DisplayMode.FLOAT32)) == [0x3FC0, 0x0000]


def test_bits():
    assert [r.text for r in format_bits([1, 0, 1], 5)] == ["1", "0", "1"]
    assert format_bits([1], 5)[0].label == "5"
    assert parse_bits(["1", "0", "on", ""]) == [1, 0, 1, 0]
    with pytest.raises(ValueError):
        parse_bits(["2"])
