from modbusai.transport.records import Parity, SerialSettings


def test_parity_coerced_from_plain_string():
    """Qt renvoie un StrEnum comme chaîne : SerialSettings doit le normaliser."""
    s = SerialSettings("COM3", parity="N", stopbits=1, bytesize=8)
    assert s.parity is Parity.NONE
    assert s.parity.value == "N"
    assert s.bits_per_char == 10  # start + 8 + stop, sans bit de parité
    assert SerialSettings("COM3", parity="E").bits_per_char == 11


def test_t35_and_gap():
    s = SerialSettings("COM3", baudrate=9600)
    assert round(s.t35_ms, 3) == 3.646  # 3,5 x 10 bits a 9600 bauds
    assert s.frame_gap_ms == 5.0
    assert SerialSettings("COM3", baudrate=115200).t35_ms == 1.75
    assert SerialSettings("COM3", inter_frame_delay_ms=2.0).frame_gap_ms == 2.0


def test_summary():
    assert SerialSettings("COM4", parity=Parity.EVEN, stopbits=2).summary() == "COM4 : 19200,8,Even,Two"
