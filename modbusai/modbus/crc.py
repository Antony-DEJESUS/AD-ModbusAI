"""CRC16 Modbus (polynôme 0xA001, init 0xFFFF), table précalculée."""

from __future__ import annotations


def _build_table() -> tuple[int, ...]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        table.append(crc)
    return tuple(table)


_TABLE = _build_table()


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ _TABLE[(crc ^ b) & 0xFF]
    return crc


def append_crc(data: bytes) -> bytes:
    """Ajoute le CRC en fin de trame, octet de poids faible d'abord (ordre RTU)."""
    return data + crc16(data).to_bytes(2, "little")


def check_crc(frame: bytes) -> bool:
    """Vrai si les deux derniers octets sont le CRC du reste."""
    if len(frame) < 3:
        return False
    return crc16(frame[:-2]) == int.from_bytes(frame[-2:], "little")
