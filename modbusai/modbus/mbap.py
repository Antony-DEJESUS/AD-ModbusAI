"""Enveloppe MBAP de Modbus TCP : identifiant de transaction, protocole 0,
longueur, identifiant d'unité, puis la PDU. Remplace l'adresse esclave et le
CRC de la trame RTU."""

from __future__ import annotations

from dataclasses import dataclass

MBAP_LENGTH = 7
PROTOCOL_MODBUS = 0
MAX_PDU = 253


@dataclass(frozen=True, slots=True)
class Mbap:
    transaction_id: int
    unit_id: int
    pdu: bytes


def build_mbap(transaction_id: int, unit_id: int, pdu: bytes) -> bytes:
    if not 0 <= transaction_id <= 0xFFFF:
        raise ValueError("Identifiant de transaction hors plage")
    if not 0 <= unit_id <= 0xFF:
        raise ValueError("Identifiant d'unité hors plage")
    if not 1 <= len(pdu) <= MAX_PDU:
        raise ValueError("PDU vide ou trop longue")
    return (
        transaction_id.to_bytes(2, "big")
        + PROTOCOL_MODBUS.to_bytes(2, "big")
        + (len(pdu) + 1).to_bytes(2, "big")
        + bytes([unit_id])
        + pdu
    )


def frame_length(header: bytes) -> int | None:
    """Longueur totale d'une trame dont on a au moins les 6 premiers octets,
    None si l'en-tête est incomplet ou incohérent."""
    if len(header) < 6:
        return None
    length = int.from_bytes(header[4:6], "big")
    if length < 2 or length > MAX_PDU + 1:
        return None
    return 6 + length


def parse_mbap(frame: bytes) -> Mbap:
    """Lève ``ValueError`` si l'enveloppe est incohérente."""
    if len(frame) < MBAP_LENGTH + 1:
        raise ValueError(f"Trame MBAP trop courte ({len(frame)} octets)")
    tid = int.from_bytes(frame[0:2], "big")
    proto = int.from_bytes(frame[2:4], "big")
    length = int.from_bytes(frame[4:6], "big")
    if proto != PROTOCOL_MODBUS:
        raise ValueError(f"Protocole MBAP {proto} inattendu")
    if length != len(frame) - 6:
        raise ValueError(f"Longueur MBAP {length} incohérente avec {len(frame) - 6} octets")
    return Mbap(tid, frame[6], bytes(frame[7:]))
