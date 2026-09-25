"""Port fermé par un autre fil en pleine lecture : la liaison doit dire « Liaison
fermée », pas laisser passer l'exception brute de pyserial."""

import pytest

from modbusai.transport.records import SerialSettings, TransportError
from modbusai.transport.serial_link import SerialLink


class _ClosedDuringRead:
    """Imite pyserial sous Linux quand close() survient pendant read() :
    le descripteur devient None et select() lève TypeError."""

    def __init__(self) -> None:
        self.is_open = True
        self.in_waiting = 0

    def read(self, _n: int) -> bytes:
        self.is_open = False
        raise TypeError("'NoneType' object cannot be interpreted as an integer")


def test_port_closed_during_receive_is_a_transport_error():
    link = SerialLink(SerialSettings(port="COM99"))
    link._ser = _ClosedDuringRead()
    with pytest.raises(TransportError, match="Liaison fermée"):
        link.receive(100)
